"""Regression tests for observation formatting and caller-described displays."""

import json
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.cli import main
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


def _metric_cli_source(tmp_path: Path) -> Path:
    source = tmp_path / "bank.csv"
    source.write_text(
        "default,y\nno,yes\nno,no\nyes,no\nunknown,yes\n", encoding="utf-8"
    )
    return source


def _metric_cli_args(source: Path) -> list[str]:
    return [
        "investigate",
        str(source),
        "--question",
        "What percentage of records with known default status subscribed?",
        "--metric-description",
        "Subscription percentage among eligible records",
        "records",
        "percent",
        "--max-steps",
        "1",
    ]


def test_cli_metric_preview_is_offline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = _metric_cli_args(_metric_cli_source(tmp_path)) + ["--preview"]
    with patch(
        "verisight.execution.gemini.GeminiTextGenerationClient.generate",
        side_effect=AssertionError("No provider calls permitted"),
    ) as generate:
        assert main(args) == 0
    generate.assert_not_called()
    report = json.loads(capsys.readouterr().out)
    assert report["kind"] == "investigation_preview"
    assert report["request"]["metric_description"] == {
        "label": "Subscription percentage among eligible records",
        "counting_unit": "records",
        "unit": "percent",
    }
    assert report["request"]["metric_claim_index"] == 0
    assert "metric_display" not in report


@pytest.mark.parametrize(
    "options",
    [
        ["--metric-description", "Label", "records"],
        ["--metric-description", "", "records", "percent"],
        ["--metric-description", "Label", "", "percent"],
        ["--metric-description", "Label", "records", ""],
        ["--metric-description", "line\nbreak", "records", "percent"],
        ["--metric-description", "x" * 257, "records", "percent"],
        ["--metric-claim-index", "0"],
        ["--metric-claim-index", "-1"],
        ["--metric-claim-index", "invalid"],
    ],
)
def test_cli_rejects_invalid_metric_options_before_loading(
    options: list[str], tmp_path: Path
) -> None:
    with (
        patch(
            "verisight.cli.VeriSight.analyze",
            side_effect=AssertionError("No data loading permitted"),
        ) as analyze,
        pytest.raises(SystemExit) as caught,
    ):
        main(
            [
                "investigate",
                str(tmp_path / "absent.csv"),
                "--question",
                "Measure",
                "--preview",
                *options,
            ]
        )
    assert caught.value.code == 2
    analyze.assert_not_called()


def test_cli_exports_caller_display_without_changing_generation_or_narrative(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VERISIGHT_GEMINI_API_KEY", "offline-key")
    source = _metric_cli_source(tmp_path)
    before = source.read_bytes()
    output = tmp_path / "metric-report.json"
    conclusion = "Among eligible records, 33.333333 percent of individuals subscribed."
    sql = (
        "SELECT ROUND(100.0*SUM(CASE WHEN y='yes' THEN 1 ELSE 0 END)"
        "/COUNT(*),6) AS \"VALUE\" FROM bank WHERE \"default\" IN ('yes','no')"
    )
    responses = [
        json.dumps(
            {"action": "investigate", "reasoning": "Measure", "question": "Measure"}
        ),
        sql,
        json.dumps(
            {
                "conclusion": conclusion,
                "claims": [
                    {
                        "operation": "value",
                        "expected": "33.333333",
                        "left": {
                            "observation_index": 0,
                            "row_index": 0,
                            "column": "VALUE",
                        },
                        "right": None,
                    }
                ],
            }
        ),
    ]
    args = _metric_cli_args(source) + [
        "--allow-llm-data-disclosure",
        "--require-claim",
        "value",
        "--output",
        str(output),
    ]
    with patch(
        "verisight.execution.gemini.GeminiTextGenerationClient.generate",
        side_effect=responses,
    ) as generate:
        assert main(args) == 0
    assert generate.call_count == 3
    for call in generate.call_args_list:
        assert "Subscription percentage among eligible records" not in call.args[0]
        assert "metric_description" not in call.args[0]
    report = json.loads(capsys.readouterr().out)
    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert source.read_bytes() == before
    assert report["metric_display_status"] == "rendered"
    display = report["metric_display"]
    assert display["value"] == "33.333333"
    assert display["text"] == (
        "Subscription percentage among eligible records: 33.333333 percent. "
        "Counting unit (caller supplied): records."
    )
    assert display["description_source"] == "caller"
    assert display["task_semantics_verified"] is False
    assert report["unverified_model_interpretation"] == conclusion
    assert report["investigation"]["conclusion"] == conclusion
    assert report["investigation"]["observations"][0]["sql"] == sql
    assert report["claim_output_assessment"]["accepted"] is True


@pytest.mark.parametrize(
    "mode", ["contradicted", "incomplete", "difference", "missing", "out-of-range"]
)
def test_cli_retains_evidence_when_requested_metric_display_is_unavailable(
    mode: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VERISIGHT_GEMINI_API_KEY", "offline-key")
    result = _metric_result()
    args = _metric_cli_args(_metric_cli_source(tmp_path)) + [
        "--allow-llm-data-disclosure"
    ]
    if mode == "contradicted":
        claim = replace(result.generated_claims[0], expected=99)
        result = replace(result, generated_claims=(claim,))
    elif mode == "incomplete":
        result = replace(result, status=InvestigationStatus.INCOMPLETE)
    elif mode == "difference":
        claim = replace(
            result.generated_claims[0],
            operation=ClaimOperation.DIFFERENCE,
            right=EvidenceReference(0, 0, "VALUE"),
            expected=0,
        )
        result = replace(result, generated_claims=(claim,))
    elif mode == "missing":
        result = replace(result, generated_claims=())
    else:
        args.extend(("--metric-claim-index", "1"))
    output = tmp_path / "unavailable.json"
    args.extend(("--output", str(output)))
    with (
        patch("verisight.cli.VeriSight.investigate", return_value=result),
        patch(
            "verisight.execution.gemini.GeminiTextGenerationClient.generate",
            side_effect=AssertionError("No provider calls permitted"),
        ) as generate,
    ):
        assert main(args) == 1
    generate.assert_not_called()
    report = json.loads(capsys.readouterr().out)
    assert report["kind"] == "investigation"
    assert report["metric_display_status"] == "unavailable"
    assert report["metric_display"] is None
    assert "supported VALUE claim" in report["metric_display_unavailable_reason"]
    assert report["investigation"] == to_jsonable(result)
    assert report["workflow_status"] == result.status.value
    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_cli_metric_claim_selection_is_explicit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERISIGHT_GEMINI_API_KEY", "offline-key")
    result = _metric_result()
    bad = replace(result.generated_claims[0], expected=99)
    result = replace(result, generated_claims=(bad, result.generated_claims[0]))
    args = _metric_cli_args(_metric_cli_source(tmp_path)) + [
        "--allow-llm-data-disclosure",
        "--metric-claim-index",
        "1",
    ]
    with patch("verisight.cli.VeriSight.investigate", return_value=result):
        assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["metric_display"]["claim_index"] == 1
    assert report["metric_display"]["value"] == "12.877788"
    assert report["investigation"] == to_jsonable(result)
