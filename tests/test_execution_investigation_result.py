import json
from dataclasses import replace
from decimal import Decimal
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
from verisight.execution.structured_synthesis import StructuredInvestigationSynthesizer
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
    assert result.quantitative_statements == ()


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
    assert tuple(
        statement.claim_index for statement in report.quantitative_statements
    ) == (
        0,
        1,
        2,
        3,
    )
    for index, statement in enumerate(report.quantitative_statements):
        assert statement.verified_claim is report.verified_claims[index]
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
    assert report.quantitative_statements == ()
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


@pytest.mark.parametrize(
    "value",
    [0, -7, 2**100, Decimal("1234.567890123456789012345678")],
    ids=["zero", "negative", "large-integer", "exact-decimal"],
)
def test_quantitative_statement_preserves_exact_evidence(value: int | Decimal) -> None:
    claim = NumericalClaim(
        ClaimOperation.VALUE, value, EvidenceReference(0, 0, "metric")
    )
    result = InvestigationResult(
        question="Read the metric.",
        conclusion="Unverified narrative.",
        analysis=_build_analysis_result(),
        observations=(
            QueryObservation(
                question="Read the metric.",
                sql="SELECT metric FROM measurements",
                result=QueryResult(columns=("metric",), rows=((value,),)),
            ),
        ),
        generated_claims=(claim,),
    )

    statement = result.quantitative_statements[0]

    assert statement.claim_index == 0
    assert statement.verified_claim is result.verified_claims[0]
    assert statement.text == (
        f"Claim 1 (value): expected {value}; evidence {value}; "
        "absolute tolerance 0; status supported."
    )
    assert result.narrative_verified is False
    serialized = json.loads(json.dumps(to_jsonable(result)))
    saved = serialized["quantitative_statements"][0]
    assert saved["text"] == statement.text
    assert saved["claim_index"] == 0
    assert saved["verified_claim"]["claim"]["left"]["column"] == "metric"
    assert saved["verified_claim"]["verification"]["actual"] == str(value)


def test_quantitative_statement_exposes_tolerance_and_recomputes_on_change() -> None:
    observation = QueryObservation(
        question="Read the metric.",
        sql="SELECT metric FROM measurements",
        result=QueryResult(columns=("metric",), rows=((11,),)),
    )
    claim = NumericalClaim(
        ClaimOperation.VALUE,
        10,
        EvidenceReference(0, 0, "metric"),
        absolute_tolerance=1,
    )
    result = InvestigationResult(
        question="Read the metric.",
        conclusion="Unverified narrative.",
        analysis=_build_analysis_result(),
        observations=(observation,),
        generated_claims=(claim,),
    )

    assert result.quantitative_statements[0].text == (
        "Claim 1 (value): expected 10; evidence 11; "
        "absolute tolerance 1; status supported."
    )
    changed = replace(result, generated_claims=(replace(claim, absolute_tolerance=0),))
    assert changed.quantitative_statements[0].text == (
        "Claim 1 (value): expected 10; evidence 11; "
        "absolute tolerance 0; status contradicted."
    )
    assert (
        changed.quantitative_statements[0].verified_claim is changed.verified_claims[0]
    )
    assert result.quantitative_statements[0].verified_claim.verification.status is (
        VerificationStatus.SUPPORTED
    )


def test_structured_investigation_renders_only_claim_linked_quantities(
    tmp_path: Path,
) -> None:
    class Client:
        def generate(self, prompt: str) -> str:
            left = {"observation_index": 0, "row_index": 0, "column": "current_total"}
            right = {"observation_index": 0, "row_index": 0, "column": "previous_total"}
            return json.dumps(
                {
                    "conclusion": "There are 9999 rows. Revenue caused the change.",
                    "claims": [
                        {
                            "operation": "value",
                            "expected": "30",
                            "left": left,
                            "right": None,
                        },
                        {
                            "operation": "difference",
                            "expected": "10",
                            "left": left,
                            "right": right,
                        },
                        {
                            "operation": "value",
                            "expected": "31",
                            "left": left,
                            "right": None,
                        },
                        {
                            "operation": "value",
                            "expected": "5",
                            "left": {**left, "column": "absent"},
                            "right": None,
                        },
                    ],
                }
            )

    path = tmp_path / "measurements.csv"
    path.write_text("current_value,previous_value\n10,8\n20,12\n", encoding="utf-8")
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False),
        planner=_SyntheticPlanner(),
        investigator=_OneQueryInvestigator(),
        synthesizer=StructuredInvestigationSynthesizer(Client()),
    )

    result = app.investigate(path, "Compare the totals.", max_steps=1)

    assert result.status is InvestigationStatus.COMPLETE
    assert result.narrative_verified is False
    assert "9999" in result.conclusion
    assert [statement.text for statement in result.quantitative_statements] == [
        (
            "Claim 1 (value): expected 30; evidence 30; "
            "absolute tolerance 0; status supported."
        ),
        (
            "Claim 2 (difference, left minus right): expected 10; evidence 10; "
            "absolute tolerance 0; status supported."
        ),
        (
            "Claim 3 (value): expected 31; evidence 30; "
            "absolute tolerance 0; status contradicted."
        ),
        (
            "Claim 4 (value): expected 5; evidence unavailable; "
            "absolute tolerance 0; status unverifiable."
        ),
    ]
    for index, statement in enumerate(result.quantitative_statements):
        assert statement.claim_index == index
        assert statement.verified_claim is result.verified_claims[index]
        assert statement.verified_claim.claim is result.generated_claims[index]
        reference = statement.verified_claim.claim.left
        assert result.observations[reference.observation_index].sql.startswith(
            "SELECT SUM"
        )
        assert "9999" not in statement.text
        assert "caused" not in statement.text
    assert result.quantitative_statements[1].verified_claim.claim.right is not None
    serialized = json.loads(json.dumps(to_jsonable(result)))
    assert (
        serialized["quantitative_statements"][3]["verified_claim"]["verification"][
            "status"
        ]
        == "unverifiable"
    )
