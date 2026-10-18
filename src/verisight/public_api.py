"""Safe, framework-independent boundary for VeriSight operations."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from verisight.error_reporting import ErrorCode, PublicErrorReport, to_public_error
from verisight.logging import get_logger

T = TypeVar("T")

_logger = get_logger(__name__)


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

    Unexpected failures are logged using only their exception type.
    Raw messages and tracebacks may contain confidential information.
    """

    try:
        value = operation()
    except Exception as exc:
        report = to_public_error(exc)

        if report.code is ErrorCode.INTERNAL_ERROR:
            _logger.error(
                "Unexpected public operation failure: %s",
                type(exc).__name__,
            )

        return PublicOperationResult(error=report)

    return PublicOperationResult(value=value)
