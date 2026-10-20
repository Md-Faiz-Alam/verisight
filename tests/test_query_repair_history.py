"""Returned query provenance separates repairs and failures from evidence."""

import json
from pathlib import Path

import pandas as pd
import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder, DatasetAnalysisResult
from verisight.error_reporting import to_public_error
from verisight.execution.decisions import InvestigationAction, InvestigationDecision
from verisight.execution.exceptions import (
    InvestigationError,
    QueryPlanningError,
    QueryRuntimeError,
    QueryValidationError,
)
from verisight.execution.execution import (
    QueryRepairAttempt,
    capture_query_repairs,
    record_query_repair,
)
from verisight.execution.gemini import GeminiTransientError
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_result import InvestigationStatus
from verisight.execution.orchestration import InvestigationOrchestrator
from verisight.execution.planning import QueryPlan, QueryRequest
from verisight.execution.prompt_budget import PromptBudgetExceededError
from verisight.execution.repair import QueryRepairRequest
from verisight.execution.service import AnalyticalExecutionService
from verisight.ingestion.models import LoadedDataset, LoadedTable, SourceMetadata
from verisight.ingestion.schema import SchemaInferer
from verisight.profiling.models import DatasetProfile
from verisight.serialization import to_jsonable

GOOD_SQL = "SELECT SUM(value) AS metric FROM measurements"
FAILED_SQL = "SELECT missing_metric FROM measurements"
REPAIR_SQL = "SELECT still_missing FROM measurements"


def _dataset() -> LoadedDataset:
    return LoadedDataset(
        tables=[
            LoadedTable(
                name="measurements",
                data=pd.DataFrame({"value": [10, 20]}),
                source=SourceMetadata(
                    path=Path("synthetic.csv"),
                    file_name="synthetic.csv",
                    file_extension=".csv",
                    file_size_bytes=1,
                ),
            )
        ]
    )


def _analysis(dataset: LoadedDataset) -> DatasetAnalysisResult:
    return AnalysisResultBuilder().build(
        DatasetAnalysis(
            schema=SchemaInferer().infer_dataset(dataset),
            profile=DatasetProfile(tables=()),
            issues=(),
        )
    )


class Planner:
    def plan(self, request: QueryRequest) -> QueryPlan:
        return QueryPlan(
            request.question, GOOD_SQL if request.question == "good" else FAILED_SQL
        )


class Repairer:
    def repair(self, request: QueryRepairRequest) -> QueryPlan:
        if request.question == "provider":
            raise GeminiTransientError("private-provider-message")
        return QueryPlan(
            request.question, REPAIR_SQL if request.question == "bad" else GOOD_SQL
        )


class Investigator:
    def __init__(self, questions: tuple[str, ...]) -> None:
        self.questions = questions

    def decide(self, state: InvestigationState) -> InvestigationDecision:
        index = state.observation_count + state.failed_attempt_count
        if index == len(self.questions):
            return InvestigationDecision(
                InvestigationAction.FINISH, "Evidence reviewed."
            )
        return InvestigationDecision(
            InvestigationAction.INVESTIGATE, "Collect evidence.", self.questions[index]
        )


class Synthesizer:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def synthesize(self, state: InvestigationState) -> str:
        if self.fail:
            raise InvestigationError("private-synthesis-message")
        return "Evidence collected."


def test_successful_repair_returns_both_plans_and_final_result() -> None:
    service = AnalyticalExecutionService(
        _dataset(), planner=Planner(), repairer=Repairer()
    )
    with capture_query_repairs() as captured:
        execution = service.run("repair")
    assert execution.result.rows == ((30,),)
    assert execution.plan == QueryPlan("repair", GOOD_SQL)
    assert tuple(captured) == execution.repair_history
    assert execution.repair_history == (
        QueryRepairAttempt(
            QueryPlan("repair", FAILED_SQL), QueryPlan("repair", GOOD_SQL), "succeeded"
        ),
    )
    assert (
        json.loads(json.dumps(to_jsonable(execution)))["repair_history"][0]["outcome"]
        == "succeeded"
    )
    assert service.run("good").repair_history == ()
    assert service.ask("good").rows == ((30,),)


