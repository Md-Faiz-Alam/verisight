"""Bounded cross-observation checks with scripted generation and real SQL."""

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

from verisight import VeriSight
from verisight.config import Settings
from verisight.execution.claim_verification import VerificationStatus
from verisight.execution.decisions import InvestigationAction, InvestigationDecision
from verisight.execution.gemini import GeminiTransientError, ProviderFailureDiagnostics
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_result import InvestigationStatus
from verisight.execution.planning import QueryPlan, QueryRequest
from verisight.serialization import to_jsonable


@dataclass(frozen=True)
class Scenario:
    name: str
    filename: str
    content: str
    base_sql: str
    included_state: str
    before: str
    after: str
    broad: str
    change: str
    wrong_change: str

    @property
    def queries(self) -> tuple[str, str, str]:
        return (
            self.base_sql,
            self.base_sql
            + f" WHERE period = 'before' AND state = '{self.included_state}'",
            self.base_sql
            + f" WHERE period = 'after' AND state = '{self.included_state}'",
        )


SCENARIOS = (
    Scenario(
        "finance",
        "ledger.csv",
        "period,state,amount\nbefore,posted,10.5\nafter,posted,12.25\nafter,pending,100\n",
        "SELECT SUM(amount) AS metric FROM ledger",
        "posted",
        "10.5",
        "12.25",
        "122.75",
        "1.75",
        "112.25",
    ),
    Scenario(
        "healthcare",
        "visits.csv",
        "period,state,minutes\nbefore,completed,1.25\nbefore,completed,2.5\nafter,completed,3.5\nafter,completed,4\nafter,cancelled,100\n",
        "SELECT AVG(minutes) AS metric FROM visits",
        "completed",
        "1.875",
        "3.75",
        "22.25",
        "1.875",
        "20.375",
    ),
    Scenario(
        "retail",
        "orders.csv",
        "period,state,total\nbefore,paid,10.5\nbefore,paid,20.25\nafter,paid,30.25\nafter,paid,10.5\nafter,cancelled,100\n",
        "SELECT SUM(total) AS metric FROM orders",
        "paid",
        "30.75",
        "40.75",
        "171.5",
        "10",
        "140.75",
    ),
    Scenario(
        "manufacturing",
        "batches.csv",
        "period,state,inspected,defective\nbefore,inspected,8,3\nafter,inspected,8,1\nafter,excluded,4,4\n",
        "SELECT 100.0 * SUM(defective) / SUM(inspected) AS metric FROM batches",
        "inspected",
        "37.5",
        "12.5",
        "40",
        "-25",
        "2.5",
    ),
    Scenario(
        "logistics",
        "routes.csv",
        "period,state,shipped,on_time\nbefore,delivered,2,1\nafter,delivered,8,5\nafter,cancelled,10,10\n",
        "SELECT 100.0 * SUM(on_time) / SUM(shipped) AS metric FROM routes",
        "delivered",
        "50",
        "62.5",
        "80",
        "12.5",
        "30",
    ),
)

QUESTIONS = (
    "Inspect the broad metric",
    "Measure the included before metric",
    "Measure the included after metric",
)
SECRET = "synthetic-private-later-failure"


class ScriptedPlanner:
    def __init__(
        self, queries: tuple[str, str, str], error: GeminiTransientError | None = None
    ) -> None:
        self.queries: dict[str, str] = dict(zip(QUESTIONS, queries, strict=True))
        self.error = error
        self.calls: list[str] = []

    def plan(self, request: QueryRequest) -> QueryPlan:
        self.calls.append(request.question)
        if self.error is not None and len(self.calls) == 3:
            raise self.error
        return QueryPlan(request.question, self.queries[request.question])


class ScriptedInvestigator:
    def __init__(self, error: GeminiTransientError | None = None) -> None:
        self.error = error
        self.states: list[InvestigationState] = []

    def decide(self, state: InvestigationState) -> InvestigationDecision:
        self.states.append(state)
        if self.error is not None and state.observation_count == 2:
            raise self.error
        if state.observation_count == 3:
            return InvestigationDecision(
                InvestigationAction.FINISH, "All observations collected"
            )
        return InvestigationDecision(
            InvestigationAction.INVESTIGATE,
            "Collect the next controlled observation",
            QUESTIONS[state.observation_count],
        )


class ControlledClient:
    def __init__(
        self,
        expected: str,
        left: int,
        right: int,
        error: GeminiTransientError | None = None,
    ) -> None:
        self.calls = 0
        self.error = error
        self.response = json.dumps(
            {
                "conclusion": f"The change is {expected}.",
                "claims": [
                    {
                        "operation": "difference",
                        "expected": expected,
                        "left": {
                            "observation_index": left,
                            "row_index": 0,
                            "column": "metric",
                        },
                        "right": {
                            "observation_index": right,
                            "row_index": 0,
                            "column": "metric",
                        },
                    }
                ],
            }
        )

    def generate(self, prompt: str) -> str:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.response


