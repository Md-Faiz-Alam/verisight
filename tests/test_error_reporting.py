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


@pytest.mark.parametrize(
    ("error", "expected_code", "expected_message"),
    [
        (
            ConfigurationError("secret=config-value"),
            ErrorCode.CONFIGURATION_ERROR,
            "Application configuration is unavailable or invalid.",
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
