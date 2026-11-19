"""Safe, framework-independent boundary for VeriSight operations."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Generic, TypeVar

from verisight.error_reporting import ErrorCode, PublicErrorReport, to_public_error
from verisight.execution.gemini import (
    GeminiGenerationError,
    ProviderFailureDiagnostics,
)
from verisight.logging import get_logger

T = TypeVar("T")

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PublicOperationResult(Generic[T]):
    """A successful value or a safe public error with optional provider metadata.

    Provider metadata is separate from the stable public error code/message.
    It contains no exception, request, response, prompt, or dataset content.
    """

    value: T | None = None
    error: PublicErrorReport | None = None
    provider_diagnostics: ProviderFailureDiagnostics | None = None

    @property
    def succeeded(self) -> bool:
        """Whether the operation completed successfully."""

        return self.error is None


def _provider_diagnostics(error: Exception) -> ProviderFailureDiagnostics | None:
    """Copy only approved fields from explicit causes, never incidental context."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, GeminiGenerationError):
            details = current.diagnostics
            if type(details) is not ProviderFailureDiagnostics:
                return None
            if details.http_status is not None and (
                type(details.http_status) is not int
                or not 100 <= details.http_status <= 599
            ):
                return None
            if (
                type(details.retryable) is not bool
                or type(details.attempts) is not int
                or details.attempts <= 0
                or type(details.stage) is not str
                or details.stage
                not in ("investigator", "text_generation", "structured_synthesis")
                or type(details.call_number) is not int
                or details.call_number <= 0
            ):
                return None
            return ProviderFailureDiagnostics(
                http_status=details.http_status,
                retryable=details.retryable,
                attempts=details.attempts,
                stage=details.stage,
                call_number=details.call_number,
            )
        current = current.__cause__
    return None


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

        return PublicOperationResult(
            error=report, provider_diagnostics=_provider_diagnostics(exc)
        )

    return PublicOperationResult(value=value)
