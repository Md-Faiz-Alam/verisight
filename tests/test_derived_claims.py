"""Ratio, percent and percent-change claims, computed from two SQL cells."""

from decimal import Decimal

import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.execution.claim_verification import (
    ClaimOperation,
    EvidenceReference,
    NumericalClaim,
    NumericalClaimVerifier,
    VerificationStatus,
    contract_kind,
)
from verisight.execution.investigation_result import (
    ClaimOutputContract,
    InvestigationResult,
)
from verisight.execution.models import QueryResult, QueryScalar
from verisight.execution.observations import QueryObservation
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile

SHIPPED = EvidenceReference(0, 0, "shipped")
TOTAL = EvidenceReference(0, 0, "total")
BEFORE = EvidenceReference(0, 0, "before")


def _observations(*row: QueryScalar) -> tuple[QueryObservation, ...]:
    columns = ("shipped", "total", "before")[: len(row)]
    return (QueryObservation("q", "SELECT 1", QueryResult(columns, (row,))),)


def _status(
    operation: str,
    expected: str,
    left: EvidenceReference,
    right: EvidenceReference,
    observations: tuple[QueryObservation, ...],
) -> VerificationStatus:
    claim = NumericalClaim(ClaimOperation(operation), Decimal(expected), left, right)
    return NumericalClaimVerifier().verify(claim, observations).status


@pytest.mark.parametrize(
    ("operation", "expected", "left", "right", "status"),
    [
        ("ratio", "0.333", SHIPPED, TOTAL, "supported"),
        ("ratio", "0.3333333", SHIPPED, TOTAL, "supported"),
        ("percent", "33.3", SHIPPED, TOTAL, "supported"),
        ("percent", "33.33", SHIPPED, TOTAL, "supported"),
        ("percent_change", "25.0", TOTAL, BEFORE, "supported"),
        ("percent_change", "25", TOTAL, BEFORE, "supported"),
        ("percent_change", "-20", BEFORE, TOTAL, "supported"),
        # A rounding the claim does not show, or too few digits, is refused.
        ("percent", "33.4", SHIPPED, TOTAL, "contradicted"),
        ("percent", "33", SHIPPED, TOTAL, "contradicted"),
        ("ratio", "0", SHIPPED, TOTAL, "contradicted"),
        ("ratio", "0.33", SHIPPED, TOTAL, "contradicted"),
        # The reference value is the right-hand cell.
        ("percent_change", "-20.0", TOTAL, BEFORE, "contradicted"),
    ],
)
def test_derived_claims_match_their_cells_at_the_places_shown(
    operation: str,
    expected: str,
    left: EvidenceReference,
    right: EvidenceReference,
    status: str,
) -> None:
    observations = _observations(5, 15, 12)

    assert _status(operation, expected, left, right, observations) == status


def test_float_cells_are_divided_from_their_shortest_decimal() -> None:
    observations = _observations(0.1, 0.3)

    assert _status("percent", "33.3", SHIPPED, TOTAL, observations) == "supported"


def test_a_zero_reference_cannot_be_divided() -> None:
    claim = NumericalClaim(ClaimOperation.RATIO, Decimal(1), SHIPPED, TOTAL)

    result = NumericalClaimVerifier().verify(claim, _observations(1, 0))

    assert result.status is VerificationStatus.UNVERIFIABLE
    assert result.actual is None
    assert "zero" in result.reason


def test_a_quotient_too_long_to_round_is_not_a_display_of_it() -> None:
    claim = NumericalClaim(
        ClaimOperation.RATIO, Decimal("1.000000000000"), SHIPPED, TOTAL
    )

    result = NumericalClaimVerifier().verify(claim, _observations(10**40, 3))

    assert result.status is VerificationStatus.CONTRADICTED


def test_a_derived_claim_keeps_the_exact_quotient_and_a_tolerance() -> None:
    claim = NumericalClaim(
        ClaimOperation.PERCENT,
        Decimal("33"),
        SHIPPED,
        TOTAL,
        absolute_tolerance=Decimal("0.5"),
    )

    result = NumericalClaimVerifier().verify(claim, _observations(5, 15))

    assert result.status is VerificationStatus.SUPPORTED
    assert str(result.actual).startswith("33.33333333")
    assert "percent" in result.reason


@pytest.mark.parametrize(
    "operation",
    [ClaimOperation.RATIO, ClaimOperation.PERCENT, ClaimOperation.PERCENT_CHANGE],
)
def test_a_derived_claim_needs_two_cells(operation: ClaimOperation) -> None:
    with pytest.raises(ValueError, match=f"{operation.value} claim requires"):
        NumericalClaim(operation, Decimal(1), SHIPPED)


@pytest.mark.parametrize(
    ("operation", "kind"),
    [
        (ClaimOperation.VALUE, ClaimOperation.VALUE),
        (ClaimOperation.RATIO, ClaimOperation.VALUE),
        (ClaimOperation.PERCENT, ClaimOperation.VALUE),
        (ClaimOperation.PERCENT_CHANGE, ClaimOperation.VALUE),
        (ClaimOperation.DIFFERENCE, ClaimOperation.DIFFERENCE),
    ],
)
def test_a_derived_claim_fills_a_slot_for_one_number(
    operation: ClaimOperation, kind: ClaimOperation
) -> None:
    assert contract_kind(operation) is kind


def _result(claim: NumericalClaim, question: str) -> InvestigationResult:
    analysis = AnalysisResultBuilder().build(
        DatasetAnalysis(
            schema=DatasetSchema(tables=()),
            profile=DatasetProfile(tables=()),
            issues=(),
        )
    )
    return InvestigationResult(
        question=question,
        conclusion="33.3% of orders were shipped.",
        analysis=analysis,
        observations=_observations(5, 15),
        generated_claims=(claim,),
    )


def test_a_percent_claim_answers_a_question_for_one_number() -> None:
    claim = NumericalClaim(ClaimOperation.PERCENT, Decimal("33.3"), SHIPPED, TOTAL)
    result = _result(claim, "What share of orders were shipped?")

    value = result.assess_output(ClaimOutputContract((ClaimOperation.VALUE,)))
    difference = result.assess_output(ClaimOutputContract((ClaimOperation.DIFFERENCE,)))

    assert value.accepted is True
    assert "claim_operations_mismatch" in difference.violations
    assert "percent, 100 times left divided by right" in (
        result.quantitative_statements[0].text
    )
