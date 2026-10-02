"""Domain models and contracts for analytical query planning."""

from dataclasses import dataclass
from typing import Protocol

from verisight.execution.context import QueryContext


@dataclass(frozen=True, slots=True)
class QueryRequest:
    """A natural-language analytical query request."""

    question: str
    context: QueryContext


@dataclass(frozen=True, slots=True)
class QueryPlan:
    """A planned analytical query ready for execution."""

    question: str
    sql: str


class QueryPlanner(Protocol):
    """Contract for components that plan analytical queries."""

    def plan(self, request: QueryRequest) -> QueryPlan:
        """Create an analytical query plan for a request."""
        ...
