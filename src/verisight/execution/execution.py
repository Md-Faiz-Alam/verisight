"""Domain models and request-local capture for analytical query repairs."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Literal

from verisight.execution.models import QueryResult
from verisight.execution.planning import QueryPlan


@dataclass(frozen=True, slots=True)
class QueryRepairAttempt:
    """One repair's plans and outcome, without raw exception text.

    Plans contain analytical SQL and can contain dataset values. This is
    provenance for the caller, not content-free telemetry or a public error.
    A missing replacement means repair did not return a plan.
    """

    failed_plan: QueryPlan
    replacement_plan: QueryPlan | None
    outcome: Literal["succeeded", "failed"]
    error_code: str | None = None


_active_repairs: ContextVar[list[QueryRepairAttempt] | None] = ContextVar(
    "verisight_query_repairs", default=None
)


@contextmanager
def capture_query_repairs() -> Iterator[list[QueryRepairAttempt]]:
    """Capture repairs in this context; nested captures remain isolated."""
    repairs: list[QueryRepairAttempt] = []
    token = _active_repairs.set(repairs)
    try:
        yield repairs
    finally:
        _active_repairs.reset(token)


def record_query_repair(attempt: QueryRepairAttempt) -> None:
    """Record a repair only when the caller requested a local capture."""
    repairs = _active_repairs.get()
    if repairs is not None:
        repairs.append(attempt)


@dataclass(frozen=True, slots=True)
class QueryExecution:
    """One successful analytical query, including any preceding repair."""

    plan: QueryPlan
    result: QueryResult
    repair_history: tuple[QueryRepairAttempt, ...] = field(default=(), kw_only=True)
