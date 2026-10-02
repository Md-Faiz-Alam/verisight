"""Exceptions raised by VeriSight analytical execution."""


class QueryExecutionError(Exception):
    """Raised when an analytical query cannot be executed."""


class QueryPlanningError(Exception):
    """Raised when an analytical query cannot be planned."""
