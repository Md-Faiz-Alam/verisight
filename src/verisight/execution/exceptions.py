"""Exceptions raised by VeriSight analytical execution."""

from typing import Literal


class QueryExecutionError(Exception):
    """Base exception for analytical query execution failures."""


class QueryValidationError(QueryExecutionError):
    """Raised when an analytical query violates the execution boundary."""


class QueryRuntimeError(QueryExecutionError):
    """Raised when an allowed analytical query fails during execution."""


class QueryDataBindingError(QueryRuntimeError):
    """Raised when source numeric data cannot be bound exactly for SQL.

    SQL repair cannot resolve this registration failure. Preserve the existing
    runtime-error inheritance for callers and public error classification.
    """


class QueryResultLimitError(QueryExecutionError):
    """Raised when an analytical query exceeds the allowed result size."""


class QueryTimeoutError(QueryExecutionError):
    """Raised when an analytical query exceeds the allowed execution time."""


class QueryPlanningError(Exception):
    """Raised when an analytical query cannot be planned."""


class InvestigationError(Exception):
    """Raised when an autonomous investigation cannot proceed."""


SynthesisValidationReason = Literal[
    "response_too_large",
    "invalid_json",
    "invalid_schema_or_claim",
    "unlinked_narrative_number",
    "claim_output_contract_mismatch",
]


class SynthesisValidationError(InvestigationError):
    """Expose only an approved local validation category, never rejected content."""

    def __init__(
        self,
        reason: SynthesisValidationReason,
        *,
        repair_attempted: bool = False,
    ) -> None:
        if reason not in (
            "response_too_large",
            "invalid_json",
            "invalid_schema_or_claim",
            "unlinked_narrative_number",
            "claim_output_contract_mismatch",
        ):
            raise ValueError("Unsupported synthesis validation category.")
        if type(repair_attempted) is not bool:
            raise ValueError("Synthesis repair flag must be a boolean.")
        self.reason: SynthesisValidationReason = reason
        self.repair_attempted: bool = repair_attempted
        message = (
            "Structured synthesis response is too large."
            if reason == "response_too_large"
            else "Structured synthesis response is invalid."
        )
        super().__init__(message)
