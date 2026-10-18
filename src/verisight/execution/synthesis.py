"""Contracts for evidence-grounded investigation synthesis."""

from dataclasses import dataclass
from typing import Protocol

from verisight.execution.claim_verification import NumericalClaim
from verisight.execution.investigation import InvestigationState


@dataclass(frozen=True, slots=True)
class StructuredSynthesis:
    """An unverified narrative accompanied by explicit numerical claims."""

    conclusion: str
    claims: tuple[NumericalClaim, ...]


class InvestigationSynthesizer(Protocol):
    """Contract for components that synthesize investigation conclusions."""

    def synthesize(self, state: InvestigationState) -> str | StructuredSynthesis:
        """Synthesize a final conclusion from investigation evidence."""
        ...
