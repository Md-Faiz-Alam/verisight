"""Known-answer pipeline benchmark; this does not measure live model accuracy."""

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts.live_evaluation import score_result, summarize_number_audits

from verisight import VeriSight
from verisight.config import Settings
from verisight.execution.claim_verification import VerificationStatus
from verisight.execution.decisions import InvestigationAction, InvestigationDecision
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_result import InvestigationStatus
from verisight.execution.planning import QueryPlan, QueryRequest
from verisight.serialization import to_jsonable


@dataclass(frozen=True)
class Scenario:
    name: str
    files: tuple[tuple[str, str], ...]
    question: str
    sql: str
    answer: str


SCENARIOS = (
    Scenario(
        name="finance_signed_posted_total",
        files=(
            (
                "ledger.csv",
                "cents,state\n12500,posted\n-2500,posted\n50,posted\n999,pending\n",
            ),
        ),
        question="What is the net posted amount in cents?",
        sql="SELECT SUM(cents) AS metric FROM ledger WHERE state = 'posted'",
        answer="10050",
    ),
    Scenario(
        name="healthcare_observed_completed_wait",
        files=(
            (
                "visits.csv",
                "minutes,state\n10,completed\n,completed\n30,completed\n100,cancelled\n",
            ),
        ),
        question="What is the mean recorded wait for completed visits?",
        sql="SELECT AVG(minutes) AS metric FROM visits WHERE state = 'completed'",
        answer="20",
    ),
    Scenario(
        name="retail_joined_line_value",
        files=(
            ("lines.csv", "sku,quantity\nA,2\nB,3\nA,1\n"),
            ("prices.csv", "sku,unit_price\nA,10\nB,20\n"),
        ),
        question="What is the total line value using the product prices?",
        sql=(
            "SELECT SUM(lines.quantity * prices.unit_price) AS metric "
            "FROM lines JOIN prices ON lines.sku = prices.sku"
        ),
        answer="90",
    ),
    Scenario(
        name="manufacturing_known_inspection_denominator",
        files=(("inspections.csv", "id,defective\n1,1\n2,0\n3,0\n4,0\n5,\n"),),
        question="What percentage of known inspection outcomes are defective?",
        sql=(
            "SELECT 100.0 * SUM(defective) / COUNT(defective) AS metric "
            "FROM inspections"
        ),
        answer="25",
    ),
    Scenario(
        name="logistics_known_delivered_lateness",
        files=(
            (
                "deliveries.csv",
                "id,late,state\n1,1,delivered\n2,0,delivered\n3,,delivered\n4,1,cancelled\n",
            ),
        ),
        question="What percentage of delivered shipments with known status were late?",
        sql=(
            "SELECT 100.0 * SUM(late) / COUNT(late) AS metric "
            "FROM deliveries WHERE state = 'delivered'"
        ),
        answer="50",
    ),
)


class FixedPlanner:
    def __init__(self, sql: str) -> None:
        self.sql = sql
        self.calls = 0

    def plan(self, request: QueryRequest) -> QueryPlan:
        self.calls += 1
        return QueryPlan(question=request.question, sql=self.sql)


class OneQueryInvestigator:
    def decide(self, state: InvestigationState) -> InvestigationDecision:
        if state.observations:
            return InvestigationDecision(
                action=InvestigationAction.FINISH,
                reasoning="The requested observation is available.",
            )
        return InvestigationDecision(
            action=InvestigationAction.INVESTIGATE,
            reasoning="Execute the benchmark query.",
            question=state.question,
        )


class ControlledClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda case: case.name)
@pytest.mark.parametrize(
    ("column", "offset", "verdict"),
    [
        pytest.param("metric", 0, VerificationStatus.SUPPORTED, id="correct"),
        pytest.param("metric", 1, VerificationStatus.CONTRADICTED, id="incorrect"),
        pytest.param("missing", 0, VerificationStatus.UNVERIFIABLE, id="missing"),
        pytest.param("unavailable", 0, VerificationStatus.UNVERIFIABLE, id="null"),
        pytest.param("label", 0, VerificationStatus.UNVERIFIABLE, id="text"),
    ],
)
def test_known_answer_investigation_pipeline(
    tmp_path: Path,
    scenario: Scenario,
    column: str,
    offset: int,
    verdict: VerificationStatus,
) -> None:
    paths = []
    for filename, content in scenario.files:
        path = tmp_path / filename
        path.write_text(content, encoding="utf-8")
        paths.append(path)

    sql = (
        "SELECT metric, CAST(NULL AS BIGINT) AS unavailable, 'unknown' AS label "
        f"FROM ({scenario.sql}) AS measured"
    )
    expected = str(Decimal(scenario.answer) + offset)
    client = ControlledClient(
        json.dumps(
            {
                "conclusion": "The submitted metric requires evidence verification.",
                "claims": [
                    {
                        "operation": "value",
                        "expected": expected,
                        "left": {
                            "observation_index": 0,
                            "row_index": 0,
                            "column": column,
                        },
                        "right": None,
                    }
                ],
            }
        )
    )
    planner = FixedPlanner(sql)

    with patch(
        "verisight.execution.structured_synthesis.GeminiTextGenerationClient",
        return_value=client,
    ) as provider:
        result = VeriSight(
            settings=Settings(
                gemini_api_key="synthetic-benchmark-key",
                allow_llm_data_disclosure=True,
            ),
            planner=planner,
            investigator=OneQueryInvestigator(),
        ).investigate(paths, scenario.question, max_steps=1)

    provider.assert_called_once()
    assert provider.call_args.kwargs["response_json_schema"] is not None
    assert planner.calls == 1
    assert len(client.prompts) == 1
    assert result.status is InvestigationStatus.COMPLETE
    assert result.observation_count == 1
    observation = result.observations[0]
    assert observation.sql == sql
    assert observation.result.columns == ("metric", "unavailable", "label")
    assert observation.result.row_count == 1
    assert Decimal(str(observation.result.rows[0][0])) == Decimal(scenario.answer)
    assert observation.result.rows[0][1:] == (None, "unknown")
    assert len(result.generated_claims) == 1
    assert len(result.verified_claims) == 1
    verification = result.verified_claims[0].verification
    assert verification.status is verdict
    if verdict is VerificationStatus.UNVERIFIABLE:
        assert verification.actual is None
    else:
        assert verification.actual == Decimal(scenario.answer)
    assert result.narrative_verified is False
    assert result.verification_scope == "referenced_numeric_values_only"

    serialized = json.loads(json.dumps(to_jsonable(result)))
    assert serialized["verified_claims"][0]["verification"]["status"] == verdict.value
    assert serialized["observations"][0]["sql"] == sql
    assert serialized["narrative_verified"] is False


