"""Safe, framework-independent boundary for VeriSight operations."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from verisight.error_reporting import PublicErrorReport, to_public_error

T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class PublicOperationResult(Generic[T]):
    """A successful value or a safe public error."""

    value: T | None = None
    error: PublicErrorReport | None = None

    @property
    def succeeded(self) -> bool:
        """Whether the operation completed successfully."""

        return self.error is None


def run_public_operation(
    operation: Callable[[], T],
) -> PublicOperationResult[T]:
    """Execute an operation and convert failures to safe reports.

    Existing internal exception handling remains unchanged.
    """

    try:
        value = operation()
    except Exception as exc:
        report = to_public_error(exc)

        return PublicOperationResult(error=report)

    return PublicOperationResult(value=value)
