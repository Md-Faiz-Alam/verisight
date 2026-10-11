"""Domain models for autonomous analytical investigations."""

from dataclasses import dataclass

from verisight.analysis.result import DatasetAnalysisResult
from verisight.execution.context import QueryContext, QueryContextBuilder
from verisight.execution.observations import QueryObservation


@dataclass(frozen=True, slots=True)
class FailedQueryAttempt:
    """A failed analytical request, not usable as query evidence."""

    question: str
    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class InvestigationState:
    """Current state of an autonomous analytical investigation."""

    question: str
    analysis: DatasetAnalysisResult
    observations: tuple[QueryObservation, ...] = ()
    failed_attempts: tuple[FailedQueryAttempt, ...] = ()

    @property
    def observation_count(self) -> int:
        """Return the number of successful analytical observations."""

        return len(self.observations)

    @property
    def failed_attempt_count(self) -> int:
        """Return the number of failed analytical attempts."""

        return len(self.failed_attempts)

    @property
    def context(self) -> QueryContext:
        """Return deterministic query context for the investigated dataset."""

        return QueryContextBuilder().build(self.analysis.analysis.schema)

    def add_observation(
        self,
        observation: QueryObservation,
    ) -> "InvestigationState":
        """Return a new state containing an additional observation."""

        return InvestigationState(
            question=self.question,
            analysis=self.analysis,
            observations=(*self.observations, observation),
            failed_attempts=self.failed_attempts,
        )

    def add_failed_attempt(
        self,
        attempt: FailedQueryAttempt,
    ) -> "InvestigationState":
        """Return a new state containing an unsuccessful analytical attempt."""

        return InvestigationState(
            question=self.question,
            analysis=self.analysis,
            observations=self.observations,
            failed_attempts=(*self.failed_attempts, attempt),
        )
