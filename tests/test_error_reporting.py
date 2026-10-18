"""Tests for safe public error reporting."""

import pytest

from verisight.error_reporting import (
    ErrorCode,
    PublicErrorReport,
    to_public_error,
)
from verisight.exceptions import ConfigurationError, VeriSightError
from verisight.execution.exceptions import (
    InvestigationError,
    QueryExecutionError,
    QueryPlanningError,
    QueryResultLimitError,
    QueryRuntimeError,
    QueryTimeoutError,
    QueryValidationError,
)
from verisight.execution.gemini import GeminiGenerationError, GeminiTransientError
from verisight.execution.prompt_budget import PromptBudgetExceededError
from verisight.ingestion.exceptions import (
    DataLoadError,
    FileValidationError,
    IngestionError,
    TableValidationError,
    UnsupportedFileTypeError,
)


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_message"),
    [
        (
            UnsupportedFileTypeError("Sensitive input details"),
            ErrorCode.UNSUPPORTED_FILE_TYPE,
            "The dataset file type is not supported.",
        ),
        (
            FileValidationError("Sensitive input details"),
            ErrorCode.FILE_VALIDATION_ERROR,
            "The dataset file input did not pass validation.",
        ),
        (
            DataLoadError("Sensitive input details"),
            ErrorCode.DATA_LOAD_ERROR,
            "The dataset file could not be loaded.",
        ),
        (
            TableValidationError("Sensitive input details"),
            ErrorCode.TABLE_VALIDATION_ERROR,
            "The dataset table structure did not pass validation.",
        ),
        (
            IngestionError("Sensitive input details"),
            ErrorCode.INGESTION_ERROR,
            "The dataset could not be ingested.",
        ),
        (
            PromptBudgetExceededError(max_prompt_chars=10, actual_prompt_chars=11),
            ErrorCode.PROMPT_BUDGET_EXCEEDED,
            "The analytical request exceeded the allowed prompt size.",
        ),
        (
            ConfigurationError("secret=config-value"),
            ErrorCode.CONFIGURATION_ERROR,
            "Application configuration is unavailable or invalid.",
        ),
        (
            GeminiTransientError("Sensitive provider details"),
            ErrorCode.PROVIDER_UNAVAILABLE,
            "The AI provider is temporarily unavailable.",
        ),
        (
            QueryValidationError("SELECT secret FROM private_table"),
            ErrorCode.QUERY_VALIDATION_ERROR,
            "The analytical query did not pass validation.",
        ),
        (
            QueryResultLimitError("Sensitive row details"),
            ErrorCode.QUERY_RESULT_LIMIT_ERROR,
            "The analytical query exceeded the allowed result size.",
        ),
        (
            QueryTimeoutError("Sensitive SQL statement"),
            ErrorCode.QUERY_TIMEOUT_ERROR,
            "The analytical query exceeded its execution time limit.",
        ),
        (
            QueryRuntimeError("Customer email: private@example.com"),
            ErrorCode.QUERY_RUNTIME_ERROR,
            "The analytical query could not be executed.",
        ),
        (
            QueryPlanningError("Raw provider response"),
            ErrorCode.QUERY_PLANNING_ERROR,
            "The analytical query could not be planned.",
        ),
        (
            InvestigationError("Sensitive investigation context"),
            ErrorCode.INVESTIGATION_ERROR,
            "The analytical investigation could not be completed.",
        ),
        (
            GeminiGenerationError("Permanent provider failure"),
            ErrorCode.INTERNAL_ERROR,
            "An unexpected application error occurred.",
        ),
        (
            QueryExecutionError("Internal execution information"),
            ErrorCode.INTERNAL_ERROR,
            "An unexpected application error occurred.",
        ),
        (
            VeriSightError("Sensitive application information"),
            ErrorCode.INTERNAL_ERROR,
            "An unexpected application error occurred.",
        ),
        (
            RuntimeError("Unknown internal failure"),
            ErrorCode.INTERNAL_ERROR,
            "An unexpected application error occurred.",
        ),
    ],
)
def test_maps_errors_to_safe_public_reports(
    error: Exception,
    expected_code: ErrorCode,
    expected_message: str,
) -> None:
    report = to_public_error(error)

    assert isinstance(report, PublicErrorReport)
    assert report.code == expected_code
    assert report.message == expected_message
    assert str(error) not in report.message


def test_public_report_does_not_expose_chained_exception() -> None:
    secret = "private-provider-token-123"

    try:
        raise RuntimeError(f"Provider failed with token {secret}")
    except RuntimeError as original:
        error = QueryPlanningError("Query planning failed.")
        error.__cause__ = original

    report = to_public_error(error)

    assert report.code == ErrorCode.QUERY_PLANNING_ERROR
    assert secret not in repr(report)
    assert secret not in report.message
    assert report.message == "The analytical query could not be planned."


def test_public_report_does_not_expose_sensitive_runtime_details() -> None:
    secret_sql = "SELECT confidential_salary FROM employees"
    error = QueryRuntimeError(f"Analytical query execution failed: {secret_sql}")

    report = to_public_error(error)

    assert report.code == ErrorCode.QUERY_RUNTIME_ERROR
    assert secret_sql not in repr(report)
    assert "confidential_salary" not in report.message


def test_public_report_is_immutable() -> None:
    report = to_public_error(QueryTimeoutError("Timeout"))

    with pytest.raises(AttributeError):
        report.message = "Changed"  # type: ignore[misc]


def test_public_report_preserves_internal_exception() -> None:
    error = QueryRuntimeError("Analytical query execution failed: missing_amount")

    report = to_public_error(error)

    assert report.code == ErrorCode.QUERY_RUNTIME_ERROR
    assert "missing_amount" not in report.message
    assert "missing_amount" in str(error)


def test_ingestion_report_hides_chained_parser_details() -> None:
    secret = "private-customer-value"
    original = ValueError(f"Parser failed at {secret}")
    error = DataLoadError("Could not load /private/customer-data.csv")
    error.__cause__ = original

    report = to_public_error(error)

    assert report.code is ErrorCode.DATA_LOAD_ERROR
    assert secret not in repr(report)
    assert "/private/" not in repr(report)
    assert error.__cause__ is original


def test_transient_provider_report_hides_sensitive_details() -> None:
    secret = "synthetic-private-provider-token"
    error = GeminiTransientError(f"Provider timeout for token {secret}")

    report = to_public_error(error)

    assert report.code is ErrorCode.PROVIDER_UNAVAILABLE
    assert report.message == "The AI provider is temporarily unavailable."
    assert secret not in repr(report)
    assert secret not in report.message


def test_transient_provider_report_hides_chained_details() -> None:
    secret = "synthetic-private-provider-token"
    original = TimeoutError(f"Provider request contained {secret}")
    error = GeminiTransientError("Temporary provider failure.")
    error.__cause__ = original

    report = to_public_error(error)

    assert report.code is ErrorCode.PROVIDER_UNAVAILABLE
    assert secret not in repr(report)
    assert error.__cause__ is original
