"""A shared, cooperative time budget for investigation orchestration.

SDK requests and SQL execution use the remaining budget for cancellation.
Synchronous setup, registration, callbacks, and cleanup cannot be forcibly
interrupted; the deadline is checked at their boundaries.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic

from verisight.execution.exceptions import InvestigationError

_deadline: ContextVar[float | None] = ContextVar("investigation_deadline", default=None)


class InvestigationDeadlineExceeded(InvestigationError):
    """Raised when the shared investigation time budget is exhausted."""


@contextmanager
def investigation_deadline(seconds: float) -> Iterator[None]:
    """Scope a finite budget without extending an enclosing deadline."""
    if not 0 < seconds < float("inf"):
        raise ValueError("Investigation timeout must be finite and positive.")
    expires = monotonic() + seconds
    enclosing = _deadline.get()
    token = _deadline.set(expires if enclosing is None else min(enclosing, expires))
    try:
        yield
    finally:
        _deadline.reset(token)


def remaining_seconds(limit: float) -> float:
    """Clamp an operation timeout, raising before starting overdue work."""
    expires = _deadline.get()
    if expires is None:
        return limit
    remaining = expires - monotonic()
    if remaining <= 0:
        raise InvestigationDeadlineExceeded("Investigation time budget was exhausted.")
    return min(limit, remaining)


def check_deadline() -> None:
    """Reject results or additional work after the deadline."""
    remaining_seconds(float("inf"))
