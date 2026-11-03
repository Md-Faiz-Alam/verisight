"""An early finish decision cannot end a run without any SQL evidence."""

import json
from pathlib import Path

import pytest

from verisight import VeriSight
from verisight.config import Settings
from verisight.execution.claim_verification import ClaimOperation, VerificationStatus
from verisight.execution.gemini import GeminiTransientError, ProviderFailureDiagnostics
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.generative_investigator import GenerativeInvestigator
from verisight.execution.generative_repair import GenerativeQueryRepairer
from verisight.execution.investigation_result import (
    ClaimOutputContract,
    InvestigationResult,
    InvestigationStatus,
    SynthesisRecovery,
)
from verisight.execution.structured_synthesis import StructuredInvestigationSynthesizer

QUESTION = "How many trips have no recorded payment method?"
FINISH = json.dumps(
    {"action": "finish", "reasoning": "The profile reports it.", "question": None}
)
MISSING_SQL = "SELECT COUNT(*) AS missing_trips FROM trips WHERE payment IS NULL"
SHARE_SQL = (
    "SELECT COUNT(*) AS missing_trips, "
    "(SELECT COUNT(*) FROM trips) AS all_trips FROM trips WHERE payment IS NULL"
)
PERCENT_SQL = (
    "SELECT 100.0 * SUM(CASE WHEN payment IS NULL THEN 1 ELSE 0 END) / COUNT(*) "
    "AS missing_percentage FROM trips"
)


class _Script:
    def __init__(self, items: list[str | Exception]) -> None:
        self.items = list(items)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _claim(column: str, expected: str, observation: int = 0) -> str:
    return json.dumps(
        {
            "conclusion": f"The answer is {expected}.",
            "claims": [
                {
                    "operation": "value",
                    "expected": expected,
                    "left": {
                        "observation_index": observation,
                        "row_index": 0,
                        "column": column,
                    },
                    "right": None,
                }
            ],
        }
    )


def _run(
    tmp_path: Path,
    *,
    decide: list[str | Exception],
    plan: list[str | Exception],
    synth: list[str | Exception],
    repair: list[str | Exception] | None = None,
    question: str = QUESTION,
) -> tuple[InvestigationResult, _Script, _Script]:
    source = tmp_path / "trips.csv"
    source.write_text("payment,fare\ncash,5\n,7\ncard,9\n,11\n", encoding="utf-8")
    investigator, planner = _Script(decide), _Script(plan)
    app = VeriSight(
        settings=Settings(gemini_api_key=None, allow_llm_data_disclosure=False),
        planner=GenerativeQueryPlanner(planner),
        investigator=GenerativeInvestigator(investigator),
        repairer=GenerativeQueryRepairer(_Script(repair or [])),
        synthesizer=StructuredInvestigationSynthesizer(_Script(synth)),
    )
    result = app.investigate(
        source,
        question,
        max_steps=3,
        claim_output_contract=ClaimOutputContract((ClaimOperation.VALUE,)),
    )
    return result, investigator, planner


def test_early_finish_queries_the_original_question(tmp_path: Path) -> None:
    result, investigator, planner = _run(
        tmp_path,
        decide=[FINISH, FINISH],
        plan=[MISSING_SQL],
        synth=[_claim("missing_trips", "2")],
    )

    assert result.status is InvestigationStatus.COMPLETE
    assert result.initial_query_required is True
    assert result.observations[0].question == QUESTION
    assert result.observations[0].sql == MISSING_SQL
    assert result.verified_claims[0].verification.status is (
        VerificationStatus.SUPPORTED
    )
    assert QUESTION in planner.prompts[0]
    # The investigator sees the new evidence before synthesis.
    assert len(investigator.prompts) == 2


def test_failed_initial_query_is_not_retried(tmp_path: Path) -> None:
    bad = "SELECT no_such_column FROM trips"
    result, investigator, planner = _run(
        tmp_path,
        decide=[FINISH, FINISH],
        plan=[bad],
        repair=[bad, bad, bad],
        synth=[],
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.initial_query_required is True
    assert result.failed_attempt_count == 1
    assert "all attempted analytical queries failed" in result.conclusion
    assert len(planner.prompts) == 1
    assert len(investigator.prompts) == 2


def test_initial_query_and_recovery_can_both_run(tmp_path: Path) -> None:
    question = "What percentage of trips have no recorded payment method?"
    invented = _claim("missing_percentage", "50")
    result, _, planner = _run(
        tmp_path,
        decide=[FINISH, FINISH],
        plan=[SHARE_SQL, PERCENT_SQL],
        synth=[invented, invented, _claim("missing_percentage", "50", 1)],
        question=question,
    )

    assert result.status is InvestigationStatus.COMPLETE
    assert result.initial_query_required is True
    assert result.synthesis_recovery == SynthesisRecovery(
        "invalid_claim_reference", True, True
    )
    assert [item.sql for item in result.observations] == [SHARE_SQL, PERCENT_SQL]
    assert len(planner.prompts) == 2


def test_normal_runs_do_not_report_an_initial_query(tmp_path: Path) -> None:
    investigate = json.dumps(
        {"action": "investigate", "reasoning": "r", "question": "Count missing"}
    )
    result, _, _ = _run(
        tmp_path,
        decide=[investigate, FINISH],
        plan=[MISSING_SQL],
        synth=[_claim("missing_trips", "2")],
    )

    assert result.status is InvestigationStatus.COMPLETE
    assert result.initial_query_required is False


def test_provider_failure_on_the_initial_query_is_raised(tmp_path: Path) -> None:
    unavailable = GeminiTransientError(
        "unavailable",
        diagnostics=ProviderFailureDiagnostics(503, True, 2, "text_generation", 1),
    )

    with pytest.raises(GeminiTransientError):
        _run(tmp_path, decide=[FINISH], plan=[unavailable], synth=[])
