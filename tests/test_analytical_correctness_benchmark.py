"""Controlled SQL baselines and semantic counterexamples, not live model accuracy."""

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts.live_evaluation import score_result

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
    control_sql: str
    answer: str
    wrong_sql: str
    wrong_answer: str


SCENARIOS = (
    Scenario(
        name="finance-signed-transaction-mean",
        files=(
            (
                "ledger.csv",
                "amount,state\n0.5,posted\n-0.25,posted\n1.25,posted\n8,pending\n",
            ),
        ),
        question=(
            "What is the mean signed amount per posted transaction, including refunds?"
        ),
        control_sql="SELECT AVG(amount) AS metric FROM ledger WHERE state = 'posted'",
        answer="0.5",
        wrong_sql=(
            "SELECT AVG(amount) AS metric FROM ledger WHERE state = 'posted' "
            "AND amount > 0"
        ),
        wrong_answer="0.875",
    ),
    Scenario(
        name="finance-principal-weighted-rate",
        files=(("loans.csv", "principal,rate\n1000,1.5\n3000,2.5\n"),),
        question="What is the principal-weighted annual rate in percentage points?",
        control_sql=(
            "SELECT SUM(principal * rate) / SUM(principal) AS metric FROM loans"
        ),
        answer="2.25",
        wrong_sql="SELECT AVG(rate) AS metric FROM loans",
        wrong_answer="2",
    ),
    Scenario(
        name="healthcare-observed-completed-mean",
        files=(
            (
                "visits.csv",
                "minutes,state\n1.25,completed\n2.5,completed\n,completed\n100,cancelled\n",
            ),
        ),
        question=(
            "What is the mean recorded wait for completed visits, excluding "
            "missing waits?"
        ),
        control_sql=(
            "SELECT AVG(minutes) AS metric FROM visits WHERE state = 'completed'"
        ),
        answer="1.875",
        wrong_sql=(
            "SELECT AVG(COALESCE(minutes, 0)) AS metric FROM visits WHERE "
            "state = 'completed'"
        ),
        wrong_answer="1.25",
    ),
    Scenario(
        name="healthcare-patients-versus-encounters",
        files=(
            (
                "encounters.csv",
                "patient_id,readmitted\nA,1\nA,1\nA,1\nB,1\nC,1\nD,0\nE,0\nF,0\nG,0\nH,0\n",
            ),
        ),
        question="What percentage of distinct patients had at least one readmission?",
        control_sql=(
            "SELECT 100.0 * SUM(readmitted) / COUNT(*) AS metric FROM (SELECT"
            " patient_id, MAX(readmitted) AS readmitted FROM encounters GROUP"
            " BY patient_id) AS patients"
        ),
        answer="37.5",
        wrong_sql="SELECT 100.0 * SUM(readmitted) / COUNT(*) AS metric FROM encounters",
        wrong_answer="50",
    ),
    Scenario(
        name="retail-order-join-multiplication",
        files=(
            ("orders.csv", "order_id,total\nA,10.5\nB,10.5\nC,20.25\n"),
            ("items.csv", "order_id,item_id\nA,1\nA,2\nA,3\nB,4\nC,5\n"),
        ),
        question=(
            "What is the sum of order totals for orders having items, "
            "counting each order once?"
        ),
        control_sql=(
            "SELECT SUM(total) AS metric FROM orders WHERE EXISTS (SELECT 1 "
            "FROM items WHERE items.order_id = orders.order_id)"
        ),
        answer="41.25",
        wrong_sql=(
            "SELECT SUM(orders.total) AS metric FROM orders JOIN items ON "
            "orders.order_id = items.order_id"
        ),
        wrong_answer="62.25",
    ),
    Scenario(
        name="retail-quantity-weighted-price",
        files=(("lines.csv", "quantity,unit_price\n1,10.5\n3,20.5\n"),),
        question="What is the average selling price per unit, weighted by quantity?",
        control_sql=(
            "SELECT SUM(quantity * unit_price) / SUM(quantity) AS metric FROM lines"
        ),
        answer="18",
        wrong_sql="SELECT AVG(unit_price) AS metric FROM lines",
        wrong_answer="15.5",
    ),
    Scenario(
        name="manufacturing-known-outcome-rate",
        files=(
            (
                "inspections.csv",
                "id,defective\n1,1\n2,1\n3,1\n4,0\n5,0\n6,0\n7,0\n8,0\n9,\n10,\n",
            ),
        ),
        question=(
            "What percentage of known inspection outcomes are defective, "
            "excluding unknown outcomes?"
        ),
        control_sql=(
            "SELECT 100.0 * SUM(defective) / COUNT(defective) AS metric FROM "
            "inspections"
        ),
        answer="37.5",
        wrong_sql="SELECT 100.0 * SUM(defective) / COUNT(*) AS metric FROM inspections",
        wrong_answer="30",
    ),
    Scenario(
        name="manufacturing-pooled-batch-rate",
        files=(("batches.csv", "inspected,defective\n2,1\n6,0\n"),),
        question="What is the pooled defect percentage across all inspected units?",
        control_sql=(
            "SELECT 100.0 * SUM(defective) / SUM(inspected) AS metric FROM batches"
        ),
        answer="12.5",
        wrong_sql="SELECT AVG(100.0 * defective / inspected) AS metric FROM batches",
        wrong_answer="25",
    ),
    Scenario(
        name="logistics-signed-delay-mean",
        files=(
            (
                "deliveries.csv",
                "delay,state\n0.5,delivered\n1.5,delivered\n-0.25,delivered\n0.25,delivered\n100,cancelled\n",
            ),
        ),
        question=(
            "What is the mean signed delay for delivered shipments, "
            "preserving negative early arrivals?"
        ),
        control_sql=(
            "SELECT AVG(delay) AS metric FROM deliveries WHERE state = 'delivered'"
        ),
        answer="0.5",
        wrong_sql=(
            "SELECT AVG(ABS(delay)) AS metric FROM deliveries WHERE state = 'delivered'"
        ),
        wrong_answer="0.625",
    ),
    Scenario(
        name="logistics-pooled-route-rate",
        files=(("routes.csv", "shipped,on_time\n1,1\n1,1\n2,1\n4,0\n"),),
        question=(
            "What percentage of all shipped parcels were on time, weighting "
            "routes by parcel count?"
        ),
        control_sql="SELECT 100.0 * SUM(on_time) / SUM(shipped) AS metric FROM routes",
        answer="37.5",
        wrong_sql="SELECT AVG(100.0 * on_time / shipped) AS metric FROM routes",
        wrong_answer="62.5",
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
                InvestigationAction.FINISH, "Evidence collected"
            )
        return InvestigationDecision(
            InvestigationAction.INVESTIGATE, "Execute controlled query", state.question
        )


class ControlledClient:
    def __init__(self, reported: str) -> None:
        self.calls = 0
        self.response = json.dumps(
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

    def generate(self, prompt: str) -> str:
        self.calls += 1
        return self.response


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
@pytest.mark.parametrize("adversarial", [False, True], ids=["control", "wrong-query"])
def test_independent_answer_separates_numeric_support_from_correctness(
    tmp_path: Path, scenario: Scenario, adversarial: bool
) -> None:
    paths = []
    for filename, content in scenario.files:
        path = tmp_path / filename
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    sql = scenario.wrong_sql if adversarial else scenario.control_sql
    reported = scenario.wrong_answer if adversarial else scenario.answer
    planner = FixedPlanner(sql)
    client = ControlledClient(reported)

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
    assert client.calls == 1
    assert result.status is InvestigationStatus.COMPLETE
    assert result.investigation_failure is None
    assert result.synthesis_failure is None
    assert result.observation_count == 1
    observation = result.observations[0]
    assert observation.sql == sql
    assert observation.result.columns == ("metric",)
    assert observation.result.row_count == 1
    assert Decimal(str(observation.result.rows[0][0])) == Decimal(reported)
    assert len(result.verified_claims) == 1
    verdict = result.verified_claims[0].verification
    assert verdict.status is VerificationStatus.SUPPORTED
    assert verdict.actual == Decimal(reported)
    assert verdict.rounding_policy is None
    assert verdict.rounded_actual is None
    # The oracle is specified with the fixture, not computed from generated SQL.
    assert (verdict.actual == Decimal(scenario.answer)) is (not adversarial)
    report = score_result(result, scenario.answer)
    assert report["outcome"] == (
        "incorrect_numeric" if adversarial else "correct_numeric"
    )
    assert report["expected"] == scenario.answer
    assert report["actual"] == str(verdict.actual)
    assert report["verification_status"] == "supported"
    assert report["narrative_number_count"] == 1
    assert report["unlinked_number_count"] == 0
    assert result.narrative_digit_coverage.status == "all_digits_parsed"
    assert result.narrative_verified is False
    payload = json.loads(json.dumps(to_jsonable(result)))
    assert payload["verified_claims"][0]["verification"]["actual"] == str(
        verdict.actual
    )
    assert payload["observations"][0]["sql"] == sql
    assert payload["narrative_verified"] is False
