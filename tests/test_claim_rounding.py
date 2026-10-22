"""Explicit rounding never replaces exact evidence or model-validation rules."""

import json
from dataclasses import FrozenInstanceError, replace
from decimal import ROUND_UP, Decimal, Inexact, Rounded, localcontext
from unittest.mock import Mock

import duckdb
import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.execution.claim_verification import (
    ClaimOperation,
    DecimalRoundingPolicy,
    EvidenceReference,
    NumericalClaim,
    NumericalClaimVerifier,
    VerificationStatus,
)
from verisight.execution.exceptions import InvestigationError
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_result import InvestigationResult
from verisight.execution.models import QueryResult, QueryScalar
from verisight.execution.observations import QueryObservation
from verisight.execution.structured_synthesis import StructuredInvestigationSynthesizer
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile
from verisight.serialization import to_jsonable

REFERENCE = EvidenceReference(0, 0, "metric")


def _observations(value: QueryScalar) -> tuple[QueryObservation, ...]:
    return (
        QueryObservation(
            question="What is the metric?",
            sql="SELECT metric FROM measurements",
            result=QueryResult(columns=("metric",), rows=((value,),)),
        ),
    )


@pytest.mark.parametrize(
    "actual,expected,places,status,rounded",
    [
        ("31.4126315", "31.41", 2, "supported_rounded", "31.41"),
        ("31.4126315", "31.4", 1, "supported_rounded", "31.4"),
        ("31.4126315", "31", 0, "supported_rounded", "31"),
        ("31.4126315", "31.4", 2, "contradicted", "31.41"),
        ("31.4126315", "41.4", 1, "contradicted", "31.4"),
        ("31.4126315", "31.411", 2, "contradicted", "31.41"),
        ("1.245", "1.25", 2, "supported_rounded", "1.25"),
        ("1.255", "1.26", 2, "supported_rounded", "1.26"),
        ("-1.245", "-1.25", 2, "supported_rounded", "-1.25"),
        ("-1.255", "-1.26", 2, "supported_rounded", "-1.26"),
        ("1.244999", "1.24", 2, "supported_rounded", "1.24"),
        ("1.245001", "1.24", 2, "contradicted", "1.25"),
        ("0.004", "0", 2, "supported_rounded", "0.00"),
        ("-0.004", "0", 2, "supported_rounded", "-0.00"),
        ("25.125", "25.13", 2, "supported_rounded", "25.13"),
        ("0.25125", "25.12", 2, "contradicted", "0.25"),
        ("0.30000000000000004", "0.3", 2, "supported_rounded", "0.30"),
        (
            "1.2345678901234",
            "1.234567890123",
            12,
            "supported_rounded",
            "1.234567890123",
        ),
        (
            "12345678901234567890.12345",
            "12345678901234567890.123",
            3,
            "supported_rounded",
            "12345678901234567890.123",
        ),
    ],
    ids=[
        "two-places",
        "one-place",
        "integer",
        "no-inferred-precision",
        "wrong-value",
        "expected-not-rounded",
        "even-tie",
        "odd-tie",
        "negative-even-tie",
        "negative-odd-tie",
        "below-boundary",
        "above-boundary",
        "zero",
        "negative-zero",
        "percentage-points",
        "no-percentage-conversion",
        "explicit-float-presentation",
        "twelve-places",
        "large-value",
    ],
)
def test_rounding_has_fixed_precision_and_retains_original_evidence(
    actual: str, expected: str, places: int, status: str, rounded: str
) -> None:
    policy = DecimalRoundingPolicy(places)
    claim = NumericalClaim(ClaimOperation.VALUE, Decimal(expected), REFERENCE)
    result = NumericalClaimVerifier(rounding_policy=policy).verify(
        claim, _observations(Decimal(actual))
    )
    assert result.status.value == status
    assert result.actual == Decimal(actual)
    assert result.expected == Decimal(expected)
    assert result.rounded_actual == Decimal(rounded)
    assert result.rounding_policy == policy
    assert result.absolute_tolerance == 0


@pytest.mark.parametrize("places", [0, 12])
def test_exact_match_keeps_supported_status(places: int) -> None:
    policy = DecimalRoundingPolicy(places)
    claim = NumericalClaim(ClaimOperation.VALUE, Decimal("31.4126315"), REFERENCE)
    result = NumericalClaimVerifier(rounding_policy=policy).verify(
        claim, _observations(Decimal("31.4126315"))
    )
    assert result.status is VerificationStatus.SUPPORTED
    assert result.rounding_policy == policy
    assert result.rounded_actual is None


