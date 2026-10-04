"""Domain models for planned analytical execution."""

from dataclasses import dataclass

from verisight.execution.models import QueryResult
from verisight.execution.planning import QueryPlan


@dataclass(frozen=True, slots=True)
class QueryExecution:
    """One successfully executed analytical query with its plan."""

    plan: QueryPlan
    result: QueryResult
