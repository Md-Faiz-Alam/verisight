"""Preserve collected SQL evidence after later expected workflow failures."""

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock

import pytest
from scripts.live_evaluation import score_result
from sqlglot.errors import OptimizeError

from verisight import VeriSight
from verisight.config import Settings
from verisight.error_reporting import ErrorCode
from verisight.execution.exceptions import (
    InvestigationError,
    QueryPlanningError,
    QueryValidationError,
)
from verisight.execution.gemini import (
    GeminiGenerationError,
    GeminiTransientError,
    ProviderFailureDiagnostics,
)
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.generative_investigator import GenerativeInvestigator
from verisight.execution.generative_repair import GenerativeQueryRepairer
from verisight.execution.investigation_result import (
    InvestigationFailure,
    InvestigationStatus,
)
from verisight.execution.prompt_budget import PromptBudgetExceededError
from verisight.public_api import run_public_operation
from verisight.serialization import to_jsonable

SECRET = "synthetic-private-error-content"
FIRST = json.dumps(
    {"action": "investigate", "reasoning": "Need evidence", "question": "Get total"}
)
SECOND = json.dumps(
    {"action": "investigate", "reasoning": "Need comparison", "question": "Compare"}
)
SQL = "SELECT SUM(value) AS total FROM measurements"


@pytest.mark.parametrize("stage", ["investigator", "planning", "repair"])
@pytest.mark.parametrize("transient", [False, True])
def test_later_provider_failure_preserves_real_sql_evidence(
    tmp_path: Path, stage: str, transient: bool
) -> None:
    path = tmp_path / "measurements.csv"
    path.write_text("value\n10\n20\n", encoding="utf-8")
    diagnostics = ProviderFailureDiagnostics(
        http_status=503 if transient else 400,
        retryable=transient,
        attempts=2 if transient else 1,
        stage="investigator" if stage == "investigator" else "text_generation",
        call_number=2,
    )
    error_type = GeminiTransientError if transient else GeminiGenerationError
    error = error_type(SECRET, diagnostics=diagnostics)
    decisions = Mock()
    decisions.generate.side_effect = [
        FIRST,
        error if stage == "investigator" else SECOND,
    ]
    planning = Mock()
    planning.generate.side_effect = [
        SQL,
        error if stage == "planning" else "SELECT absent_column FROM measurements",
    ]
    repair = Mock()
    repair.generate.side_effect = error
    synthesis = Mock()
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False),
        planner=GenerativeQueryPlanner(planning),
        repairer=GenerativeQueryRepairer(repair),
        investigator=GenerativeInvestigator(decisions),
        synthesizer=synthesis,
    )

    public = run_public_operation(
        lambda: app.investigate(path, "Investigate the total", max_steps=2)
    )

    assert public.succeeded is True
    assert public.error is None
    result = public.value
    assert result is not None
    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.analysis.analysis.schema.tables[0].row_count == 2
    assert result.observation_count == 1
    assert result.observations[0].sql == SQL
    assert result.observations[0].result.rows == ((30,),)
    assert result.generated_claims == ()
    assert result.verified_claims == ()
    assert result.narrative_verified is False
    assert result.synthesis_failure is None
    expected = {
        "stage": "investigator" if stage == "investigator" else "query_execution",
        "kind": "provider_unavailable" if transient else "provider_error",
        "diagnostics": {
            "http_status": diagnostics.http_status,
            "retryable": transient,
            "attempts": diagnostics.attempts,
            "stage": diagnostics.stage,
            "call_number": 2,
        },
    }
    serialized = json.dumps(to_jsonable(result))
    assert json.loads(serialized)["investigation_failure"] == expected
    report = score_result(result, "30")
    assert report["outcome"] == "incomplete"
    assert report["investigation_failure"] == expected
    assert SECRET not in serialized
    assert SECRET not in json.dumps(report)
    synthesis.synthesize.assert_not_called()
    assert decisions.generate.call_count == 2
    assert planning.generate.call_count == (1 if stage == "investigator" else 2)
    assert repair.generate.call_count == (1 if stage == "repair" else 0)
    with pytest.raises(ValueError, match="requires an incomplete investigation"):
        replace(result, status=InvestigationStatus.COMPLETE)


