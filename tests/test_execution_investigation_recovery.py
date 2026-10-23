"""Regression tests for investigation recovery and incomplete evidence."""

from typing import cast
from unittest.mock import MagicMock, patch

import pytest

from verisight.analysis.result import DatasetAnalysisResult
from verisight.execution.decisions import InvestigationAction
from verisight.execution.generative_investigator import (
    GenerativeInvestigator,
)
from verisight.execution.incomplete_evidence import IncompleteEvidenceError
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_result import InvestigationStatus
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation
from verisight.execution.orchestration import InvestigationOrchestrator
from verisight.execution.prompt_budget import PromptBudgetExceededError


def _analysis() -> DatasetAnalysisResult:
    """Build a minimal analysis fixture."""

    analysis = MagicMock(spec=DatasetAnalysisResult)

    analysis.summary.table_count = 0
    analysis.summary.total_row_count = 0
    analysis.summary.total_column_count = 0
    analysis.summary.issue_count = 0
    analysis.summary.info_issue_count = 0
    analysis.summary.warning_issue_count = 0
    analysis.summary.error_issue_count = 0

    analysis.insights = ()
    analysis.analysis.issues = ()
    analysis.analysis.schema.tables = ()

    return cast(DatasetAnalysisResult, analysis)


def _state() -> InvestigationState:
    """Build a minimal investigation state."""

    return InvestigationState(
        question="Investigate revenue.",
        analysis=_analysis(),
    )


