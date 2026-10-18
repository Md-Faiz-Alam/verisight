"""Safe, structured error reports for external consumers."""

from dataclasses import dataclass
from enum import StrEnum

from verisight.exceptions import ConfigurationError
from verisight.execution.exceptions import (
    InvestigationError,
    QueryPlanningError,
    QueryResultLimitError,
    QueryRuntimeError,
    QueryTimeoutError,
    QueryValidationError,
)
from verisight.execution.prompt_budget import PromptBudgetExceededError
from verisight.ingestion.exceptions import (
    DataLoadError,
    FileValidationError,
    IngestionError,
    TableValidationError,
    UnsupportedFileTypeError,
)


class ErrorCode(StrEnum):
    """Stable identifiers for externally reported failures."""

    CONFIGURATION_ERROR = "configuration_error"
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
    FILE_VALIDATION_ERROR = "file_validation_error"
    DATA_LOAD_ERROR = "data_load_error"
    TABLE_VALIDATION_ERROR = "table_validation_error"
    INGESTION_ERROR = "ingestion_error"
    PROMPT_BUDGET_EXCEEDED = "prompt_budget_exceeded"
    QUERY_VALIDATION_ERROR = "query_validation_error"
    QUERY_RUNTIME_ERROR = "query_runtime_error"
    QUERY_RESULT_LIMIT_ERROR = "query_result_limit_error"
    QUERY_TIMEOUT_ERROR = "query_timeout_error"
    QUERY_PLANNING_ERROR = "query_planning_error"
    INVESTIGATION_ERROR = "investigation_error"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True, slots=True)
class PublicErrorReport:
    """An error report containing only approved public information."""

    code: ErrorCode
    message: str


def to_public_error(error: Exception) -> PublicErrorReport:
    """Convert an exception to a safe public error report.

    Do not include raw exception messages, chained exceptions,
    tracebacks, SQL statements, or dataset values.
    """

    if isinstance(error, ConfigurationError):
        return PublicErrorReport(
            code=ErrorCode.CONFIGURATION_ERROR,
            message="Application configuration is unavailable or invalid.",
        )

    if isinstance(error, UnsupportedFileTypeError):
        return PublicErrorReport(
            code=ErrorCode.UNSUPPORTED_FILE_TYPE,
            message="The dataset file type is not supported.",
        )

    if isinstance(error, FileValidationError):
        return PublicErrorReport(
            code=ErrorCode.FILE_VALIDATION_ERROR,
            message="The dataset file input did not pass validation.",
        )

    if isinstance(error, DataLoadError):
        return PublicErrorReport(
            code=ErrorCode.DATA_LOAD_ERROR,
            message="The dataset file could not be loaded.",
        )

    if isinstance(error, TableValidationError):
        return PublicErrorReport(
            code=ErrorCode.TABLE_VALIDATION_ERROR,
            message="The dataset table structure did not pass validation.",
        )

    if isinstance(error, IngestionError):
        return PublicErrorReport(
            code=ErrorCode.INGESTION_ERROR,
            message="The dataset could not be ingested.",
        )

    if isinstance(error, PromptBudgetExceededError):
        return PublicErrorReport(
            code=ErrorCode.PROMPT_BUDGET_EXCEEDED,
            message="The analytical request exceeded the allowed prompt size.",
        )

    if isinstance(error, QueryValidationError):
        return PublicErrorReport(
            code=ErrorCode.QUERY_VALIDATION_ERROR,
            message="The analytical query did not pass validation.",
        )

    if isinstance(error, QueryResultLimitError):
        return PublicErrorReport(
            code=ErrorCode.QUERY_RESULT_LIMIT_ERROR,
            message="The analytical query exceeded the allowed result size.",
        )

    if isinstance(error, QueryTimeoutError):
        return PublicErrorReport(
            code=ErrorCode.QUERY_TIMEOUT_ERROR,
            message="The analytical query exceeded its execution time limit.",
        )

    if isinstance(error, QueryRuntimeError):
        return PublicErrorReport(
            code=ErrorCode.QUERY_RUNTIME_ERROR,
            message="The analytical query could not be executed.",
        )

    if isinstance(error, QueryPlanningError):
        return PublicErrorReport(
            code=ErrorCode.QUERY_PLANNING_ERROR,
            message="The analytical query could not be planned.",
        )

    if isinstance(error, InvestigationError):
        return PublicErrorReport(
            code=ErrorCode.INVESTIGATION_ERROR,
            message="The analytical investigation could not be completed.",
        )

    return PublicErrorReport(
        code=ErrorCode.INTERNAL_ERROR,
        message="An unexpected application error occurred.",
    )
