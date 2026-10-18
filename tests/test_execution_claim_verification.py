"""Tests for deterministic evidence-linked numerical claim verification."""

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


def _observation(
    columns: tuple[str, ...],
    rows: tuple[tuple[object, ...], ...],
) -> QueryObservation:
    return QueryObservation(
        question="What does the synthetic dataset show?",
        sql="SELECT value FROM synthetic_data",
        result=QueryResult(
            columns=columns,
            rows=rows,  # type: ignore[arg-type]
        ),
    )


def _reference(
    column: str = "value",
    *,
    observation_index: int = 0,
    row_index: int = 0,
) -> EvidenceReference:
    return EvidenceReference(
        observation_index=observation_index,
        row_index=row_index,
        column=column,
    )


def _value_claim(
    expected: int | float | Decimal,
    *,
    reference: EvidenceReference | None = None,
    tolerance: int | float | Decimal = 0,
) -> NumericalClaim:
    return NumericalClaim(
        operation=ClaimOperation.VALUE,
        expected=expected,
        left=reference if reference is not None else _reference(),
        absolute_tolerance=tolerance,
    )


def test_verifies_supported_exact_integer() -> None:
    observations = (_observation(("value",), ((60,),)),)

    result = NumericalClaimVerifier().verify(
        _value_claim(60),
        observations,
    )

    assert result.status is VerificationStatus.SUPPORTED
    assert result.actual == Decimal(60)
    assert result.expected == Decimal(60)
    assert result.absolute_tolerance == Decimal(0)


def test_detects_contradicted_integer() -> None:
    observations = (_observation(("value",), ((60,),)),)

    result = NumericalClaimVerifier().verify(
        _value_claim(70),
        observations,
    )

    assert result.status is VerificationStatus.CONTRADICTED
    assert result.actual == Decimal(60)


def test_preserves_large_integer_precision() -> None:
    value = 9_007_199_254_740_993
    observations = (_observation(("value",), ((value,),)),)

    supported = NumericalClaimVerifier().verify(
        _value_claim(value),
        observations,
    )
    contradicted = NumericalClaimVerifier().verify(
        _value_claim(value - 1),
        observations,
    )

    assert supported.status is VerificationStatus.SUPPORTED
    assert contradicted.status is VerificationStatus.CONTRADICTED
    assert supported.actual == Decimal(value)


def test_preserves_decimal_values() -> None:
    observations = (_observation(("value",), ((Decimal("10.25"),),)),)

    result = NumericalClaimVerifier().verify(
        _value_claim(Decimal("10.25")),
        observations,
    )

    assert result.status is VerificationStatus.SUPPORTED
    assert result.actual == Decimal("10.25")


def test_supports_explicit_absolute_tolerance() -> None:
    observations = (_observation(("value",), ((0.30000000000000004,),)),)

    result = NumericalClaimVerifier().verify(
        _value_claim(0.3, tolerance=Decimal("0.000000000000001")),
        observations,
    )

    assert result.status is VerificationStatus.SUPPORTED
    assert result.absolute_tolerance == Decimal("0.000000000000001")


def test_without_tolerance_detects_float_difference() -> None:
    observations = (_observation(("value",), ((0.30000000000000004,),)),)

    result = NumericalClaimVerifier().verify(
        _value_claim(0.3),
        observations,
    )

    assert result.status is VerificationStatus.CONTRADICTED


def test_supports_difference_between_rows() -> None:
    observations = (
        _observation(
            ("value",),
            ((Decimal("100.50"),), (Decimal("80.25"),)),
        ),
    )

    claim = NumericalClaim(
        operation=ClaimOperation.DIFFERENCE,
        expected=Decimal("20.25"),
        left=_reference(row_index=0),
        right=_reference(row_index=1),
    )

    result = NumericalClaimVerifier().verify(claim, observations)

    assert result.status is VerificationStatus.SUPPORTED
    assert result.actual == Decimal("20.25")


def test_detects_wrong_difference() -> None:
    observations = (_observation(("value",), ((100,), (80,))),)

    claim = NumericalClaim(
        operation=ClaimOperation.DIFFERENCE,
        expected=30,
        left=_reference(row_index=0),
        right=_reference(row_index=1),
    )

    result = NumericalClaimVerifier().verify(claim, observations)

    assert result.status is VerificationStatus.CONTRADICTED
    assert result.actual == Decimal(20)


def test_can_reference_different_observations() -> None:
    observations = (
        _observation(("total",), ((100,),)),
        _observation(("total",), ((65,),)),
    )

    claim = NumericalClaim(
        operation=ClaimOperation.DIFFERENCE,
        expected=35,
        left=_reference("total", observation_index=0),
        right=_reference("total", observation_index=1),
    )

    result = NumericalClaimVerifier().verify(claim, observations)

    assert result.status is VerificationStatus.SUPPORTED


@pytest.mark.parametrize(
    "reference",
    [
        EvidenceReference(-1, 0, "value"),
        EvidenceReference(5, 0, "value"),
        EvidenceReference(0, -1, "value"),
        EvidenceReference(0, 10, "value"),
        EvidenceReference(0, 0, "missing"),
    ],
)
def test_missing_reference_is_unverifiable(
    reference: EvidenceReference,
) -> None:
    observations = (_observation(("value",), ((10,),)),)

    result = NumericalClaimVerifier().verify(
        _value_claim(10, reference=reference),
        observations,
    )

    assert result.status is VerificationStatus.UNVERIFIABLE
    assert result.actual is None


