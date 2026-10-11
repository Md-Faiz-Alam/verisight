"""Results produced by autonomous analytical investigations."""

from dataclasses import dataclass
from enum import StrEnum

from verisight.analysis.result import DatasetAnalysisResult
from verisight.execution.observations import QueryObservation


class InvestigationStatus(StrEnum):
    """Completion status of an autonomous analytical investigation."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True, slots=True)
class InvestigationResult:
    """Result produced by an autonomous analytical investigation."""

    question: str
    conclusion: str
    analysis: DatasetAnalysisResult
    observations: tuple[QueryObservation, ...] = ()
    status: InvestigationStatus = InvestigationStatus.COMPLETE

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
