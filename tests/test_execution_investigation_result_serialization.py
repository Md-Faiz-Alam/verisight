"""Regression tests for observation formatting and caller-described displays."""

from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal

import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.execution.claim_verification import (
    ClaimOperation,
    EvidenceReference,
    NumericalClaim,
)
from verisight.execution.investigation_formatting import (
    InvestigationStateFormatter,
)
from verisight.execution.investigation_result import (
    InvestigationResult,
    InvestigationStatus,
)
from verisight.execution.metric_display import MetricDescription, render_metric
from verisight.execution.models import QueryResult, QueryScalar
from verisight.execution.observations import QueryObservation
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile
from verisight.serialization import to_jsonable


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            date(2026, 1, 15),
            '["2026-01-15"]',
        ),
        (
            datetime(2026, 1, 15, 10, 30),
            '["2026-01-15T10:30:00"]',
        ),
        (
            Decimal("1234.567890"),
            '["1234.567890"]',
        ),
        (
            Decimal("0.00000001"),
            '["1E-8"]',
        ),
        (
            None,
            "[null]",
        ),
        (
            float("nan"),
            "[null]",
        ),
    ],
)
def test_formats_sql_scalar_as_json(
    value: QueryScalar,
    expected: str,
) -> None:
    """Supported SQL scalar values must be JSON-safe."""

    formatter = InvestigationStateFormatter()

    result = QueryResult(
        columns=("value",),
        rows=((value,),),
    )

    formatted = formatter._format_result(result)

    assert expected in formatted


def test_formats_mixed_temporal_and_decimal_values() -> None:
    """A result row may contain multiple non-JSON-native SQL values."""

    formatter = InvestigationStateFormatter()

    result = QueryResult(
        columns=("month", "total", "created_at"),
        rows=(
            (
                date(2026, 1, 1),
                Decimal("1500.25"),
                datetime(2026, 1, 31, 23, 59),
            ),
        ),
    )

    formatted = formatter._format_result(result)

    assert '["2026-01-01","1500.25","2026-01-31T23:59:00"]' in formatted
    assert "Row count: 1" in formatted


def test_serialization_preserves_row_omission_limits() -> None:
    """Serialization must not change the existing row-budget contract."""

    formatter = InvestigationStateFormatter(max_result_rows=1)

    result = QueryResult(
        columns=("month", "amount"),
        rows=(
            (date(2026, 1, 1), Decimal("100.50")),
            (date(2026, 2, 1), Decimal("200.75")),
        ),
    )

    formatted = formatter._format_result(result)

    assert '["2026-01-01","100.50"]' in formatted
    assert "200.75" not in formatted
    assert "Rows omitted: 1 of 2" in formatted


def _metric_result() -> InvestigationResult:
    analysis = AnalysisResultBuilder().build(
        DatasetAnalysis(
            schema=DatasetSchema(tables=()),
            profile=DatasetProfile(tables=()),
            issues=(),
        )
    )
    observation = QueryObservation(
        question="Subscription percentage among eligible records.",
        sql=(
            "SELECT ROUND(100.0 * SUM(CASE WHEN \"y\" = 'yes' "
            'THEN 1 ELSE 0 END) / COUNT(*), 6) AS "VALUE" '
            "FROM \"bank_additional_full\" WHERE \"default\" IN ('yes', 'no')"
        ),
        result=QueryResult(columns=("VALUE",), rows=((Decimal("12.877788"),),)),
    )
    return InvestigationResult(
        question="Count each eligible record once.",
        conclusion=(
            "Among the records with a known credit-default status, "
            "12.877788 percent of individuals subscribed to a term deposit."
        ),
        analysis=analysis,
        observations=(observation,),
        generated_claims=(
            NumericalClaim(
                operation=ClaimOperation.VALUE,
                expected=Decimal("12.877788"),
                left=EvidenceReference(0, 0, "VALUE"),
            ),
        ),
    )


def _description() -> MetricDescription:
    return MetricDescription(
        label="Subscription percentage among records with known default status",
        counting_unit="records",
        unit="percent",
    )


def test_metric_display_preserves_caller_wording_and_original_narrative() -> None:
    result = _metric_result()
    original = to_jsonable(result)
    display = render_metric(result, _description())

    assert display.text == (
        "Subscription percentage among records with known default status: "
        "12.877788 percent. Counting unit (caller supplied): records."
    )
    assert "individuals" not in display.text
    assert "individuals" in result.conclusion
    assert display.reference == result.generated_claims[0].left
    assert display.value == Decimal("12.877788")
    assert display.verification.actual == display.value
    assert display.description_source == "caller"
    assert display.verification_scope == "referenced_numeric_values_only"
    assert display.task_semantics_verified is False
    assert result.narrative_verified is False
    assert to_jsonable(result) == original
    assert to_jsonable(display) == {
        "description": {
            "label": _description().label,
            "counting_unit": "records",
            "unit": "percent",
        },
        "claim_index": 0,
        "reference": {"observation_index": 0, "row_index": 0, "column": "VALUE"},
        "value": "12.877788",
        "verification": to_jsonable(display.verification),
        "text": display.text,
        "description_source": "caller",
        "verification_scope": "referenced_numeric_values_only",
        "task_semantics_verified": False,
    }