class RecordingClient:
    """Return deterministic generation responses and record prompts."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def _budget_error() -> PromptBudgetExceededError:
    """Build a representative prompt-budget exception."""

    return PromptBudgetExceededError(
        max_prompt_chars=100,
        actual_prompt_chars=101,
    )


def test_investigator_recovers_from_prompt_budget_overflow() -> None:
    """A compact prompt allows the investigator to request more evidence."""

    client = RecordingClient(
        '{"action":"investigate",'
        '"reasoning":"More evidence is needed.",'
        '"question":"Calculate revenue."}'
    )

    investigator = GenerativeInvestigator(client)

    with (
        patch.object(
            investigator._prompt_builder,
            "build",
            side_effect=_budget_error(),
        ),
        patch.object(
            investigator._compaction,
            "investigator_prompt",
            return_value="COMPACTED INVESTIGATION PROMPT",
        ),
    ):
        decision = investigator.decide(_state())

    assert decision.action is InvestigationAction.INVESTIGATE
    assert decision.question == "Calculate revenue."
    assert client.prompts == ["COMPACTED INVESTIGATION PROMPT"]


def test_investigator_rejects_finish_with_compacted_context() -> None:
    """Compacted evidence must not support an unverified FINISH decision."""

    client = RecordingClient(
        '{"action":"finish","reasoning":"Enough evidence.","question":null}'
    )

    investigator = GenerativeInvestigator(client)

    with (
        patch.object(
            investigator._prompt_builder,
            "build",
            side_effect=_budget_error(),
        ),
        patch.object(
            investigator._compaction,
            "investigator_prompt",
            return_value="COMPACTED INVESTIGATION PROMPT",
        ),
        pytest.raises(
            IncompleteEvidenceError,
            match="compacted evidence",
        ),
    ):
        investigator.decide(_state())

    assert client.prompts == ["COMPACTED INVESTIGATION PROMPT"]


def test_investigator_uses_normal_prompt_when_budget_fits() -> None:
    """Normal investigation prompts do not trigger compaction."""

    client = RecordingClient(
        '{"action":"finish",'
        '"reasoning":"No additional query is needed.",'
        '"question":null}'
    )

    investigator = GenerativeInvestigator(client)

    with patch.object(
        investigator._compaction,
        "investigator_prompt",
    ) as compact_prompt:
        decision = investigator.decide(_state())

    assert decision.action is InvestigationAction.FINISH
    assert len(client.prompts) == 1
    compact_prompt.assert_not_called()


def test_compaction_failure_preserves_typed_budget_error() -> None:
    """An impossible compact prompt budget propagates safely."""

    client = RecordingClient('{"action":"finish","reasoning":"Done.","question":null}')

    investigator = GenerativeInvestigator(client)

    with (
        patch.object(
            investigator._prompt_builder,
            "build",
            side_effect=_budget_error(),
        ),
        patch.object(
            investigator._compaction,
            "investigator_prompt",
            side_effect=_budget_error(),
        ),
        pytest.raises(PromptBudgetExceededError),
    ):
        investigator.decide(_state())

    assert client.prompts == []


@pytest.mark.parametrize(
    "failure",
    [
        PromptBudgetExceededError(
            max_prompt_chars=100,
            actual_prompt_chars=101,
        ),
        IncompleteEvidenceError("Full evidence unavailable."),
    ],
)
def test_orchestrator_preserves_incomplete_investigator_result(
    failure: Exception,
) -> None:
    """Investigator evidence failures produce explicit incomplete results."""

    execution_service = MagicMock()
    investigator = MagicMock()
    synthesizer = MagicMock()

    investigator.decide.side_effect = failure

    orchestrator = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
    )

    result = orchestrator.investigate(
        question="Investigate revenue.",
        analysis=_analysis(),
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observations == ()
    assert "No analytical conclusion has been established." in result.conclusion

    execution_service.run.assert_not_called()
    synthesizer.synthesize.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        PromptBudgetExceededError(
            max_prompt_chars=100,
            actual_prompt_chars=101,
        ),
        IncompleteEvidenceError("Full evidence unavailable."),
    ],
)
def test_orchestrator_preserves_incomplete_synthesis_result(
    failure: Exception,
) -> None:
    """Synthesis evidence failures produce explicit incomplete results."""

    execution_service = MagicMock()
    investigator = MagicMock()
    synthesizer = MagicMock()

    investigator.decide.side_effect = [
        MagicMock(
            action=InvestigationAction.INVESTIGATE,
            question="Count the records.",
        ),
        MagicMock(
            action=InvestigationAction.FINISH,
        ),
    ]

    execution_service.run.return_value.plan.question = "Count the records."
    execution_service.run.return_value.plan.sql = "SELECT COUNT(*) FROM records"

    synthesizer.synthesize.side_effect = failure

    orchestrator = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
    )

    result = orchestrator.investigate(
        question="Investigate revenue.",
        analysis=_analysis(),
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == 1
    assert result.observations[0].question == "Count the records."
    assert "No analytical conclusion has been established." in result.conclusion

    execution_service.run.assert_called_once_with(
        "Count the records.", original_question="Investigate revenue."
    )
    assert investigator.decide.call_count == 2
    synthesizer.synthesize.assert_called_once()


@pytest.mark.parametrize(
    "failure",
    [
        PromptBudgetExceededError(
            max_prompt_chars=100,
            actual_prompt_chars=101,
        ),
        IncompleteEvidenceError("Full evidence unavailable."),
    ],
)
def test_orchestrator_preserves_executed_observation_on_investigator_failure(
    failure: Exception,
) -> None:
    """Preserve successful SQL evidence when a later decision fails."""

    execution_service = MagicMock()
    investigator = MagicMock()
    synthesizer = MagicMock()

    investigator.decide.side_effect = [
        MagicMock(
            action=InvestigationAction.INVESTIGATE,
            question="Calculate total revenue.",
        ),
        failure,
    ]

    execution_service.run.return_value.plan.question = "Calculate total revenue."
    execution_service.run.return_value.plan.sql = (
        "SELECT SUM(revenue) AS total_revenue FROM sales"
    )

    expected_result = QueryResult(
        columns=("total_revenue",),
        rows=((1500,),),
    )
    execution_service.run.return_value.result = expected_result

    orchestrator = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
    )

    result = orchestrator.investigate(
        question="Investigate revenue.",
        analysis=_analysis(),
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.question == "Investigate revenue."
    assert result.observations == (
        QueryObservation(
            question="Calculate total revenue.",
            sql="SELECT SUM(revenue) AS total_revenue FROM sales",
            result=expected_result,
        ),
    )
    assert "No analytical conclusion has been established." in result.conclusion

    assert investigator.decide.call_count == 2
    execution_service.run.assert_called_once_with(
        "Calculate total revenue.", original_question="Investigate revenue."
    )
    synthesizer.synthesize.assert_not_called()


@pytest.mark.parametrize(
    "failure",
    [
        PromptBudgetExceededError(
            max_prompt_chars=100,
            actual_prompt_chars=101,
        ),
        IncompleteEvidenceError("Full evidence unavailable."),
    ],
)
def test_orchestrator_preserves_executed_observation_on_synthesis_failure(
    failure: Exception,
) -> None:
    """Preserve successful SQL evidence when final synthesis fails."""

    execution_service = MagicMock()
    investigator = MagicMock()
    synthesizer = MagicMock()

    investigator.decide.side_effect = [
        MagicMock(
            action=InvestigationAction.INVESTIGATE,
            question="Calculate total revenue.",
        ),
        MagicMock(action=InvestigationAction.FINISH),
    ]

    execution_service.run.return_value.plan.question = "Calculate total revenue."
    execution_service.run.return_value.plan.sql = (
        "SELECT SUM(revenue) AS total_revenue FROM sales"
    )

    expected_result = QueryResult(
        columns=("total_revenue",),
        rows=((1500,),),
    )
    execution_service.run.return_value.result = expected_result

    synthesizer.synthesize.side_effect = failure

    orchestrator = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
    )

    result = orchestrator.investigate(
        question="Investigate revenue.",
        analysis=_analysis(),
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.question == "Investigate revenue."
    assert result.observations == (
        QueryObservation(
            question="Calculate total revenue.",
            sql="SELECT SUM(revenue) AS total_revenue FROM sales",
            result=expected_result,
        ),
    )
    assert "No analytical conclusion has been established." in result.conclusion

    assert investigator.decide.call_count == 2
    execution_service.run.assert_called_once_with(
        "Calculate total revenue.", original_question="Investigate revenue."
    )
    synthesizer.synthesize.assert_called_once()
