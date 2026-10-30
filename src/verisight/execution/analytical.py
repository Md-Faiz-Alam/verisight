"""Contract for provenance-aware analytical query execution."""

from typing import Protocol

from verisight.execution.execution import QueryExecution


class AnalyticalQueryRunner(Protocol):
    """Contract for provenance-aware analytical query execution."""

    def run(
        self, question: str, *, original_question: str | None = None
    ) -> QueryExecution:
        """Plan and execute an analytical question with provenance."""
        ...
