"""Contracts for analytical planning and execution."""

from typing import Protocol

from verisight.execution.execution import QueryExecution
from verisight.execution.models import QueryResult
from verisight.execution.planning import QueryPlan


class AnalyticalQueryService(Protocol):
    """Contract for complete analytical query services."""

    def plan(self, question: str) -> QueryPlan:
        """Plan an analytical query from a natural-language question."""
        ...

    def execute(self, query: str) -> QueryResult:
        """Execute an analytical query."""
        ...

    def run(self, question: str) -> QueryExecution:
        """Plan and execute an analytical question with provenance."""
        ...


class AnalyticalQueryRunner(Protocol):
    """Contract for provenance-aware analytical query execution."""

    def run(self, question: str) -> QueryExecution:
        """Plan and execute an analytical question with provenance."""
        ...
