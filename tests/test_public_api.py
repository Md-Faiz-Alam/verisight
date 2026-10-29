"""Tests for the framework-independent public operation boundary."""

import logging
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from verisight import VeriSight
from verisight.config import Settings
from verisight.error_reporting import ErrorCode
from verisight.execution.exceptions import (
    InvestigationError,
    QueryPlanningError,
    QueryRuntimeError,
    QueryValidationError,
)
from verisight.execution.gemini import (
    GeminiGenerationError,
    GeminiTransientError,
    ProviderFailureDiagnostics,
)
from verisight.execution.prompt_budget import PromptBudget
from verisight.ingestion.exceptions import FileValidationError
from verisight.public_api import run_public_operation
from verisight.serialization import to_jsonable


def test_public_operation_returns_successful_value() -> None:
    result = run_public_operation(lambda: 42)

    assert result.succeeded is True
    assert result.value == 42
    assert result.error is None


def test_public_operation_preserves_none_result() -> None:
    result = run_public_operation(lambda: None)

    assert result.succeeded is True
    assert result.value is None
    assert result.error is None


@pytest.mark.parametrize(
    ("exception", "expected_code"),
    [
        (
            QueryValidationError("Sensitive validation detail"),
            ErrorCode.QUERY_VALIDATION_ERROR,
        ),
        (
            QueryRuntimeError("Sensitive database detail"),
            ErrorCode.QUERY_RUNTIME_ERROR,
        ),
        (
            QueryPlanningError("Sensitive provider detail"),
            ErrorCode.QUERY_PLANNING_ERROR,
        ),
        (
            InvestigationError("Sensitive investigation detail"),
            ErrorCode.INVESTIGATION_ERROR,
        ),
        (
            RuntimeError("Sensitive unexpected detail"),
            ErrorCode.INTERNAL_ERROR,
        ),
    ],
)
def test_public_operation_sanitizes_failures(
    exception: Exception,
    expected_code: ErrorCode,
) -> None:
    secret = "Sensitive"

    def failing_operation() -> int:
        raise exception

    result = run_public_operation(failing_operation)

    assert result.succeeded is False
    assert result.value is None
    assert result.error is not None
    assert result.error.code == expected_code
    assert secret not in repr(result)


def test_public_operation_does_not_expose_chained_exception() -> None:
    secret = "private-provider-token-456"

    def failing_operation() -> str:
        try:
            raise RuntimeError(f"Provider token: {secret}")
        except RuntimeError as exc:
            raise QueryPlanningError("Planning failed.") from exc

    result = run_public_operation(failing_operation)

    assert result.error is not None
    assert result.error.code == ErrorCode.QUERY_PLANNING_ERROR
    assert secret not in repr(result)


def test_public_operation_preserves_successful_data_identity() -> None:
    value = {"rows": [(1, 10.0)]}

    result = run_public_operation(lambda: value)

    assert result.succeeded is True
    assert result.value is value


@pytest.mark.parametrize(
    ("scenario", "expected_code"),
    [
        ("missing", ErrorCode.FILE_VALIDATION_ERROR),
        ("unsupported", ErrorCode.UNSUPPORTED_FILE_TYPE),
        ("oversized", ErrorCode.FILE_VALIDATION_ERROR),
        ("malformed", ErrorCode.DATA_LOAD_ERROR),
        ("empty_input", ErrorCode.FILE_VALIDATION_ERROR),
    ],
)
def test_public_boundary_classifies_actual_ingestion_failures(
    tmp_path: Path,
    scenario: str,
    expected_code: ErrorCode,
) -> None:
    path = tmp_path / "private-dataset.csv"
    paths: list[Path] = [path]

    if scenario == "unsupported":
        path = tmp_path / "private-dataset.txt"
        path.write_text("private-value", encoding="utf-8")
        paths = [path]
    elif scenario == "oversized":
        path.write_bytes(b"x" * (1024 * 1024 + 1))
    elif scenario == "malformed":
        path = tmp_path / "private-dataset.json"
        path.write_text('{"private-value":', encoding="utf-8")
        paths = [path]
    elif scenario == "empty_input":
        paths = []

    app = VeriSight(
        settings=Settings(max_upload_size_mb=1, allow_llm_data_disclosure=False)
    )

    result = run_public_operation(lambda: app.analyze(paths))

    assert result.succeeded is False
    assert result.value is None
    assert result.error is not None
    assert result.error.code is expected_code
    assert "private-dataset" not in repr(result)
    assert "private-value" not in repr(result)
    assert str(tmp_path) not in repr(result)


