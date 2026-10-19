"""Results produced by autonomous analytical investigations."""

from dataclasses import dataclass, field
from enum import StrEnum

from verisight.analysis.result import DatasetAnalysisResult
from verisight.execution.claim_verification import (
    ClaimVerificationResult,
    NumericalClaim,
    NumericalClaimVerifier,
)
from verisight.execution.gemini import (
    GeminiGenerationError,
    GeminiTransientError,
    ProviderFailureDiagnostics,
)
from verisight.execution.observations import QueryObservation


class InvestigationStatus(StrEnum):
    """Completion status of an autonomous analytical investigation."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


class SynthesisFailureKind(StrEnum):
    """Distinguish provider failures from other expected synthesis failures."""

    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_ERROR = "provider_error"
    SYNTHESIS_ERROR = "synthesis_error"


@dataclass(frozen=True, slots=True)
class SynthesisFailure:
    """Safe synthesis failure metadata without exception text or objects."""

    kind: SynthesisFailureKind
    diagnostics: ProviderFailureDiagnostics | None = None

    @classmethod
    def from_exception(cls, error: Exception) -> "SynthesisFailure":
        """Follow explicit causes to preserve provider classification safely."""
        current: BaseException | None = error
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, GeminiGenerationError):
                return cls(
                    kind=(
                        SynthesisFailureKind.PROVIDER_UNAVAILABLE
                        if isinstance(current, GeminiTransientError)
                        else SynthesisFailureKind.PROVIDER_ERROR
                    ),
                    diagnostics=current.diagnostics,
                )
            current = current.__cause__
        return cls(kind=SynthesisFailureKind.SYNTHESIS_ERROR)


@dataclass(frozen=True, slots=True)
class InvestigationResult:
    """Result produced by an autonomous analytical investigation."""

    question: str
    conclusion: str
    analysis: DatasetAnalysisResult
    observations: tuple[QueryObservation, ...] = ()
    status: InvestigationStatus = InvestigationStatus.COMPLETE
    generated_claims: tuple[NumericalClaim, ...] = ()
    synthesis_failure: SynthesisFailure | None = None
    narrative_verified: bool = field(default=False, init=False)
    verified_claims: tuple["VerifiedNumericalClaim", ...] = field(init=False)
    verification_scope: str = field(
        default="referenced_numeric_values_only", init=False
    )

    def __post_init__(self) -> None:
        """Validate investigation result invariants."""

        if not self.question.strip():
            raise ValueError("Investigation question must not be empty.")

        if not self.conclusion.strip():
            raise ValueError("Investigation conclusion must not be empty.")

        if (
            self.synthesis_failure is not None
            and self.status is not InvestigationStatus.INCOMPLETE
        ):
            raise ValueError("Synthesis failure requires an incomplete investigation.")

        object.__setattr__(
            self,
            "verified_claims",
            self.verify_claims(self.generated_claims).verified_claims,
        )

    @property
    def observation_count(self) -> int:
        """Return the number of executed analytical observations."""

        return len(self.observations)

    def verify_claims(
        self, claims: tuple[NumericalClaim, ...]
    ) -> "InvestigationVerificationReport":
        """Check explicit numerical claims without certifying the narrative."""
        verifier = NumericalClaimVerifier()
        return InvestigationVerificationReport(
            investigation=self,
            verified_claims=tuple(
                VerifiedNumericalClaim(
                    claim=claim,
                    verification=verifier.verify(claim, self.observations),
                )
                for claim in claims
            ),
        )


@dataclass(frozen=True, slots=True)
class VerifiedNumericalClaim:
    """Keep a numerical claim, its evidence references, and its verdict together."""

    claim: NumericalClaim
    verification: ClaimVerificationResult


@dataclass(frozen=True, slots=True)
class InvestigationVerificationReport:
    """Numerical checks alongside the original investigation and SQL evidence.

    These checks do not validate query semantics, units, filters, causal
    interpretations, or whether all claims in the conclusion were supplied.
    Investigation completion and numerical verification are separate states.
    """

    investigation: InvestigationResult
    verified_claims: tuple[VerifiedNumericalClaim, ...]
    verification_scope: str = field(
        default="referenced_numeric_values_only", init=False
    )