@pytest.mark.parametrize("has_evidence", [False, True])
def test_malformed_investigator_response_retains_existing_evidence(
    tmp_path: Path, has_evidence: bool
) -> None:
    path = tmp_path / "measurements.csv"
    path.write_text("value\n10\n20\n", encoding="utf-8")
    decisions = Mock()
    decisions.generate.side_effect = [FIRST, SECRET] if has_evidence else [SECRET]
    planning = Mock()
    planning.generate.return_value = SQL
    synthesis = Mock()
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False),
        planner=GenerativeQueryPlanner(planning),
        investigator=GenerativeInvestigator(decisions),
        synthesizer=synthesis,
    )
    if has_evidence:
        result = app.investigate(path, "Get total", max_steps=1)
        assert result.status is InvestigationStatus.INCOMPLETE
        assert result.observations[0].result.rows == ((30,),)
        assert result.investigation_failure == InvestigationFailure(
            "investigator", "investigation_error"
        )
        assert SECRET not in json.dumps(to_jsonable(result))
    else:
        with pytest.raises(InvestigationError):
            app.investigate(path, "Get total", max_steps=1)
        planning.generate.assert_not_called()
    synthesis.synthesize.assert_not_called()


def test_later_planning_budget_failure_keeps_observations(tmp_path: Path) -> None:
    path = tmp_path / "measurements.csv"
    path.write_text("value\n10\n20\n", encoding="utf-8")
    decisions = Mock()
    decisions.generate.side_effect = [FIRST, SECOND]
    planning = Mock()
    planning.generate.side_effect = [
        SQL,
        PromptBudgetExceededError(max_prompt_chars=10, actual_prompt_chars=11),
    ]
    synthesis = Mock()
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False),
        planner=GenerativeQueryPlanner(planning),
        investigator=GenerativeInvestigator(decisions),
        synthesizer=synthesis,
    )
    result = app.investigate(path, "Investigate", max_steps=2)
    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observations[0].result.rows == ((30,),)
    assert result.investigation_failure == InvestigationFailure(
        "query_execution", "prompt_budget_exceeded"
    )
    synthesis.synthesize.assert_not_called()


@pytest.mark.parametrize("stage", ["investigator", "planning", "repair"])
def test_unexpected_later_errors_still_propagate(tmp_path: Path, stage: str) -> None:
    path = tmp_path / "measurements.csv"
    path.write_text("value\n10\n20\n", encoding="utf-8")
    error = RuntimeError("Synthetic programming defect")
    decisions = Mock()
    decisions.generate.side_effect = [
        FIRST,
        error if stage == "investigator" else SECOND,
    ]
    planning = Mock()
    planning.generate.side_effect = [
        SQL,
        error if stage == "planning" else "SELECT absent_column FROM measurements",
    ]
    repair = Mock()
    repair.generate.side_effect = error
    synthesis = Mock()
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False),
        planner=GenerativeQueryPlanner(planning),
        repairer=GenerativeQueryRepairer(repair),
        investigator=GenerativeInvestigator(decisions),
        synthesizer=synthesis,
    )
    with pytest.raises(RuntimeError) as caught:
        app.investigate(path, "Investigate", max_steps=2)
    assert caught.value is error
    synthesis.synthesize.assert_not_called()


