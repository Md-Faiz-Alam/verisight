"""Metric displays must respect advisory reviews on their referenced evidence."""

import json
from dataclasses import replace
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
from verisight.execution.context import (
    CountingGrainReview,
    PopulationReview,
    PopulationWarning,
)
from verisight.execution.investigation_result import InvestigationResult
from verisight.execution.metric_display import (
    MetricDescription,
    MetricReviewRequiredError,
    render_metric,
    summarize_advisory_reviews,
)
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile
from verisight.serialization import to_jsonable

_FLAGGED_POPULATION = PopulationReview(
    "review_required",
    (PopulationWarning("generation", "record type", "production"),),
)
_FLAGGED_GRAIN = CountingGrainReview(
    "review_required", ("row_counts_for_identity_request",)
)


def _observation(
    value: int,
    *,
    population: PopulationReview | None = None,
    grain: CountingGrainReview | None = None,
) -> QueryObservation:
    return QueryObservation(
        question="Measure total production output.",
        sql='SELECT SUM(kwh) AS total FROM "generation"',
        result=QueryResult(columns=("total",), rows=((value,),)),
        population_review=population,
        grain_review=grain,
    )


def _result(
    *observations: QueryObservation, claim_index: int = 0
) -> InvestigationResult:
    analysis = AnalysisResultBuilder().build(
        DatasetAnalysis(
            schema=DatasetSchema(tables=()),
            profile=DatasetProfile(tables=()),
            issues=(),
        )
    )
    value = observations[claim_index].result.rows[0][0]
    assert isinstance(value, int)
    return InvestigationResult(
        question="What is total production output in kWh?",
        conclusion=f"Total production output is {value} kWh.",
        analysis=analysis,
        observations=observations,
        generated_claims=(
            NumericalClaim(
                operation=ClaimOperation.VALUE,
                expected=Decimal(value),
                left=EvidenceReference(claim_index, 0, "total"),
            ),
        ),
    )


def _description() -> MetricDescription:
    return MetricDescription(
        label="Production output", counting_unit="reading", unit="kWh"
    )


@pytest.mark.parametrize(
    ("population", "grain"),
    [(_FLAGGED_POPULATION, None), (None, _FLAGGED_GRAIN)],
    ids=["population", "grain"],
)
def test_display_is_refused_when_referenced_evidence_requires_review(
    population: PopulationReview | None, grain: CountingGrainReview | None
) -> None:
    result = _result(_observation(10030, population=population, grain=grain))
    original = to_jsonable(result)

    with pytest.raises(MetricReviewRequiredError, match="advisory review"):
        render_metric(result, _description())

    assert to_jsonable(result) == original
    assert result.verified_claims[0].verification.status.value == "supported"


@pytest.mark.parametrize(
    ("population", "grain"),
    [
        (None, None),
        (PopulationReview("no_warning_detected"), CountingGrainReview("not_assessed")),
        (PopulationReview("not_assessed"), CountingGrainReview("no_warning_detected")),
    ],
    ids=["absent", "no-warning", "not-assessed"],
)
def test_display_renders_without_a_review_warning(
    population: PopulationReview | None, grain: CountingGrainReview | None
) -> None:
    result = _result(_observation(30, population=population, grain=grain))

    display = render_metric(result, _description())

    assert display.text == (
        "Production output: 30 kWh. Counting unit (caller supplied): reading."
    )
    assert display.task_semantics_verified is False


def test_display_checks_only_the_referenced_observation() -> None:
    flagged = _observation(10030, population=_FLAGGED_POPULATION)
    clean = _observation(30, population=PopulationReview("no_warning_detected"))
    result = _result(flagged, clean, claim_index=1)

    display = render_metric(result, _description())
    summary = summarize_advisory_reviews(result)

    assert display.value == 30
    assert summary.review_required is True
    assert summary.population_review_required_observations == (0,)
    assert summary.grain_review_required_observations == ()


def test_review_summary_lists_each_kind_and_never_certifies_semantics() -> None:
    result = _result(
        _observation(1, grain=_FLAGGED_GRAIN),
        _observation(2),
        _observation(3, population=_FLAGGED_POPULATION, grain=_FLAGGED_GRAIN),
    )

    summary = summarize_advisory_reviews(result)

    assert to_jsonable(summary) == {
        "review_required": True,
        "population_review_required_observations": [2],
        "grain_review_required_observations": [0, 2],
        "scope": "advisory_heuristics_only",
        "task_semantics_verified": False,
    }


