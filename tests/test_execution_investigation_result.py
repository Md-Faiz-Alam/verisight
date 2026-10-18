import json
from pathlib import Path

import pytest

from verisight import VeriSight
from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import (
    AnalysisResultBuilder,
    DatasetAnalysisResult,
)
from verisight.config import Settings
from verisight.execution.claim_verification import (
    ClaimOperation,
    EvidenceReference,
    NumericalClaim,
    VerificationStatus,
)
from verisight.execution.decisions import InvestigationAction, InvestigationDecision
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_result import (
    InvestigationResult,
    InvestigationStatus,
)
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation
from verisight.execution.planning import QueryPlan, QueryRequest
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile
from verisight.serialization import to_jsonable


def _build_analysis_result() -> DatasetAnalysisResult:
    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(),
    )

    return AnalysisResultBuilder().build(analysis)


def test_investigation_result_preserves_completed_investigation() -> None:
    observation = QueryObservation(
        question="What is revenue by month?",
        sql="SELECT month, SUM(revenue) FROM sales GROUP BY month",
        result=QueryResult(
            columns=("month", "revenue"),
            rows=(
                ("January", 1000),
                ("February", 800),
            ),
        ),
    )

    analysis = _build_analysis_result()

    result = InvestigationResult(
        question="Why did revenue decline?",
        conclusion="Revenue declined from January to February.",
        analysis=analysis,
        observations=(observation,),
    )

    assert result.question == "Why did revenue decline?"
    assert result.conclusion == ("Revenue declined from January to February.")
    assert result.analysis is analysis
    assert result.observations == (observation,)
    assert result.observation_count == 1


def test_investigation_result_can_have_no_observations() -> None:
    result = InvestigationResult(
        question="Are there data-quality concerns?",
        conclusion="The deterministic analysis is sufficient.",
        analysis=_build_analysis_result(),
    )

    assert result.observations == ()
    assert result.observation_count == 0


@pytest.mark.parametrize(
    "question",
    [
        "",
        " ",
        "\n\t",
    ],
)
def test_investigation_result_rejects_empty_question(
    question: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="Investigation question must not be empty.",
    ):
        InvestigationResult(
            question=question,
            conclusion="The investigation is complete.",
            analysis=_build_analysis_result(),
        )


@pytest.mark.parametrize(
    "conclusion",
    [
        "",
        " ",
        "\n\t",
    ],
)
def test_investigation_result_rejects_empty_conclusion(
    conclusion: str,
) -> None:
    with pytest.raises(
        ValueError,
        match="Investigation conclusion must not be empty.",
    ):
        InvestigationResult(
            question="Why did revenue decline?",
            conclusion=conclusion,
            analysis=_build_analysis_result(),
        )


class _SyntheticPlanner:
    def plan(self, request: QueryRequest) -> QueryPlan:
        return QueryPlan(
            question=request.question,
            sql=(
                "SELECT SUM(current_value) AS current_total, "
                "SUM(previous_value) AS previous_total "
                "FROM measurements"
            ),
        )


class _OneQueryInvestigator:
    def decide(self, state: InvestigationState) -> InvestigationDecision:
        if state.observations:
            return InvestigationDecision(
                action=InvestigationAction.FINISH,
                reasoning="The requested totals have been collected.",
            )
        return InvestigationDecision(
            action=InvestigationAction.INVESTIGATE,
            reasoning="Both totals are needed for the comparison.",
            question="What are the current and previous totals?",
        )


class _SyntheticSynthesizer:
    def synthesize(self, state: InvestigationState) -> str:
        return "Totals were collected. Their causes have not been established."


@pytest.mark.parametrize(
    ("current_values", "previous_values", "current_total", "difference"),
    [
        ([10, 20], [8, 12], 30, 10),
        ([4, 5], [6, 7], 9, -4),
        ([0, 0], [0, 0], 0, 0),
        ([-10, 3], [-4, 2], -7, -5),
        ([9007199254740993, 2], [9007199254740993, 1], 9007199254740995, 1),
    ],
    ids=["increase", "decrease", "zero", "negative", "large-integer"],
)
def test_verification_benchmark_uses_real_investigation_sql(
    tmp_path: Path,
    current_values: list[int],
    previous_values: list[int],
    current_total: int,
    difference: int,
) -> None:
    path = tmp_path / "measurements.json"
    path.write_text(
        json.dumps(
            [
                {"current_value": current, "previous_value": previous}
                for current, previous in zip(
                    current_values, previous_values, strict=True
                )
            ]
        ),
        encoding="utf-8",
    )
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False),
        planner=_SyntheticPlanner(),
        investigator=_OneQueryInvestigator(),
        synthesizer=_SyntheticSynthesizer(),
    )
    investigation = app.investigate(path, "Compare the two totals.", max_steps=1)
    left = EvidenceReference(0, 0, "current_total")
    right = EvidenceReference(0, 0, "previous_total")
    claims = (
        NumericalClaim(ClaimOperation.VALUE, current_total, left),
        NumericalClaim(ClaimOperation.DIFFERENCE, difference, left, right),
        NumericalClaim(ClaimOperation.DIFFERENCE, difference + 1, left, right),
        NumericalClaim(ClaimOperation.VALUE, 0, EvidenceReference(0, 0, "absent")),
    )

    report = investigation.verify_claims(claims)

    assert investigation.status is InvestigationStatus.COMPLETE
    assert investigation.observation_count == 1
    assert report.investigation is investigation
    assert tuple(item.claim for item in report.verified_claims) == claims
    assert tuple(item.verification.status for item in report.verified_claims) == (
        VerificationStatus.SUPPORTED,
        VerificationStatus.SUPPORTED,
        VerificationStatus.CONTRADICTED,
        VerificationStatus.UNVERIFIABLE,
    )
    assert report.verified_claims[1].verification.actual == difference
    assert report.verification_scope == "referenced_numeric_values_only"
    serialized = json.loads(json.dumps(to_jsonable(report)))
    assert serialized["verified_claims"][0]["claim"]["left"] == {
        "observation_index": 0,
        "row_index": 0,
        "column": "current_total",
    }
    assert serialized["verified_claims"][0]["verification"]["actual"] == str(
        current_total
    )
    assert serialized["investigation"]["observations"][0]["sql"] == (
        investigation.observations[0].sql
    )
    assert serialized["investigation"]["conclusion"] == investigation.conclusion


def test_empty_claim_report_does_not_certify_a_conclusion() -> None:
    investigation = InvestigationResult(
        question="What can be established?",
        conclusion="No numerical claims have been checked.",
        analysis=_build_analysis_result(),
    )

    report = investigation.verify_claims(())

    assert report.verified_claims == ()
    assert report.investigation is investigation
    assert report.verification_scope == "referenced_numeric_values_only"


def test_claim_without_observations_is_unverifiable() -> None:
    investigation = InvestigationResult(
        question="What can be established?",
        conclusion="Investigation incomplete.",
        analysis=_build_analysis_result(),
        status=InvestigationStatus.INCOMPLETE,
    )
    claim = NumericalClaim(ClaimOperation.VALUE, 10, EvidenceReference(0, 0, "value"))

    report = investigation.verify_claims((claim,))

    assert (
        report.verified_claims[0].verification.status is VerificationStatus.UNVERIFIABLE
    )
    assert report.investigation.status is InvestigationStatus.INCOMPLETE
