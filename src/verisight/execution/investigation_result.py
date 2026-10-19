"""Results produced by autonomous analytical investigations."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal

from verisight.analysis.result import DatasetAnalysisResult
from verisight.error_reporting import to_public_error
from verisight.execution.claim_verification import (
    ClaimOperation,
    ClaimVerificationResult,
    DecimalRoundingPolicy,
    NumericalClaim,
    NumericalClaimVerifier,
)
from verisight.execution.gemini import (
    GeminiGenerationError,
    GeminiTransientError,
    ProviderFailureDiagnostics,
)
from verisight.execution.narrative_audit import (
    NarrativeDigitCoverage,
    NarrativeNumberToken,
    audit_narrative_digit_coverage,
    find_narrative_numbers,
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


InvestigationFailureStage = Literal["investigator", "query_execution"]


@dataclass(frozen=True, slots=True)
class InvestigationFailure:
    """Safe terminal failure after evidence collection, with no raw error text.

    query_execution covers planning, execution, and repair. Provider diagnostics
    retain the generation client's more specific stage when available.
    """

    stage: InvestigationFailureStage
    kind: str
    diagnostics: ProviderFailureDiagnostics | None = None

    @classmethod
    def from_exception(
        cls, stage: InvestigationFailureStage, error: Exception
    ) -> "InvestigationFailure":
        """Classify explicit causes without retaining exceptions or messages."""
        current: BaseException | None = error
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if isinstance(current, GeminiGenerationError):
                return cls(
                    stage=stage,
                    kind=(
                        "provider_unavailable"
                        if isinstance(current, GeminiTransientError)
                        else "provider_error"
                    ),
                    diagnostics=current.diagnostics,
                )
            current = current.__cause__
        return cls(stage=stage, kind=to_public_error(error).code.value)


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
    investigation_failure: InvestigationFailure | None = None
    narrative_verified: bool = field(default=False, init=False)
    verified_claims: tuple["VerifiedNumericalClaim", ...] = field(init=False)
    quantitative_statements: tuple["ClaimLinkedStatement", ...] = field(init=False)
    narrative_numbers: tuple[NarrativeNumberToken, ...] = field(init=False)
    narrative_digit_coverage: NarrativeDigitCoverage = field(init=False)
    unlinked_numbers: tuple[str, ...] = field(init=False)
    narrative_number_audit_scope: str = field(
        default="ascii_numeric_tokens_only", init=False
    )
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

        if (
            self.investigation_failure is not None
            and self.status is not InvestigationStatus.INCOMPLETE
        ):
            raise ValueError(
                "Investigation failure requires an incomplete investigation."
            )

        report = self.verify_claims(self.generated_claims)
        object.__setattr__(self, "verified_claims", report.verified_claims)
        object.__setattr__(
            self, "quantitative_statements", report.quantitative_statements
        )
        tokens = find_narrative_numbers(
            self.conclusion,
            tuple(item.verification.expected for item in self.verified_claims),
        )
        object.__setattr__(self, "narrative_numbers", tokens)
        object.__setattr__(
            self,
            "narrative_digit_coverage",
            audit_narrative_digit_coverage(self.conclusion, tokens),
        )
        object.__setattr__(
            self,
            "unlinked_numbers",
            tuple(token.text for token in tokens if not token.claim_indexes),
        )

    @property
    def observation_count(self) -> int:
        """Return the number of executed analytical observations."""

        return len(self.observations)

    def verify_claims(
        self,
        claims: tuple[NumericalClaim, ...],
        *,
        rounding_policy: DecimalRoundingPolicy | None = None,
    ) -> "InvestigationVerificationReport":
        """Check explicit numerical claims without certifying the narrative."""
        verifier = NumericalClaimVerifier(rounding_policy=rounding_policy)
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
class ClaimLinkedStatement:
    """Application-rendered numerical statement with its exact claim and verdict.

    claim_index is a zero-based position in the owning report's claim sequence.
    Text is computed from numerical verification, never supplied by a model.
    It does not certify SQL semantics or the generated conclusion.
    """

    claim_index: int
    verified_claim: VerifiedNumericalClaim
    text: str = field(init=False)

    def __post_init__(self) -> None:
        """Render expected and evidence values with an explicit verification status."""
        verification = self.verified_claim.verification
        operation = (
            "difference, left minus right"
            if self.verified_claim.claim.operation is ClaimOperation.DIFFERENCE
            else "value"
        )
        actual = (
            "unavailable" if verification.actual is None else str(verification.actual)
        )
        rounding_text = ""
        if verification.rounding_policy is not None:
            policy = verification.rounding_policy
            rounded = (
                "not applied"
                if verification.rounded_actual is None
                else str(verification.rounded_actual)
            )
            rounding_text = (
                f" Rounding policy: {policy.decimal_places} decimal places, "
                f"{policy.rounding_mode}; rounded evidence {rounded}."
            )
        object.__setattr__(
            self,
            "text",
            f"Claim {self.claim_index + 1} ({operation}): "
            f"expected {verification.expected}; evidence {actual}; "
            f"absolute tolerance {verification.absolute_tolerance}; "
            f"status {verification.status.value}." + rounding_text,
        )


@dataclass(frozen=True, slots=True)
class InvestigationVerificationReport:
    """Numerical checks alongside the original investigation and SQL evidence.

    These checks do not validate query semantics, units, filters, causal
    interpretations, or whether all claims in the conclusion were supplied.
    Investigation completion and numerical verification are separate states.
    """

    investigation: InvestigationResult
    verified_claims: tuple[VerifiedNumericalClaim, ...]
    quantitative_statements: tuple[ClaimLinkedStatement, ...] = field(init=False)
    verification_scope: str = field(
        default="referenced_numeric_values_only", init=False
    )

    def __post_init__(self) -> None:
        """Build one traceable statement per submitted numerical claim."""
        object.__setattr__(
            self,
            "quantitative_statements",
            tuple(
                ClaimLinkedStatement(claim_index=index, verified_claim=item)
                for index, item in enumerate(self.verified_claims)
            ),
        )
