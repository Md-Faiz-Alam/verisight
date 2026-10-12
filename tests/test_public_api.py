"""Tests for the framework-independent public operation boundary."""

import pytest

from verisight.error_reporting import ErrorCode
from verisight.execution.exceptions import (
    InvestigationError,
    QueryPlanningError,
    QueryRuntimeError,
    QueryValidationError,
)
from verisight.public_api import run_public_operation


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
