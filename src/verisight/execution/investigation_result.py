"""Results produced by autonomous analytical investigations."""

from dataclasses import dataclass

from verisight.analysis.result import DatasetAnalysisResult
from verisight.execution.observations import QueryObservation


@dataclass(frozen=True, slots=True)
class InvestigationResult:
    """Complete result produced by an autonomous investigation."""

    question: str
    conclusion: str
    analysis: DatasetAnalysisResult
    observations: tuple[QueryObservation, ...] = ()

    def __post_init__(self) -> None:
        """Validate investigation result invariants."""

        if not self.question.strip():
            raise ValueError("Investigation question must not be empty.")

        if not self.conclusion.strip():
            raise ValueError("Investigation conclusion must not be empty.")

    @property
    def observation_count(self) -> int:
        """Return the number of executed analytical observations."""

        return len(self.observations)
