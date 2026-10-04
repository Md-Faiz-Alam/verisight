"""Contracts for evidence-grounded investigation synthesis."""

from typing import Protocol

from verisight.execution.investigation import InvestigationState


class InvestigationSynthesizer(Protocol):
    """Contract for components that synthesize investigation conclusions."""

    def synthesize(self, state: InvestigationState) -> str:
        """Synthesize a final conclusion from investigation evidence."""
        ...