@pytest.mark.parametrize(
    "description",
    [
        MetricDescription("Accepted batch mass", "batches", "kg"),
        MetricDescription("Approved permit fees", "permit records", "EUR"),
        MetricDescription("Réservations", "booking records", "percent"),
    ],
)
def test_metric_display_does_not_infer_or_certify_caller_semantics(
    description: MetricDescription,
) -> None:
    display = render_metric(_metric_result(), description)
    assert display.description is description
    assert display.text == (
        f"{description.label}: 12.877788 {description.unit}. "
        f"Counting unit (caller supplied): {description.counting_unit}."
    )
    assert display.task_semantics_verified is False


@pytest.mark.parametrize("field", ["label", "counting_unit", "unit"])
@pytest.mark.parametrize("invalid", ["", "   ", "line\nbreak", "x\x00y", "x" * 257])
def test_metric_description_rejects_unusable_text(field: str, invalid: str) -> None:
    fields = {"label": "Metric", "counting_unit": "records", "unit": "percent"}
    fields[field] = invalid
    with pytest.raises(ValueError, match="nonblank printable text"):
        MetricDescription(**fields)


@pytest.mark.parametrize("field", ["label", "counting_unit", "unit"])
def test_metric_description_rejects_nontext(field: str) -> None:
    with pytest.raises(TypeError, match="must be strings"):
        replace(_description(), **{field: 1})  # type: ignore[arg-type]


@pytest.mark.parametrize("index", [-1, 1])
def test_metric_display_rejects_missing_claim(index: int) -> None:
    with pytest.raises(IndexError, match="out of range"):
        render_metric(_metric_result(), _description(), claim_index=index)


@pytest.mark.parametrize("index", [True, 0.0, "0", None])
def test_metric_display_rejects_noninteger_index(index: object) -> None:
    with pytest.raises(TypeError, match="must be an integer"):
        render_metric(_metric_result(), _description(), claim_index=index)  # type: ignore[arg-type]


def test_metric_display_rejects_wrong_input_types() -> None:
    with pytest.raises(TypeError, match="must be an InvestigationResult"):
        render_metric(None, _description())  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="must be a MetricDescription"):
        render_metric(_metric_result(), None)  # type: ignore[arg-type]


def test_metric_display_rejects_incomplete_investigation() -> None:
    result = replace(_metric_result(), status=InvestigationStatus.INCOMPLETE)
    with pytest.raises(ValueError, match="complete investigation"):
        render_metric(result, _description())


def test_metric_display_rejects_difference_claims() -> None:
    result = _metric_result()
    claim = replace(
        result.generated_claims[0],
        operation=ClaimOperation.DIFFERENCE,
        right=EvidenceReference(0, 0, "VALUE"),
        expected=0,
    )
    with pytest.raises(ValueError, match="VALUE claim"):
        render_metric(replace(result, generated_claims=(claim,)), _description())


@pytest.mark.parametrize("value", [None, "12.877788", True, 99])
def test_metric_display_rejects_unavailable_or_contradicted_evidence(
    value: QueryScalar,
) -> None:
    result = _metric_result()
    observation = replace(
        result.observations[0],
        result=QueryResult(columns=("VALUE",), rows=((value,),)),
    )
    with pytest.raises(ValueError, match="supported numerical evidence"):
        render_metric(replace(result, observations=(observation,)), _description())


def test_metric_display_rechecks_changed_evidence_and_displays_actual_value() -> None:
    result = _metric_result()
    tolerant_claim = replace(
        result.generated_claims[0], expected=13, absolute_tolerance=1
    )
    result = replace(result, generated_claims=(tolerant_claim,))
    display = render_metric(result, _description())
    assert display.value == Decimal("12.877788")
    assert display.verification.expected == 13
    assert "12.877788 percent" in display.text
    assert result.generated_claims[0].expected == 13


def test_metric_display_selects_evidence_without_rounding_or_unit_conversion() -> None:
    result = _metric_result()
    value = Decimal("0.128777883464760209873")
    observation = replace(
        result.observations[0],
        result=QueryResult(columns=("VALUE",), rows=((value,),)),
    )
    selected = replace(result.generated_claims[0], expected=value)
    unrelated = replace(selected, expected=99)
    result = replace(
        result, observations=(observation,), generated_claims=(unrelated, selected)
    )
    display = render_metric(result, _description(), claim_index=1)
    assert display.claim_index == 1
    assert display.value == value
    assert f"{value} percent" in display.text
    assert display.task_semantics_verified is False
