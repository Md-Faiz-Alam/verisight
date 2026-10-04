"""Domain models for autonomous investigation decisions."""

from dataclasses import dataclass
from enum import StrEnum


class InvestigationAction(StrEnum):
    """Actions available to an autonomous analytical investigator."""

    INVESTIGATE = "investigate"
    FINISH = "finish"


@dataclass(frozen=True, slots=True)
class InvestigationDecision:
    """One decision made during an analytical investigation."""

    action: InvestigationAction
    reasoning: str
    question: str | None = None

    def __post_init__(self) -> None:
        """Validate the decision invariants."""

        if not self.reasoning.strip():
            raise ValueError("Investigation reasoning must not be empty.")

        if self.action is InvestigationAction.INVESTIGATE and (
            self.question is None or not self.question.strip()
        ):
            raise ValueError(
                "An investigate decision must include an analytical question."
            )

        if self.action is InvestigationAction.FINISH and self.question is not None:
            raise ValueError(
                "A finish decision must not include an analytical question."
            )