def test_failure_metadata_handles_nested_and_cyclic_causes() -> None:
    provider = GeminiTransientError(SECRET)
    middle = ValueError(SECRET)
    middle.__cause__ = provider
    outer = QueryPlanningError(SECRET)
    outer.__cause__ = middle
    assert InvestigationFailure.from_exception("query_execution", outer) == (
        InvestigationFailure("query_execution", "provider_unavailable")
    )
    middle.__cause__ = outer
    failure = InvestigationFailure.from_exception("query_execution", outer)
    assert failure == InvestigationFailure("query_execution", "query_planning_error")
    assert SECRET not in json.dumps(to_jsonable(failure))


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM measurements private_alias "
        "JOIN measurements private_alias ON true",
        "SELECT * FROM (SELECT 1 AS value) private_alias "
        "JOIN (SELECT 2 AS value) private_alias ON true",
        "WITH x AS (SELECT * FROM measurements) "
        "SELECT * FROM x private_alias JOIN x private_alias ON true",
    ],
    ids=["tables", "subqueries", "cte"],
)
def test_duplicate_aliases_have_a_safe_public_validation_error(
    tmp_path: Path, sql: str
) -> None:
    path = tmp_path / "measurements.csv"
    path.write_text("value\n10\n20\n", encoding="utf-8")
    app = VeriSight(settings=Settings(allow_llm_data_disclosure=False))

    with pytest.raises(QueryValidationError) as caught:
        app.execute(path, sql)

    assert isinstance(caught.value.__cause__, OptimizeError)
    assert str(caught.value) == "Dataset access is not allowed: SQL analysis failed."
    assert "private_alias" not in str(caught.value)
    public = run_public_operation(lambda: app.execute(path, sql))
    assert public.succeeded is False
    assert public.value is None
    assert public.error is not None
    assert public.error.code is ErrorCode.QUERY_VALIDATION_ERROR
    assert "private_alias" not in json.dumps(to_jsonable(public))
    valid = app.execute(
        path,
        "SELECT SUM(a.value) AS total FROM measurements a "
        "JOIN measurements b ON a.value = b.value",
    )
    assert valid.rows == ((30,),)


@pytest.mark.parametrize("recover", [False, True])
def test_duplicate_alias_failure_preserves_evidence_and_allows_recovery(
    tmp_path: Path, recover: bool
) -> None:
    path = tmp_path / "measurements.csv"
    path.write_text("value\n10\n20\n", encoding="utf-8")
    third = json.dumps(
        {
            "action": "investigate",
            "reasoning": "Use distinct aliases",
            "question": "Retry",
        }
    )
    finish = json.dumps(
        {"action": "finish", "reasoning": "Evidence collected", "question": None}
    )
    decisions = Mock()
    decisions.generate.side_effect = [FIRST, SECOND, third, finish]
    planning = Mock()
    valid_join = (
        "SELECT SUM(a.value) AS total FROM measurements a "
        "JOIN measurements b ON a.value = b.value"
    )
    planning.generate.side_effect = [
        SQL,
        "SELECT * FROM measurements a JOIN measurements a ON true",
        valid_join,
    ]
    repair = Mock()
    synthesis = Mock()
    synthesis.synthesize.return_value = "The queries produced matching totals."
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False),
        planner=GenerativeQueryPlanner(planning),
        repairer=GenerativeQueryRepairer(repair),
        investigator=GenerativeInvestigator(decisions),
        synthesizer=synthesis,
    )

    public = run_public_operation(
        lambda: app.investigate(path, "Compare totals", max_steps=2 + int(recover))
    )

    assert public.succeeded is True
    result = public.value
    assert result is not None
    assert result.status is (
        InvestigationStatus.COMPLETE if recover else InvestigationStatus.INCOMPLETE
    )
    assert result.observation_count == 1 + int(recover)
    assert result.observations[0].sql == SQL
    assert result.observations[0].result.rows == ((30,),)
    assert len(result.failed_attempts) == 1
    failure = result.failed_attempts[0]
    assert failure.question == "Compare"
    assert failure.error_type == "QueryValidationError"
    assert failure.repair_history == ()
    assert result.investigation_failure is None
    assert planning.generate.call_count == 2 + int(recover)
    repair.generate.assert_not_called()
    serialized = json.loads(json.dumps(to_jsonable(result)))
    assert serialized["failed_attempts"][0]["error_type"] == "QueryValidationError"
    if recover:
        assert result.observations[1].sql == valid_join
        assert result.observations[1].result.rows == ((30,),)
        synthesis.synthesize.assert_called_once()
    else:
        synthesis.synthesize.assert_not_called()