def test_empty_observations_are_unverifiable() -> None:
    result = NumericalClaimVerifier().verify(
        _value_claim(10),
        (),
    )

    assert result.status is VerificationStatus.UNVERIFIABLE


def test_duplicate_column_names_are_unverifiable() -> None:
    observations = (_observation(("value", "value"), ((10, 10),)),)

    result = NumericalClaimVerifier().verify(
        _value_claim(10),
        observations,
    )

    assert result.status is VerificationStatus.UNVERIFIABLE


def test_malformed_short_row_is_unverifiable() -> None:
    observations = (_observation(("other", "value"), ((1,),)),)

    result = NumericalClaimVerifier().verify(
        _value_claim(10),
        observations,
    )

    assert result.status is VerificationStatus.UNVERIFIABLE


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        "10",
        float("nan"),
        float("inf"),
        Decimal("NaN"),
        Decimal("Infinity"),
    ],
)
def test_non_numeric_or_nonfinite_evidence_is_unverifiable(
    value: object,
) -> None:
    observations = (_observation(("value",), ((value,),)),)

    result = NumericalClaimVerifier().verify(
        _value_claim(10),
        observations,
    )

    assert result.status is VerificationStatus.UNVERIFIABLE


def test_missing_right_operand_is_unverifiable() -> None:
    observations = (_observation(("value",), ((100,),)),)

    claim = NumericalClaim(
        operation=ClaimOperation.DIFFERENCE,
        expected=20,
        left=_reference(),
        right=_reference(row_index=1),
    )

    result = NumericalClaimVerifier().verify(claim, observations)

    assert result.status is VerificationStatus.UNVERIFIABLE
    assert result.actual is None


@pytest.mark.parametrize("index", [True, 0.5, "0"])
def test_rejects_invalid_observation_index(index: object) -> None:
    with pytest.raises(TypeError, match="Observation index"):
        EvidenceReference(index, 0, "value")  # type: ignore[arg-type]


@pytest.mark.parametrize("index", [True, 0.5, "0"])
def test_rejects_invalid_row_index(index: object) -> None:
    with pytest.raises(TypeError, match="Row index"):
        EvidenceReference(0, index, "value")  # type: ignore[arg-type]


def test_rejects_non_string_column() -> None:
    with pytest.raises(TypeError, match="Evidence column"):
        EvidenceReference(0, 0, 123)  # type: ignore[arg-type]


def test_rejects_empty_column() -> None:
    with pytest.raises(ValueError, match="Evidence column"):
        EvidenceReference(0, 0, "")


def test_rejects_invalid_claim_operation() -> None:
    with pytest.raises(TypeError, match="Claim operation"):
        NumericalClaim(
            operation="sum",  # type: ignore[arg-type]
            expected=10,
            left=_reference(),
        )


def test_value_claim_rejects_second_reference() -> None:
    with pytest.raises(ValueError, match="one evidence reference"):
        NumericalClaim(
            operation=ClaimOperation.VALUE,
            expected=10,
            left=_reference(),
            right=_reference(),
        )


def test_difference_claim_requires_second_reference() -> None:
    with pytest.raises(ValueError, match="right-hand evidence"):
        NumericalClaim(
            operation=ClaimOperation.DIFFERENCE,
            expected=10,
            left=_reference(),
        )


def test_rejects_invalid_left_reference() -> None:
    with pytest.raises(TypeError, match="Left evidence"):
        NumericalClaim(
            operation=ClaimOperation.VALUE,
            expected=10,
            left="invalid",  # type: ignore[arg-type]
        )


@pytest.mark.parametrize("value", [True, "10", None, float("inf"), Decimal("NaN")])
def test_rejects_invalid_expected_value(value: object) -> None:
    with pytest.raises((TypeError, ValueError), match="Expected value"):
        NumericalClaim(
            operation=ClaimOperation.VALUE,
            expected=value,  # type: ignore[arg-type]
            left=_reference(),
        )


@pytest.mark.parametrize(
    "tolerance",
    [-1, True, "0.1", float("nan"), Decimal("Infinity")],
)
def test_rejects_invalid_absolute_tolerance(tolerance: object) -> None:
    with pytest.raises(
        (TypeError, ValueError),
        match="Absolute tolerance",
    ):
        NumericalClaim(
            operation=ClaimOperation.VALUE,
            expected=10,
            left=_reference(),
            absolute_tolerance=tolerance,  # type: ignore[arg-type]
        )


def test_immutable_claim_and_reference() -> None:
    reference = _reference()
    claim = _value_claim(10)

    with pytest.raises(AttributeError):
        reference.column = "other"  # type: ignore[misc]

    with pytest.raises(AttributeError):
        claim.expected = 20  # type: ignore[misc]


def test_verification_result_has_safe_reason() -> None:
    observations = (_observation(("value",), ((10,),)),)

    result = NumericalClaimVerifier().verify(
        _value_claim(20),
        observations,
    )

    assert result.reason == ("The numerical evidence contradicts the claimed value.")
    assert "synthetic_data" not in result.reason
