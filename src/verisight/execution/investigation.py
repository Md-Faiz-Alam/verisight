"""Domain models for autonomous analytical investigations."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from verisight.analysis.result import DatasetAnalysisResult
from verisight.execution.context import (
    PopulationFilter,
    QueryContext,
    QueryContextBuilder,
)
from verisight.execution.execution import QueryRepairAttempt
from verisight.execution.observations import QueryObservation

if TYPE_CHECKING:
    from verisight.execution.investigation_result import ClaimOutputContract


@dataclass(frozen=True, slots=True)
class FailedQueryAttempt:
    """A failed analytical request, not usable as query evidence."""

    question: str
    error_type: str
    message: str
    repair_history: tuple[QueryRepairAttempt, ...] = field(default=(), kw_only=True)


@dataclass(frozen=True, slots=True)
class InvestigationState:
    """Current state of an autonomous analytical investigation.

    remaining_steps is a runtime budget snapshot, or None when unknown.
    Successful and failed attempt transitions consume it without mutation.
    The orchestrator independently enforces the analytical-attempt limit.
    """

    question: str
    analysis: DatasetAnalysisResult
    population: tuple[PopulationFilter, ...] = field(default=(), kw_only=True)
    remaining_steps: int | None = field(default=None, kw_only=True)
    claim_output_contract: "ClaimOutputContract | None" = field(
        default=None, kw_only=True
    )
    observations: tuple[QueryObservation, ...] = ()
    failed_attempts: tuple[FailedQueryAttempt, ...] = ()

    def __post_init__(self) -> None:
        if self.remaining_steps is not None and (
            type(self.remaining_steps) is not int or self.remaining_steps < 0
        ):
            raise ValueError(
                "Remaining analytical steps must be a nonnegative integer."
            )

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

        return QueryContextBuilder().build(
            self.analysis.analysis.schema, population=self.population
        )

    def add_observation(
        self,
        observation: QueryObservation,
    ) -> "InvestigationState":
        """Return a new state containing an additional observation."""

        return InvestigationState(
            question=self.question,
            analysis=self.analysis,
            population=self.population,
            claim_output_contract=self.claim_output_contract,
            remaining_steps=(
                None
                if self.remaining_steps is None
                else max(0, self.remaining_steps - 1)
            ),
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
            population=self.population,
            claim_output_contract=self.claim_output_contract,
            remaining_steps=(
                None
                if self.remaining_steps is None
                else max(0, self.remaining_steps - 1)
            ),
            observations=self.observations,
            failed_attempts=(*self.failed_attempts, attempt),
        )
