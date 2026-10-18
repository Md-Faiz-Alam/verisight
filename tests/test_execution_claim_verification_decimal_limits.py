"""Tests for decimal arithmetic limits in numerical claim verification."""

from decimal import Decimal

from verisight.execution.claim_verification import (
    ClaimOperation,
    EvidenceReference,
    NumericalClaim,
    NumericalClaimVerifier,
    VerificationStatus,
)
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation


def _observation(
    values: tuple[Decimal, ...],
) -> QueryObservation:
    """Build a synthetic observation with decimal measurements."""

    return QueryObservation(
        question="What are the synthetic numerical values?",
        sql="SELECT value FROM synthetic_measurements",
        result=QueryResult(
            columns=("value",),
            rows=tuple((value,) for value in values),
        ),
    )


def _reference(row_index: int) -> EvidenceReference:
    """Reference one value in the first observation."""

    return EvidenceReference(
        observation_index=0,
        row_index=row_index,
        column="value",
    )


def test_extreme_decimal_difference_is_unverifiable() -> None:
    """Overflow during subtraction must not produce a false claim verdict."""

    observations = (
        _observation(
            (
                Decimal("9E+999999"),
                Decimal("-9E+999999"),
            )
        ),
    )

    claim = NumericalClaim(
        operation=ClaimOperation.DIFFERENCE,
        expected=Decimal(0),
        left=_reference(0),
        right=_reference(1),
    )

    result = NumericalClaimVerifier().verify(claim, observations)

    assert result.status is VerificationStatus.UNVERIFIABLE
    assert result.actual is None
    assert result.reason == ("Numerical evidence cannot be combined safely.")


def test_extreme_decimal_comparison_is_unverifiable() -> None:
    """Overflow while comparing finite values must not imply contradiction."""

    observations = (_observation((Decimal("9E+999999"),)),)

    claim = NumericalClaim(
        operation=ClaimOperation.VALUE,
        expected=Decimal("-9E+999999"),
        left=_reference(0),
    )

    result = NumericalClaimVerifier().verify(claim, observations)

    assert result.status is VerificationStatus.UNVERIFIABLE
    assert result.actual is None
    assert result.reason == ("Numerical evidence cannot be compared safely.")
