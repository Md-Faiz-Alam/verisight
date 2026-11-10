"""A difference rounded by the SQL itself is evidence; any other rounding is not."""

from decimal import Decimal

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

HIGH = 11.518049155145922
LOW = 9.926478494623645


def _verify(
    expected: str,
    row: tuple[object, ...],
    columns: tuple[str, ...] = ("a", "b", "gap"),
) -> VerificationStatus:
    observation = QueryObservation(
        "q",
        "SELECT 1",
        QueryResult(columns, (row,)),  # type: ignore[arg-type]
    )
    claim = NumericalClaim(
        ClaimOperation.DIFFERENCE,
        Decimal(expected),
        EvidenceReference(0, 0, "a"),
        EvidenceReference(0, 0, "b"),
    )
    return NumericalClaimVerifier().verify(claim, (observation,)).status


def test_a_difference_rounded_by_the_sql_is_supported() -> None:
    assert _verify("1.591571", (HIGH, LOW, 1.591571)) is VerificationStatus.SUPPORTED


@pytest.mark.parametrize(
    ("expected", "row", "columns"),
    [
        ("1.591571", (HIGH, LOW), ("a", "b")),
        ("1.591571", (HIGH, LOW, "1.591571"), ("a", "b", "gap")),
        ("1.591572", (HIGH, LOW, 1.591572), ("a", "b", "gap")),
        ("1.59", (HIGH, LOW, 1.591571), ("a", "b", "gap")),
        ("1.5", (1.5, 0.0000001), ("a", "b")),
        ("1E+3", (1500.0, 500.0000001, 1000.0), ("a", "b", "gap")),
        (
            "1.0000000000000",
            (Decimal("2.00000000000001"), Decimal(1), Decimal(1)),
            ("a", "b", "gap"),
        ),
    ],
    ids=[
        "no-rounded-cell",
        "rounded-cell-is-text",
        "not-a-rounding-of-the-difference",
        "cell-holds-another-rounding",
        "only-a-cited-cell-matches",
        "rounded-to-thousands",
        "too-many-places",
    ],
)
def test_other_roundings_are_still_rejected(
    expected: str, row: tuple[object, ...], columns: tuple[str, ...]
) -> None:
    assert _verify(expected, row, columns) is VerificationStatus.CONTRADICTED


def test_parts_in_different_rows_cannot_use_a_rounded_cell() -> None:
    observation = QueryObservation(
        "q",
        "SELECT 1",
        QueryResult(("a", "b", "gap"), ((HIGH, 0.0, 1.591571), (0.0, LOW, 1.591571))),
    )
    claim = NumericalClaim(
        ClaimOperation.DIFFERENCE,
        Decimal("1.591571"),
        EvidenceReference(0, 0, "a"),
        EvidenceReference(0, 1, "b"),
    )

    result = NumericalClaimVerifier().verify(claim, (observation,))

    assert result.status is VerificationStatus.CONTRADICTED


def test_a_value_too_large_to_round_is_rejected() -> None:
    large = Decimal("12345678901234567890123.5")
    expected = "12345678901234567890123.500001"

    status = _verify(expected, (large, Decimal(0), Decimal(expected)))

    assert status is VerificationStatus.CONTRADICTED
