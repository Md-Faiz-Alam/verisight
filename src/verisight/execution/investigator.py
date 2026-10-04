"""Contracts for autonomous analytical investigation."""

from typing import Protocol

from verisight.execution.decisions import InvestigationDecision
from verisight.execution.investigation import InvestigationState


class Investigator(Protocol):
    """Contract for components that decide the next investigation action."""

    def decide(
        self,
        state: InvestigationState,
    ) -> InvestigationDecision:
        """Decide the next action for an analytical investigation."""
        ...