def test_public_boundary_classifies_escaping_prompt_budget_error() -> None:
    budget = PromptBudget(max_prompt_chars=10)

    result = run_public_operation(lambda: budget.enforce("private-prompt-content"))

    assert result.succeeded is False
    assert result.error is not None
    assert result.error.code is ErrorCode.PROMPT_BUDGET_EXCEEDED
    assert "private-prompt-content" not in repr(result)


@pytest.mark.parametrize("operation", ["analyze", "execute", "ask", "investigate"])
@pytest.mark.parametrize("invalid_input", [None, 42, True, 1.5, object()])
def test_public_workflows_reject_non_iterable_dataset_input(
    operation: str, invalid_input: Any
) -> None:
    app = VeriSight(settings=Settings(allow_llm_data_disclosure=False))
    operations: dict[str, Callable[[], object]] = {
        "analyze": lambda: app.analyze(invalid_input),
        "execute": lambda: app.execute(invalid_input, "SELECT 1"),
        "ask": lambda: app.ask(invalid_input, "Count the rows"),
        "investigate": lambda: app.investigate(invalid_input, "Count the rows"),
    }

    with pytest.raises(FileValidationError, match="file path or an iterable"):
        operations[operation]()

    result = run_public_operation(operations[operation])

    assert result.succeeded is False
    assert result.value is None
    assert result.error is not None
    assert result.error.code is ErrorCode.FILE_VALIDATION_ERROR


def test_public_boundary_keeps_iterator_execution_bug_as_internal_error() -> None:
    class BrokenPaths:
        def __iter__(self) -> Iterator[str]:
            return self

        def __next__(self) -> str:
            raise TypeError("private iterator implementation detail")

    app = VeriSight(settings=Settings(allow_llm_data_disclosure=False))

    result = run_public_operation(lambda: app.analyze(BrokenPaths()))

    assert result.succeeded is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INTERNAL_ERROR
    assert "private iterator" not in repr(result)


def test_public_operation_logs_unexpected_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def failing_operation() -> int:
        raise ZeroDivisionError("Sensitive calculation details")

    with caplog.at_level(logging.ERROR, logger="verisight.public_api"):
        result = run_public_operation(failing_operation)

    assert result.succeeded is False
    assert result.error is not None
    assert result.error.code is ErrorCode.INTERNAL_ERROR

    records = [
        record for record in caplog.records if record.name == "verisight.public_api"
    ]

    assert len(records) == 1
    assert records[0].levelno == logging.ERROR
    assert records[0].getMessage() == (
        "Unexpected public operation failure: ZeroDivisionError"
    )
    assert records[0].exc_info is None
    assert "Sensitive calculation details" not in caplog.text


