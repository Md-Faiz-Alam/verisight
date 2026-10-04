"""Domain models and contracts for analytical query repair."""

from dataclasses import dataclass
from typing import Protocol

from verisight.execution.context import QueryContext
from verisight.execution.planning import QueryPlan


@dataclass(frozen=True, slots=True)
class QueryRepairRequest:
    """Request to repair a failed analytical query plan."""

    question: str
    failed_sql: str
    error: str
    context: QueryContext


class QueryRepairer(Protocol):
    """Contract for components that repair failed analytical queries."""

    def repair(self, request: QueryRepairRequest) -> QueryPlan:
        """Create a replacement query plan after a runtime failure."""
        ...