@pytest.mark.parametrize("value", [None, True, "31.412", Decimal("NaN")])
def test_rounding_does_not_make_unsuitable_evidence_usable(value: QueryScalar) -> None:
    policy = DecimalRoundingPolicy(2)
    result = NumericalClaimVerifier(rounding_policy=policy).verify(
        NumericalClaim(ClaimOperation.VALUE, Decimal("31.41"), REFERENCE),
        _observations(value),
    )
    assert result.status is VerificationStatus.UNVERIFIABLE
    assert result.actual is None
    assert result.rounded_actual is None
    assert result.rounding_policy == policy


def test_difference_rounds_only_after_exact_subtraction() -> None:
    observations = (
        QueryObservation(
            question="What changed?",
            sql="SELECT left_value, right_value FROM measurements",
            result=QueryResult(
                columns=("left", "right"),
                rows=((Decimal("10.125"), Decimal("1.004")),),
            ),
        ),
    )
    claim = NumericalClaim(
        ClaimOperation.DIFFERENCE,
        Decimal("9.12"),
        EvidenceReference(0, 0, "left"),
        EvidenceReference(0, 0, "right"),
    )
    result = NumericalClaimVerifier(rounding_policy=DecimalRoundingPolicy(2)).verify(
        claim, observations
    )
    assert result.status is VerificationStatus.SUPPORTED_ROUNDED
    assert result.actual == Decimal("9.121")
    assert result.rounded_actual == Decimal("9.12")


def test_rounding_keeps_caller_context_and_fails_closed_at_precision_limit() -> None:
    claim = NumericalClaim(ClaimOperation.VALUE, Decimal("1.25"), REFERENCE)
    verifier = NumericalClaimVerifier(rounding_policy=DecimalRoundingPolicy(2))
    with localcontext() as context:
        context.rounding = ROUND_UP
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        context.clear_flags()
        result = verifier.verify(claim, _observations(Decimal("1.245")))
        assert result.status is VerificationStatus.SUPPORTED_ROUNDED
        assert result.rounded_actual == Decimal("1.25")
        assert context.rounding == ROUND_UP
        assert context.traps[Inexact] is True
        assert context.traps[Rounded] is True
        assert context.flags[Inexact] is False
        assert context.flags[Rounded] is False
    with localcontext() as context:
        context.prec = 2
        result = NumericalClaimVerifier(
            rounding_policy=DecimalRoundingPolicy(12)
        ).verify(
            NumericalClaim(ClaimOperation.VALUE, 1, REFERENCE),
            _observations(Decimal("0.999")),
        )
    assert result.status is VerificationStatus.UNVERIFIABLE
    assert result.actual == Decimal("0.999")
    assert result.rounded_actual is None
    assert result.reason == "Numerical evidence cannot be rounded safely."


@pytest.mark.parametrize("places", [-1, 13])
def test_policy_rejects_out_of_range_places(places: int) -> None:
    with pytest.raises(ValueError, match="between 0 and 12"):
        DecimalRoundingPolicy(places)


@pytest.mark.parametrize("places", [True, 2.0, "2", None])
def test_policy_rejects_noninteger_places(places: object) -> None:
    with pytest.raises(TypeError, match="must be an integer"):
        DecimalRoundingPolicy(places)  # type: ignore[arg-type]


def test_policy_cannot_be_combined_with_tolerance_or_changed_after_creation() -> None:
    policy = DecimalRoundingPolicy(2)
    with pytest.raises(FrozenInstanceError):
        policy.decimal_places = 0  # type: ignore[misc]
    with pytest.raises(TypeError, match="Rounding policy must"):
        NumericalClaimVerifier(rounding_policy="2")  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="cannot be combined"):
        NumericalClaimVerifier(rounding_policy=policy).verify(
            NumericalClaim(ClaimOperation.VALUE, 1, REFERENCE, absolute_tolerance=1),
            _observations(Decimal("1.234")),
        )