def test_public_operation_does_not_log_expected_errors(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def failing_operation() -> int:
        raise QueryValidationError("Sensitive SQL contents")

    with caplog.at_level(logging.ERROR, logger="verisight.public_api"):
        result = run_public_operation(failing_operation)

    assert result.error is not None
    assert result.error.code is ErrorCode.QUERY_VALIDATION_ERROR
    assert not [
        record for record in caplog.records if record.name == "verisight.public_api"
    ]


def test_public_operation_logs_no_exception_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "private-api-key-123"

    def failing_operation() -> int:
        try:
            raise ValueError(f"Credential: {secret}")
        except ValueError as exc:
            raise RuntimeError(f"Dataset value: {secret}") from exc

    with caplog.at_level(logging.ERROR, logger="verisight.public_api"):
        result = run_public_operation(failing_operation)

    assert result.error is not None
    assert result.error.code is ErrorCode.INTERNAL_ERROR
    assert secret not in repr(result)
    assert secret not in caplog.text
    assert "Credential:" not in caplog.text
    assert "Dataset value:" not in caplog.text
    assert "RuntimeError" in caplog.text


@pytest.mark.parametrize("http_status", [None, 503])
@pytest.mark.parametrize("wrapped", [False, True])
def test_public_operation_retains_only_safe_provider_diagnostics(
    http_status: int | None, wrapped: bool, caplog: pytest.LogCaptureFixture
) -> None:
    details = ProviderFailureDiagnostics(http_status, True, 2, "text_generation", 3)
    provider = GeminiTransientError("private-provider-secret", diagnostics=details)

    def operation() -> None:
        if wrapped:
            raise QueryPlanningError("private-query-secret") from provider
        raise provider

    result = run_public_operation(operation)

    assert result.provider_diagnostics == details
    assert result.provider_diagnostics is not details
    assert result.error is not None
    assert result.error.code is (
        ErrorCode.QUERY_PLANNING_ERROR if wrapped else ErrorCode.PROVIDER_UNAVAILABLE
    )
    serialized = to_jsonable(result)
    assert isinstance(serialized, dict)
    assert serialized["provider_diagnostics"] == {
        "http_status": http_status,
        "retryable": True,
        "attempts": 2,
        "stage": "text_generation",
        "call_number": 3,
    }
    assert "private-" not in repr(result)
    assert "private-" not in caplog.text


@pytest.mark.parametrize(
    "overrides",
    [
        {"http_status": "private-status"},
        {"http_status": True},
        {"http_status": 99},
        {"http_status": 600},
        {"retryable": "private-retryability"},
        {"attempts": "private-attempts"},
        {"attempts": 0},
        {"stage": ["private-stage"]},
        {"stage": "private-stage"},
        {"call_number": "private-call"},
        {"call_number": 0},
    ],
)
def test_public_operation_omits_malformed_provider_metadata(
    overrides: dict[str, Any],
) -> None:
    values: dict[str, Any] = {
        "http_status": 503,
        "retryable": True,
        "attempts": 1,
        "stage": "investigator",
        "call_number": 1,
    }
    values.update(overrides)
    details = ProviderFailureDiagnostics(**values)

    def operation() -> None:
        raise GeminiTransientError("private-error", diagnostics=details)

    result = run_public_operation(operation)
    assert result.provider_diagnostics is None
    assert "private-" not in repr(result)


def test_public_operation_does_not_export_untyped_provider_metadata() -> None:
    error = GeminiTransientError("private-error")
    error.diagnostics = {"prompt": "private-prompt"}  # type: ignore[assignment]
    result = run_public_operation(lambda: _raise_provider(error))
    assert result.provider_diagnostics is None
    assert "private-" not in repr(result)


def _raise_provider(error: GeminiGenerationError) -> None:
    raise error


def test_public_operation_handles_missing_metadata_and_cause_cycles() -> None:
    missing = run_public_operation(
        lambda: _raise_provider(GeminiTransientError("private-error"))
    )
    assert missing.provider_diagnostics is None
    error = QueryPlanningError("private-cycle")
    error.__cause__ = error

    def operation() -> None:
        raise error

    result = run_public_operation(operation)
    assert result.provider_diagnostics is None
    assert result.error is not None
    assert result.error.code is ErrorCode.QUERY_PLANNING_ERROR


def test_public_operation_does_not_export_incidental_provider_context() -> None:
    details = ProviderFailureDiagnostics(503, True, 1, "investigator", 1)

    def operation() -> None:
        try:
            raise GeminiTransientError("private-provider", diagnostics=details)
        except GeminiTransientError:
            raise QueryPlanningError("private-outer") from None

    result = run_public_operation(operation)
    assert result.provider_diagnostics is None
    assert result.error is not None
    assert result.error.code is ErrorCode.QUERY_PLANNING_ERROR