@pytest.mark.parametrize(
    ("scenario", "wrong_sql", "wrong_answer"),
    [
        pytest.param(
            SCENARIOS[0],
            "SELECT SUM(cents) AS metric FROM ledger",
            "11049",
            id="missing-posted-filter",
        ),
        pytest.param(
            SCENARIOS[2],
            "SELECT SUM(lines.quantity * prices.unit_price) AS metric "
            "FROM lines CROSS JOIN prices",
            "180",
            id="cross-join-inflation",
        ),
        pytest.param(
            SCENARIOS[3],
            "SELECT 100.0 * SUM(defective) / COUNT(*) AS metric FROM inspections",
            "20",
            id="unknown-outcomes-in-denominator",
        ),
        pytest.param(
            SCENARIOS[1],
            "SELECT ROUND(AVG(COALESCE(minutes, 0)), 2) AS metric "
            "FROM visits WHERE state = 'completed'",
            "13.33",
            id="missing-waits-imputed-as-zero",
        ),
        pytest.param(
            SCENARIOS[4],
            "SELECT ROUND(100.0 * SUM(late) / COUNT(late), 2) AS metric "
            "FROM deliveries",
            "66.67",
            id="cancelled-shipments-included",
        ),
    ],
)
@pytest.mark.parametrize(
    "use_wrong_query", [False, True], ids=["control", "adversarial"]
)
def test_numeric_support_does_not_establish_analytical_correctness(
    tmp_path: Path,
    scenario: Scenario,
    wrong_sql: str,
    wrong_answer: str,
    use_wrong_query: bool,
) -> None:
    """The external oracle detects errors that cell-value verification cannot."""
    paths = []
    for filename, content in scenario.files:
        path = tmp_path / filename
        path.write_text(content, encoding="utf-8")
        paths.append(path)

    sql = wrong_sql if use_wrong_query else scenario.sql
    reported = wrong_answer if use_wrong_query else scenario.answer
    client = ControlledClient(
        json.dumps(
            {
                "conclusion": f"The requested metric is {reported}.",
                "claims": [
                    {
                        "operation": "value",
                        "expected": reported,
                        "left": {
                            "observation_index": 0,
                            "row_index": 0,
                            "column": "metric",
                        },
                        "right": None,
                    }
                ],
            }
        )
    )
    planner = FixedPlanner(sql)
    with patch(
        "verisight.execution.structured_synthesis.GeminiTextGenerationClient",
        return_value=client,
    ) as provider:
        result = VeriSight(
            settings=Settings(
                gemini_api_key="synthetic-benchmark-key",
                allow_llm_data_disclosure=True,
            ),
            planner=planner,
            investigator=OneQueryInvestigator(),
        ).investigate(paths, scenario.question, max_steps=1)

    provider.assert_called_once()
    assert planner.calls == 1
    assert len(client.prompts) == 1
    assert result.status is InvestigationStatus.COMPLETE
    assert result.observation_count == 1
    observation = result.observations[0]
    assert observation.sql == sql
    assert observation.result.columns == ("metric",)
    assert observation.result.row_count == 1
    actual = Decimal(str(observation.result.rows[0][0]))
    assert actual == Decimal(reported)
    assert len(result.verified_claims) == 1
    verification = result.verified_claims[0].verification
    assert verification.status is VerificationStatus.SUPPORTED
    assert verification.actual == actual

    # This benchmark oracle is independent of the claim and executed query.
    # It is not a semantic-verification feature of the application.
    agrees_with_known_answer = actual == Decimal(scenario.answer)
    assert agrees_with_known_answer is (not use_wrong_query)

    # The evaluator must use the independent answer, not just a supported verdict.
    report = score_result(result, scenario.answer)
    assert report["outcome"] == (
        "incorrect_numeric" if use_wrong_query else "correct_numeric"
    )
    assert report["expected"] == scenario.answer
    assert report["actual"] == str(verification.actual)
    assert report["verification_status"] == "supported"
    assert report["narrative_number_count"] == 1
    assert report["unlinked_number_count"] == 0
    assert report["narrative_verified"] is False
    assert summarize_number_audits({scenario.name: report}) == {
        "audited_case_count": 1,
        "unaudited_case_count": 0,
        "detected_token_count": 1,
        "unlinked_token_count": 0,
        "cases_with_unlinked_tokens": 0,
    }

    assert result.narrative_verified is False
    assert result.verification_scope == "referenced_numeric_values_only"

    serialized = json.loads(json.dumps(to_jsonable(result)))
    assert serialized["verified_claims"][0]["verification"]["status"] == "supported"
    assert serialized["observations"][0]["sql"] == sql
    assert serialized["narrative_verified"] is False
