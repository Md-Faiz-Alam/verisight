"""Tests for decimal arithmetic limits in numerical claim verification."""

from decimal import Decimal, Inexact, Overflow, localcontext

import pytest

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


@pytest.mark.parametrize("precision", [2, 28])
def test_rounded_difference_is_unverifiable(precision: int) -> None:
    observations = (_observation((Decimal(10**30), Decimal(-1))),)
    claim = NumericalClaim(
        operation=ClaimOperation.DIFFERENCE,
        expected=10**30,
        left=_reference(0),
        right=_reference(1),
    )

    with localcontext() as context:
        context.prec = precision
        context.traps[Inexact] = False
        context.clear_flags()
        result = NumericalClaimVerifier().verify(claim, observations)
        assert context.traps[Inexact] is False
        assert context.flags[Inexact] is False

    assert result.status is VerificationStatus.UNVERIFIABLE
    assert result.actual is None
    assert result.reason == "Numerical evidence cannot be combined safely."


def test_rounded_tolerance_comparison_is_unverifiable() -> None:
    observations = (_observation((Decimal("1.04"),)),)
    claim = NumericalClaim(
        operation=ClaimOperation.VALUE,
        expected=0,
        left=_reference(0),
        absolute_tolerance=1,
    )

    with localcontext() as context:
        context.prec = 2
        result = NumericalClaimVerifier().verify(claim, observations)

    assert result.status is VerificationStatus.UNVERIFIABLE
    assert result.reason == "Numerical evidence cannot be compared safely."


def test_overflow_remains_unverifiable_when_callers_disable_traps() -> None:
    observations = (_observation((Decimal("9E+999999"), Decimal("-9E+999999"))),)
    claim = NumericalClaim(
        operation=ClaimOperation.DIFFERENCE,
        expected=0,
        left=_reference(0),
        right=_reference(1),
    )

    with localcontext() as context:
        context.traps[Overflow] = False
        context.traps[Inexact] = False
        result = NumericalClaimVerifier().verify(claim, observations)

    assert result.status is VerificationStatus.UNVERIFIABLE
    assert result.actual is None


def test_sufficient_precision_verifies_large_difference_exactly() -> None:
    observations = (_observation((Decimal(10**30), Decimal(-1))),)
    claim = NumericalClaim(
        operation=ClaimOperation.DIFFERENCE,
        expected=10**30 + 1,
        left=_reference(0),
        right=_reference(1),
    )

    with localcontext() as context:
        context.prec = 40
        result = NumericalClaimVerifier().verify(claim, observations)

    assert result.status is VerificationStatus.SUPPORTED
    assert result.actual == Decimal(10**30 + 1)