@pytest.mark.parametrize(
    ("replacement", "error_type", "code"),
    [
        pytest.param(
            REPAIR_SQL, QueryRuntimeError, "query_runtime_error", id="runtime"
        ),
        pytest.param(
            "DELETE FROM measurements",
            QueryValidationError,
            "query_validation_error",
            id="validation",
        ),
        pytest.param("", QueryPlanningError, "query_planning_error", id="empty-plan"),
    ],
)
def test_unsuccessful_replacement_retains_attempt_without_becoming_evidence(
    replacement: str, error_type: type[Exception], code: str
) -> None:
    class BadRepairer:
        def repair(self, request: QueryRepairRequest) -> QueryPlan:
            return QueryPlan(request.question, replacement)

    service = AnalyticalExecutionService(
        _dataset(), planner=Planner(), repairer=BadRepairer()
    )
    with capture_query_repairs() as captured, pytest.raises(error_type):
        service.run("repair")
    assert captured == [
        QueryRepairAttempt(
            QueryPlan("repair", FAILED_SQL),
            QueryPlan("repair", replacement),
            "failed",
            code,
        )
    ]
    assert service.execute("SELECT COUNT(*) FROM measurements").rows == ((2,),)


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(QueryPlanningError("private-planning-message"), id="planning"),
        pytest.param(GeminiTransientError("private-provider-message"), id="provider"),
        pytest.param(
            PromptBudgetExceededError(max_prompt_chars=1, actual_prompt_chars=2),
            id="budget",
        ),
    ],
)
def test_repair_generation_failure_keeps_original_exception_and_safe_record(
    error: Exception,
) -> None:
    class FailingRepairer:
        def repair(self, request: QueryRepairRequest) -> QueryPlan:
            raise error

    service = AnalyticalExecutionService(
        _dataset(), planner=Planner(), repairer=FailingRepairer()
    )
    with capture_query_repairs() as captured, pytest.raises(type(error)) as caught:
        service.run("repair")
    assert caught.value is error
    assert captured == [
        QueryRepairAttempt(
            QueryPlan("repair", FAILED_SQL),
            None,
            "failed",
            to_public_error(error).code.value,
        )
    ]
    assert "private-" not in json.dumps(to_jsonable(captured))


@pytest.mark.parametrize(
    ("questions", "max_steps", "synthesis_fails", "status", "observations", "failures"),
    [
        pytest.param(("bad", "repair"), 2, False, "complete", 1, 1, id="recovered"),
        pytest.param(("bad",), 1, False, "incomplete", 0, 1, id="all-failed"),
        pytest.param(("bad", "repair"), 1, False, "incomplete", 0, 1, id="step-budget"),
        pytest.param(("bad", "repair"), 2, True, "incomplete", 1, 1, id="synthesis"),
        pytest.param(
            ("repair", "provider"), 2, False, "incomplete", 1, 1, id="provider"
        ),
        pytest.param(("good",), 1, False, "complete", 1, 0, id="no-repair"),
    ],
)
def test_investigation_returns_failure_and_repair_history(
    questions: tuple[str, ...],
    max_steps: int,
    synthesis_fails: bool,
    status: str,
    observations: int,
    failures: int,
) -> None:
    dataset = _dataset()
    result = InvestigationOrchestrator(
        execution_service=AnalyticalExecutionService(
            dataset, planner=Planner(), repairer=Repairer()
        ),
        investigator=Investigator(questions),
        synthesizer=Synthesizer(synthesis_fails),
        max_steps=max_steps,
    ).investigate(question="Review measurements.", analysis=_analysis(dataset))
    assert result.status is InvestigationStatus(status)
    assert result.observation_count == observations
    assert result.failed_attempt_count == failures
    for failed in result.failed_attempts:
        assert len(failed.repair_history) == 1
        assert failed.repair_history[0].outcome == "failed"
        assert failed.repair_history[0].failed_plan.sql == FAILED_SQL
    for observation in result.observations:
        assert observation.sql == GOOD_SQL
        assert observation.result.rows == ((30,),)
        if observation.question == "repair":
            assert len(observation.repair_history) == 1
            assert observation.repair_history[0].outcome == "succeeded"
        else:
            assert observation.repair_history == ()
    payload = json.loads(json.dumps(to_jsonable(result)))
    assert len(payload["failed_attempts"]) == failures
    assert "private-" not in json.dumps(payload)
    if questions[-1] == "provider":
        assert result.investigation_failure is not None
        assert result.investigation_failure.kind == "provider_unavailable"
        assert result.failed_attempts[-1].repair_history[0].replacement_plan is None


def test_nested_capture_and_exception_cleanup_do_not_leak_history() -> None:
    attempt = QueryRepairAttempt(QueryPlan("q", FAILED_SQL), None, "failed", "x")
    record_query_repair(attempt)
    with capture_query_repairs() as outer:
        record_query_repair(attempt)
        with pytest.raises(RuntimeError), capture_query_repairs() as inner:
            record_query_repair(attempt)
            raise RuntimeError("programming failure")
        record_query_repair(attempt)
    record_query_repair(attempt)
    assert outer == [attempt, attempt]
    assert inner == [attempt]
    with capture_query_repairs() as fresh:
        assert fresh == []
