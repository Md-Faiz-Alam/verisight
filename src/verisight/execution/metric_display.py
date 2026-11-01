"""Caller-described displays of supported numerical VALUE evidence.

Descriptions are application input, never inferred from generated prose or SQL.
They are not sent to a provider and do not certify analytical semantics.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from verisight.execution.claim_verification import (
    ClaimOperation,
    ClaimVerificationResult,
    EvidenceReference,
    NumericalClaimVerifier,
    VerificationStatus,
)
from verisight.execution.investigation_result import (
    InvestigationResult,
    InvestigationStatus,
)


@dataclass(frozen=True, slots=True)
class MetricDescription:
    """Caller-supplied display wording, not a verified metric definition.

    Each field is bounded, printable, nonblank plain text. The caller supplies
    the population in label and the intended counting unit and displayed units.
    Nothing here establishes that SQL implements those descriptions.
    """

    label: str
    counting_unit: str
    unit: str

    def __post_init__(self) -> None:
        for value in (self.label, self.counting_unit, self.unit):
            if not isinstance(value, str):
                raise TypeError("Metric descriptions must be strings.")
            if not value.strip() or not value.isprintable() or len(value) > 256:
                raise ValueError(
                    "Metric descriptions must be nonblank printable text "
                    "of at most 256 characters."
                )


@dataclass(frozen=True, slots=True)
class MetricDisplay:
    """A selected evidence value with explicit caller-supplied descriptions.

    Use render_metric to produce this display. It does not establish that the
    caller's population, counting unit or units match the executed SQL.
    Render text as plain text, not trusted markup.
    """

    description: MetricDescription
    claim_index: int
    reference: EvidenceReference
    value: Decimal
    verification: ClaimVerificationResult
    text: str
    description_source: str = field(default="caller", init=False)
    verification_scope: str = field(
        default="referenced_numeric_values_only", init=False
    )
    task_semantics_verified: bool = field(default=False, init=False)


def render_metric(
    investigation: InvestigationResult,
    description: MetricDescription,
    *,
    claim_index: int = 0,
) -> MetricDisplay:
    """Render one supported VALUE cell without using the generated conclusion.

    Require a complete workflow and recheck the selected claim against its
    evidence. Display the actual SQL cell even if a nonzero claim tolerance
    permits a different expected value. Do not round, rescale, deduplicate or
    infer units. Other claims and the narrative are outside this check.
    The original result, acceptance and provider-call counts are unchanged.
    """
    if not isinstance(investigation, InvestigationResult):
        raise TypeError("Investigation must be an InvestigationResult.")
    if not isinstance(description, MetricDescription):
        raise TypeError("Description must be a MetricDescription.")
    if type(claim_index) is not int:
        raise TypeError("Claim index must be an integer.")
    if investigation.status is not InvestigationStatus.COMPLETE:
        raise ValueError("Metric display requires a complete investigation.")
    if not 0 <= claim_index < len(investigation.generated_claims):
        raise IndexError("Metric claim index is out of range.")
    claim = investigation.generated_claims[claim_index]
    if claim.operation is not ClaimOperation.VALUE:
        raise ValueError("Metric display requires a VALUE claim.")
    verification = NumericalClaimVerifier().verify(claim, investigation.observations)
    if verification.status is not VerificationStatus.SUPPORTED:
        raise ValueError("Metric display requires supported numerical evidence.")
    value = verification.actual
    assert value is not None
    return MetricDisplay(
        description=description,
        claim_index=claim_index,
        reference=claim.left,
        value=value,
        verification=verification,
        text=(
            f"{description.label}: {value} {description.unit}. "
            f"Counting unit (caller supplied): {description.counting_unit}."
        ),
    )