def test_review_summary_without_warnings_is_not_a_verification() -> None:
    result = _result(_observation(30, population=PopulationReview("not_assessed")))

    summary = summarize_advisory_reviews(result)

    assert summary.review_required is False
    assert summary.population_review_required_observations == ()
    assert summary.task_semantics_verified is False


def test_review_summary_rejects_other_inputs() -> None:
    with pytest.raises(TypeError, match="InvestigationResult"):
        summarize_advisory_reviews(None)  # type: ignore[arg-type]


def _energy_source(tmp_path: Path) -> Path:
    source = tmp_path / "generation.csv"
    source.write_text(
        "reading,record type,kwh\n"
        "r1,production,10\nr2,production,20\nr3,test,500\nr4,calibration,10000\n",
        encoding="utf-8",
    )
    return source


def _energy_responses(sql: str, value: str) -> list[str]:
    return [
        json.dumps(
            {"action": "investigate", "reasoning": "Measure", "question": "Measure"}
        ),
        sql,
        json.dumps(
            {
                "conclusion": f"Total production output is {value} kWh.",
                "claims": [
                    {
                        "operation": "value",
                        "expected": value,
                        "left": {
                            "observation_index": 0,
                            "row_index": 0,
                            "column": "total",
                        },
                        "right": None,
                    }
                ],
            }
        ),
    ]


def _energy_args(source: Path, *, display: bool) -> list[str]:
    args = [
        "investigate",
        str(source),
        "--question",
        "What is total production output in kWh? Return exactly one VALUE claim.",
        "--require-claim",
        "value",
        "--max-steps",
        "1",
        "--allow-llm-data-disclosure",
    ]
    if display:
        args += ["--metric-description", "Production output", "reading", "kWh"]
    return args


@pytest.mark.parametrize(
    ("sql", "value", "display", "exit_code", "display_status", "flagged"),
    [
        (
            "SELECT SUM(kwh) AS total FROM generation WHERE \"record type\" != 'test'",
            "10030",
            True,
            1,
            "review_required",
            [0],
        ),
        (
            "SELECT SUM(kwh) AS total FROM generation "
            "WHERE \"record type\" = 'production'",
            "30",
            True,
            0,
            "rendered",
            [],
        ),
        (
            "SELECT SUM(kwh) AS total FROM generation WHERE \"record type\" != 'test'",
            "10030",
            False,
            0,
            None,
            [0],
        ),
    ],
    ids=["exclusion-with-display", "inclusion-with-display", "exclusion-no-display"],
)
def test_cli_withholds_caller_worded_display_for_flagged_population(
    sql: str,
    value: str,
    display: bool,
    exit_code: int,
    display_status: str | None,
    flagged: list[int],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VERISIGHT_GEMINI_API_KEY", "offline-key")
    output = tmp_path / "report.json"
    args = _energy_args(_energy_source(tmp_path), display=display)
    args += ["--output", str(output)]

    with patch(
        "verisight.execution.gemini.GeminiTextGenerationClient.generate",
        side_effect=_energy_responses(sql, value),
    ) as generate:
        assert main(args) == exit_code

    assert generate.call_count == 3
    report = json.loads(capsys.readouterr().out)
    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert report["workflow_status"] == "complete"
    assert report["claim_output_assessment"]["accepted"] is True
    assert report["investigation"]["observations"][0]["result"]["rows"] == [
        [int(value)]
    ]
    reviews = report["advisory_reviews"]
    assert reviews["review_required"] is bool(flagged)
    assert reviews["population_review_required_observations"] == flagged
    assert reviews["task_semantics_verified"] is False
    assert report.get("metric_display_status") == display_status
    if display_status == "review_required":
        assert report["metric_display"] is None
        assert "Inspect the executed SQL" in report["metric_display_unavailable_reason"]
        assert "Production output" not in json.dumps(report["investigation"])
    elif display_status == "rendered":
        assert report["metric_display"]["text"].startswith("Production output: 30 kWh.")


def test_cli_review_gate_preserves_the_original_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERISIGHT_GEMINI_API_KEY", "offline-key")
    result = _result(_observation(10030, population=_FLAGGED_POPULATION))
    args = _energy_args(_energy_source(tmp_path), display=True)

    with (
        patch("verisight.cli.VeriSight.investigate", return_value=result),
        patch(
            "verisight.execution.gemini.GeminiTextGenerationClient.generate",
            side_effect=AssertionError("No provider calls permitted"),
        ),
    ):
        assert main(args) == 1

    report = json.loads(capsys.readouterr().out)
    assert report["investigation"] == to_jsonable(replace(result))
    assert report["metric_display_status"] == "review_required"
