"""Caller-described displays of supported numerical VALUE evidence.

Descriptions are application input, never inferred from generated prose or SQL.
They are not sent to a provider and do not certify analytical semantics.
Advisory population and counting-grain reviews on the selected evidence are
respected: a display is refused when either review requires inspection.
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
from verisight.execution.observations import QueryObservation


class MetricReviewRequiredError(ValueError):
    """The selected claim's evidence has an advisory review requiring inspection.

    This is not proof that the SQL is wrong. It means a caller-worded display
    would present the value with more authority than its evidence supports.
    """


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


@dataclass(frozen=True, slots=True)
class AdvisoryReviewSummary:
    """Zero-based observation indexes whose advisory reviews require inspection.

    An empty summary means no built-in heuristic raised a warning. It does not
    mean the population or counting grain was verified: unassessed and
    unsupported query shapes also produce no warning.
    """

    review_required: bool
    population_review_required_observations: tuple[int, ...]
    grain_review_required_observations: tuple[int, ...]
    scope: str = field(default="advisory_heuristics_only", init=False)
    task_semantics_verified: bool = field(default=False, init=False)


def _population_review_required(observation: QueryObservation) -> bool:
    review = observation.population_review
    return review is not None and review.status == "review_required"


def _grain_review_required(observation: QueryObservation) -> bool:
    review = observation.grain_review
    return review is not None and review.status == "review_required"


def summarize_advisory_reviews(
    investigation: InvestigationResult,
) -> AdvisoryReviewSummary:
    """Collect advisory warnings without changing the investigation or its verdicts."""
    if not isinstance(investigation, InvestigationResult):
        raise TypeError("Investigation must be an InvestigationResult.")
    population = tuple(
        index
        for index, observation in enumerate(investigation.observations)
        if _population_review_required(observation)
    )
    grain = tuple(
        index
        for index, observation in enumerate(investigation.observations)
        if _grain_review_required(observation)
    )
    return AdvisoryReviewSummary(
        review_required=bool(population or grain),
        population_review_required_observations=population,
        grain_review_required_observations=grain,
    )


def render_metric(
    investigation: InvestigationResult,
    description: MetricDescription,
    *,
    claim_index: int = 0,
) -> MetricDisplay:
    """Render one supported VALUE cell without using the generated conclusion.

    Require a complete workflow and recheck the selected claim against its
    evidence. Refuse the display when the referenced observation has an
    advisory population or counting-grain review requiring inspection.
    Display the actual SQL cell even if a nonzero claim tolerance permits a
    different expected value. Do not round, rescale, deduplicate or infer units.
    Other claims and the narrative are outside this check. The original result,
    acceptance and provider-call counts are unchanged.
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
    # A supported verdict guarantees the referenced observation exists.
    observation = investigation.observations[claim.left.observation_index]
    if _population_review_required(observation) or _grain_review_required(observation):
        raise MetricReviewRequiredError(
            "Metric display requires inspection of an advisory review "
            "on the referenced evidence."
        )
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
