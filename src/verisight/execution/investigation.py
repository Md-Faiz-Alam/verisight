"""Domain models for autonomous analytical investigations."""

from dataclasses import dataclass

from verisight.analysis.result import DatasetAnalysisResult
from verisight.execution.context import QueryContext, QueryContextBuilder
from verisight.execution.observations import QueryObservation


@dataclass(frozen=True, slots=True)
class InvestigationState:
    """Current state of an autonomous analytical investigation."""

    question: str
    analysis: DatasetAnalysisResult
    observations: tuple[QueryObservation, ...] = ()

    @property
    def observation_count(self) -> int:
        """Return the number of executed analytical observations."""

        return len(self.observations)

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
        )
