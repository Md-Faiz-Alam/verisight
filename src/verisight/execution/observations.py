"""Observed evidence produced by analytical query execution."""

from dataclasses import dataclass, field

from verisight.execution.context import CountingGrainReview, PopulationReview
from verisight.execution.execution import QueryRepairAttempt
from verisight.execution.models import QueryResult


@dataclass(frozen=True, slots=True)
class QueryObservation:
    """One executed analytical observation with its provenance."""

    question: str
    sql: str
    result: QueryResult
    repair_history: tuple[QueryRepairAttempt, ...] = field(default=(), kw_only=True)
    population_review: PopulationReview | None = field(default=None, kw_only=True)
    grain_review: CountingGrainReview | None = field(default=None, kw_only=True)
