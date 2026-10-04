"""Exceptions raised by VeriSight analytical execution."""


class QueryExecutionError(Exception):
    """Base exception for analytical query execution failures."""


class QueryValidationError(QueryExecutionError):
    """Raised when an analytical query violates the execution boundary."""


class QueryRuntimeError(QueryExecutionError):
    """Raised when an allowed analytical query fails during execution."""


class QueryResultLimitError(QueryExecutionError):
    """Raised when an analytical query exceeds the allowed result size."""


class QueryPlanningError(Exception):
    """Raised when an analytical query cannot be planned."""


class InvestigationError(Exception):
    """Raised when an autonomous investigation cannot proceed."""