def test_investigation_reverification_is_explicit_serializable_and_visible() -> None:
    analysis = AnalysisResultBuilder().build(
        DatasetAnalysis(
            schema=DatasetSchema(tables=()),
            profile=DatasetProfile(tables=()),
            issues=(),
        )
    )
    claim = NumericalClaim(ClaimOperation.VALUE, Decimal("31.41"), REFERENCE)
    result = InvestigationResult(
        question="What is the metric?",
        conclusion="The metric is 31.41.",
        analysis=analysis,
        observations=_observations(Decimal("31.4126315")),
        generated_claims=(claim,),
    )
    assert (
        result.verified_claims[0].verification.status is VerificationStatus.CONTRADICTED
    )
    report = result.verify_claims(
        result.generated_claims, rounding_policy=DecimalRoundingPolicy(2)
    )
    verified = report.verified_claims[0].verification
    assert verified.status is VerificationStatus.SUPPORTED_ROUNDED
    statement = report.quantitative_statements[0].text
    assert "evidence 31.4126315" in statement
    assert "rounded evidence 31.41" in statement
    assert "2 decimal places, ROUND_HALF_UP" in statement
    assert "status supported_rounded" in statement
    payload = json.loads(json.dumps(to_jsonable(report)))
    saved = payload["verified_claims"][0]["verification"]
    assert saved["actual"] == "31.4126315"
    assert saved["rounded_actual"] == "31.41"
    assert saved["rounding_policy"] == {
        "decimal_places": 2,
        "rounding_mode": "ROUND_HALF_UP",
    }
    assert (
        result.verified_claims[0].verification.status is VerificationStatus.CONTRADICTED
    )
    assert result.narrative_verified is False
    exact = result.verify_claims(
        (replace(claim, expected=Decimal("31.4126315")),),
        rounding_policy=DecimalRoundingPolicy(2),
    )
    assert "rounded evidence not applied" in exact.quantitative_statements[0].text


def test_model_cannot_supply_rounding_policy() -> None:
    analysis = AnalysisResultBuilder().build(
        DatasetAnalysis(
            schema=DatasetSchema(tables=()),
            profile=DatasetProfile(tables=()),
            issues=(),
        )
    )
    client = Mock()
    client.generate.return_value = json.dumps(
        {
            "conclusion": "Rounded measurement",
            "claims": [
                {
                    "operation": "value",
                    "expected": "31",
                    "left": {
                        "observation_index": 0,
                        "row_index": 0,
                        "column": "metric",
                    },
                    "right": None,
                    "rounding_policy": {"decimal_places": 0},
                }
            ],
        }
    )
    state = InvestigationState(
        question="Measure",
        analysis=analysis,
        observations=_observations(Decimal("31.412")),
    )
    with pytest.raises(InvestigationError):
        StructuredInvestigationSynthesizer(client).synthesize(state)
    assert client.generate.call_count == 2


@pytest.mark.parametrize(
    "value,places,expected",
    [
        ("12.5", 0, "13"),
        ("-12.5", 0, "-13"),
        ("2.5", 0, "3"),
        ("-2.5", 0, "-3"),
        ("0.875", 2, "0.88"),
        ("-0.875", 2, "-0.88"),
        ("1.245", 2, "1.25"),
        ("-1.245", 2, "-1.25"),
    ],
)
def test_rounding_ties_match_duckdb_decimal_round(
    value: str, places: int, expected: str
) -> None:
    with duckdb.connect(":memory:") as connection:
        row = connection.execute(
            "SELECT ROUND(CAST(? AS DECIMAL(10, 3)), ?)", [value, places]
        ).fetchone()
    assert row is not None
    assert row[0] == Decimal(expected)
    verifier = NumericalClaimVerifier(rounding_policy=DecimalRoundingPolicy(places))
    observations = _observations(Decimal(value))
    result = verifier.verify(
        NumericalClaim(ClaimOperation.VALUE, Decimal(expected), REFERENCE), observations
    )
    assert result.status is VerificationStatus.SUPPORTED_ROUNDED
    assert result.actual == Decimal(value)
    assert result.rounded_actual == row[0]
    opposite = verifier.verify(
        NumericalClaim(ClaimOperation.VALUE, -Decimal(expected), REFERENCE),
        observations,
    )
    assert opposite.status is VerificationStatus.CONTRADICTED
    strict = NumericalClaimVerifier().verify(
        NumericalClaim(ClaimOperation.VALUE, Decimal(expected), REFERENCE), observations
    )
    assert strict.status is VerificationStatus.CONTRADICTED