def _write_fixture(tmp_path: Path, scenario: Scenario) -> Path:
    path = tmp_path / scenario.filename
    path.write_text(scenario.content, encoding="utf-8")
    return path


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
@pytest.mark.parametrize(
    "mode",
    ["control", "wrong-observation", "reversed-reference", "missing-observation"],
)
def test_cross_observation_claims_and_independent_change_oracle(
    tmp_path: Path, scenario: Scenario, mode: str
) -> None:
    path = _write_fixture(tmp_path, scenario)
    expected = scenario.wrong_change if mode == "wrong-observation" else scenario.change
    left, right = {
        "control": (2, 1),
        "wrong-observation": (0, 1),
        "reversed-reference": (1, 2),
        "missing-observation": (3, 1),
    }[mode]
    planner = ScriptedPlanner(scenario.queries)
    investigator = ScriptedInvestigator()
    client = ControlledClient(expected, left, right)
    with patch(
        "verisight.execution.structured_synthesis.GeminiTextGenerationClient",
        return_value=client,
    ):
        result = VeriSight(
            settings=Settings(
                gemini_api_key="synthetic-key", allow_llm_data_disclosure=True
            ),
            planner=planner,
            investigator=investigator,
        ).investigate(path, "Compare included after and before metrics", max_steps=3)

    assert result.status is InvestigationStatus.COMPLETE
    assert result.observation_count == 3
    assert planner.calls == list(QUESTIONS)
    assert client.calls == 1
    assert [state.observation_count for state in investigator.states] == [0, 1, 2, 3]
    assert all(state.failed_attempt_count == 0 for state in investigator.states)
    assert (
        tuple(observation.sql for observation in result.observations)
        == scenario.queries
    )
    actuals = tuple(
        Decimal(str(observation.result.rows[0][0]))
        for observation in result.observations
    )
    assert actuals == tuple(
        Decimal(value) for value in (scenario.broad, scenario.before, scenario.after)
    )
    assert len(result.verified_claims) == 1
    verification = result.verified_claims[0].verification
    assert (
        verification.status
        is {
            "control": VerificationStatus.SUPPORTED,
            "wrong-observation": VerificationStatus.SUPPORTED,
            "reversed-reference": VerificationStatus.CONTRADICTED,
            "missing-observation": VerificationStatus.UNVERIFIABLE,
        }[mode]
    )
    assert verification.rounding_policy is None
    if mode == "missing-observation":
        assert verification.actual is None
    else:
        actual_change = {
            "control": Decimal(scenario.change),
            "wrong-observation": Decimal(scenario.wrong_change),
            "reversed-reference": -Decimal(scenario.change),
        }[mode]
        assert verification.actual == actual_change
        assert (verification.actual == Decimal(scenario.change)) is (mode == "control")
    assert result.generated_claims[0].left.observation_index == left
    assert result.generated_claims[0].right is not None
    assert result.generated_claims[0].right.observation_index == right
    assert result.narrative_verified is False
    assert result.unlinked_numbers == ()
    assert result.narrative_digit_coverage.status == "all_digits_parsed"
    payload = json.loads(json.dumps(to_jsonable(result)))
    assert [item["sql"] for item in payload["observations"]] == list(scenario.queries)
    assert (
        payload["verified_claims"][0]["verification"]["status"]
        == verification.status.value
    )
    assert payload["narrative_verified"] is False


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
@pytest.mark.parametrize(
    "stop", ["step-budget", "investigator", "planning", "synthesis"]
)
def test_later_failures_and_step_limits_preserve_ordered_evidence(
    tmp_path: Path, scenario: Scenario, stop: str
) -> None:
    path = _write_fixture(tmp_path, scenario)
    diagnostics = ProviderFailureDiagnostics(
        http_status=503,
        retryable=True,
        attempts=2,
        stage=(
            "investigator"
            if stop == "investigator"
            else "structured_synthesis"
            if stop == "synthesis"
            else "text_generation"
        ),
        call_number=1,
    )
    error = GeminiTransientError(SECRET, diagnostics=diagnostics)
    planner = ScriptedPlanner(scenario.queries, error if stop == "planning" else None)
    investigator = ScriptedInvestigator(error if stop == "investigator" else None)
    client = ControlledClient(
        scenario.change, 2, 1, error if stop == "synthesis" else None
    )
    with patch(
        "verisight.execution.structured_synthesis.GeminiTextGenerationClient",
        return_value=client,
    ):
        result = VeriSight(
            settings=Settings(
                gemini_api_key="synthetic-key", allow_llm_data_disclosure=True
            ),
            planner=planner,
            investigator=investigator,
        ).investigate(
            path,
            "Compare included after and before metrics",
            max_steps=2 if stop == "step-budget" else 3,
        )

    count = 3 if stop == "synthesis" else 2
    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == count
    assert (
        tuple(observation.sql for observation in result.observations)
        == scenario.queries[:count]
    )
    assert tuple(
        Decimal(str(observation.result.rows[0][0]))
        for observation in result.observations
    ) == tuple(
        Decimal(value)
        for value in (scenario.broad, scenario.before, scenario.after)[:count]
    )
    assert len(planner.calls) == (3 if stop in {"planning", "synthesis"} else 2)
    assert client.calls == (1 if stop == "synthesis" else 0)
    assert len(investigator.states) == (4 if stop == "synthesis" else 3)
    assert result.generated_claims == ()
    assert result.verified_claims == ()
    assert result.narrative_verified is False
    if stop in {"investigator", "planning"}:
        assert result.investigation_failure is not None
        assert result.investigation_failure.kind == "provider_unavailable"
        assert result.investigation_failure.stage == (
            "investigator" if stop == "investigator" else "query_execution"
        )
        assert result.investigation_failure.diagnostics == diagnostics
        assert result.synthesis_failure is None
    elif stop == "synthesis":
        assert result.synthesis_failure is not None
        assert result.synthesis_failure.kind.value == "provider_unavailable"
        assert result.synthesis_failure.diagnostics == diagnostics
        assert result.investigation_failure is None
    else:
        assert result.investigation_failure is None
        assert result.synthesis_failure is None
        assert "maximum number of analytical steps" in result.conclusion
    serialized = json.dumps(to_jsonable(result))
    assert SECRET not in serialized
    payload = json.loads(serialized)
    assert len(payload["observations"]) == count
    assert payload["status"] == "incomplete"
