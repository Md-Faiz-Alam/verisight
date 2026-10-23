"""Tests for autonomous investigation orchestration."""

import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import (
    AnalysisResultBuilder,
    DatasetAnalysisResult,
)
from verisight.error_reporting import to_public_error
from verisight.execution.decisions import (
    InvestigationAction,
    InvestigationDecision,
)
from verisight.execution.exceptions import (
    InvestigationError,
    QueryExecutionError,
    QueryPlanningError,
    QueryResultLimitError,
    QueryRuntimeError,
    QueryTimeoutError,
    QueryValidationError,
)
from verisight.execution.execution import QueryExecution
from verisight.execution.gemini import GeminiGenerationError
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_result import (
    InvestigationResult,
    InvestigationStatus,
)
from verisight.execution.models import QueryResult
from verisight.execution.orchestration import InvestigationOrchestrator
from verisight.execution.planning import QueryPlan
from verisight.execution.prompt_budget import PromptBudgetExceededError
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile


class StubInvestigator:
    """Deterministic investigator for orchestration tests."""

    def __init__(
        self,
        decisions: list[InvestigationDecision],
    ) -> None:
        self._decisions = decisions
        self.states: list[InvestigationState] = []

    def decide(
        self,
        state: InvestigationState,
    ) -> InvestigationDecision:
        self.states.append(state)
        return self._decisions[len(self.states) - 1]


class StubExecutionService:
    """Deterministic analytical execution service."""

    def __init__(self) -> None:
        self.run_questions: list[str] = []

    def run(
        self, question: str, *, original_question: str | None = None
    ) -> QueryExecution:
        self.run_questions.append(question)

        return QueryExecution(
            plan=QueryPlan(
                question=question,
                sql="SELECT 100 AS revenue",
            ),
            result=QueryResult(
                columns=("revenue",),
                rows=((100,),),
            ),
        )


class FailingExecutionService(StubExecutionService):
    """Execution service with configurable failures."""

    def __init__(
        self,
        failures: dict[str, Exception],
    ) -> None:
        super().__init__()
        self._failures = failures

    def run(
        self, question: str, *, original_question: str | None = None
    ) -> QueryExecution:
        if question in self._failures:
            self.run_questions.append(question)
            raise self._failures[question]

        return super().run(question, original_question=original_question)


class StubInvestigationSynthesizer:
    """Deterministic investigation synthesizer."""

    def __init__(
        self,
        conclusion: str = "Synthesized analytical conclusion.",
    ) -> None:
        self.conclusion = conclusion
        self.states: list[InvestigationState] = []

    def synthesize(
        self,
        state: InvestigationState,
    ) -> str:
        self.states.append(state)
        return self.conclusion


def _build_analysis_result() -> DatasetAnalysisResult:
    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(),
    )
    return AnalysisResultBuilder().build(analysis)


def _investigate(question: str) -> InvestigationDecision:
    return InvestigationDecision(
        action=InvestigationAction.INVESTIGATE,
        reasoning="Additional analytical evidence is required.",
        question=question,
    )


def _finish() -> InvestigationDecision:
    return InvestigationDecision(
        action=InvestigationAction.FINISH,
        reasoning="The available evidence is sufficient.",
    )


def _build_orchestrator(
    *,
    investigator: StubInvestigator,
    execution_service: StubExecutionService,
    synthesizer: StubInvestigationSynthesizer,
    max_steps: int = 5,
) -> InvestigationOrchestrator:
    return InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
        max_steps=max_steps,
    )


def test_investigation_finishes_without_querying() -> None:
    investigator = StubInvestigator([_finish()])
    execution_service = StubExecutionService()
    synthesizer = StubInvestigationSynthesizer(
        conclusion="The existing evidence supports the final conclusion."
    )

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=synthesizer,
    ).investigate(
        question="Why did revenue decline?",
        analysis=_build_analysis_result(),
    )

    assert isinstance(result, InvestigationResult)
    assert result.question == "Why did revenue decline?"
    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.conclusion == (
        "Investigation incomplete: no analytical observations were collected. "
        "No analytical conclusion has been established."
    )
    assert result.observations == ()
    assert result.observation_count == 0
    assert execution_service.run_questions == []
    assert len(investigator.states) == 1
    assert synthesizer.states == []


def test_investigation_executes_requested_observation() -> None:
    investigator = StubInvestigator(
        [
            _investigate("What is revenue by month?"),
            _finish(),
        ]
    )
    execution_service = StubExecutionService()
    synthesizer = StubInvestigationSynthesizer(
        conclusion="Revenue changed across the observed period."
    )

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=synthesizer,
    ).investigate(
        question="Why did revenue decline?",
        analysis=_build_analysis_result(),
    )

    assert result.conclusion == "Revenue changed across the observed period."
    assert result.observation_count == 1

    observation = result.observations[0]
    assert observation.question == "What is revenue by month?"
    assert observation.sql == "SELECT 100 AS revenue"
    assert observation.result == QueryResult(
        columns=("revenue",),
        rows=((100,),),
    )
    assert execution_service.run_questions == ["What is revenue by month?"]
    assert synthesizer.states[0].observations[0] == observation


def test_investigator_receives_updated_state() -> None:
    investigator = StubInvestigator(
        [
            _investigate("What is revenue by month?"),
            _finish(),
        ]
    )
    synthesizer = StubInvestigationSynthesizer()

    _build_orchestrator(
        investigator=investigator,
        execution_service=StubExecutionService(),
        synthesizer=synthesizer,
    ).investigate(
        question="Why did revenue decline?",
        analysis=_build_analysis_result(),
    )

    assert len(investigator.states) == 2
    assert investigator.states[0].observation_count == 0
    assert investigator.states[1].observation_count == 1
    assert synthesizer.states[0].observation_count == 1


def test_investigation_can_execute_multiple_observations() -> None:
    investigator = StubInvestigator(
        [
            _investigate("What is revenue by month?"),
            _investigate("What is revenue by customer?"),
            _finish(),
        ]
    )
    execution_service = StubExecutionService()
    synthesizer = StubInvestigationSynthesizer()

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=synthesizer,
    ).investigate(
        question="Why did revenue decline?",
        analysis=_build_analysis_result(),
    )

    assert result.observation_count == 2
    assert execution_service.run_questions == [
        "What is revenue by month?",
        "What is revenue by customer?",
    ]
    assert synthesizer.states[0].observation_count == 2


def test_investigation_result_preserves_analysis() -> None:
    analysis = _build_analysis_result()
    synthesizer = StubInvestigationSynthesizer()

    result = _build_orchestrator(
        investigator=StubInvestigator([_finish()]),
        execution_service=StubExecutionService(),
        synthesizer=synthesizer,
    ).investigate(
        question="Inspect the dataset.",
        analysis=analysis,
    )

    assert result.analysis is analysis
    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == 0
    assert result.observations == ()
    assert synthesizer.states == []


def test_finish_reasoning_is_not_used_as_conclusion() -> None:
    synthesizer = StubInvestigationSynthesizer(
        conclusion="Revenue declined in the observed data."
    )

    result = _build_orchestrator(
        investigator=StubInvestigator(
            [
                _investigate("What is revenue by month?"),
                _finish(),
            ]
        ),
        execution_service=StubExecutionService(),
        synthesizer=synthesizer,
    ).investigate(
        question="Why did revenue decline?",
        analysis=_build_analysis_result(),
    )

    assert result.status is InvestigationStatus.COMPLETE
    assert result.observation_count == 1
    assert result.conclusion == "Revenue declined in the observed data."
    assert result.conclusion != "The available evidence is sufficient."
    assert len(synthesizer.states) == 1


def test_synthesizer_is_called_only_after_finish() -> None:
    investigator = StubInvestigator(
        [
            _investigate("What is revenue by month?"),
            _finish(),
        ]
    )
    synthesizer = StubInvestigationSynthesizer()

    orchestrator = _build_orchestrator(
        investigator=investigator,
        execution_service=StubExecutionService(),
        synthesizer=synthesizer,
    )

    assert synthesizer.states == []

    result = orchestrator.investigate(
        question="Why did revenue decline?",
        analysis=_build_analysis_result(),
    )

    assert result.observation_count == 1
    assert len(synthesizer.states) == 1
    assert synthesizer.states[0].observation_count == 1


def test_investigation_rejects_empty_question() -> None:
    investigator = StubInvestigator([])
    synthesizer = StubInvestigationSynthesizer()

    orchestrator = _build_orchestrator(
        investigator=investigator,
        execution_service=StubExecutionService(),
        synthesizer=synthesizer,
    )

    with pytest.raises(
        InvestigationError,
        match="Investigation question must not be empty.",
    ):
        orchestrator.investigate(
            question=" ",
            analysis=_build_analysis_result(),
        )

    assert investigator.states == []
    assert synthesizer.states == []


def test_investigation_rejects_non_positive_max_steps() -> None:
    with pytest.raises(
        ValueError,
        match="Maximum investigation steps must be positive.",
    ):
        _build_orchestrator(
            investigator=StubInvestigator([]),
            execution_service=StubExecutionService(),
            synthesizer=StubInvestigationSynthesizer(),
            max_steps=0,
        )


def test_investigation_stops_at_maximum_steps() -> None:
    investigator = StubInvestigator(
        [
            _investigate("What is revenue by month?"),
            _investigate("What is revenue by customer?"),
            _investigate("What is revenue by region?"),
        ]
    )
    execution_service = StubExecutionService()
    synthesizer = StubInvestigationSynthesizer()

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=synthesizer,
        max_steps=2,
    ).investigate(
        question="Why did revenue decline?",
        analysis=_build_analysis_result(),
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert "maximum number of analytical steps" in result.conclusion
    assert result.observation_count == 2
    assert execution_service.run_questions == [
        "What is revenue by month?",
        "What is revenue by customer?",
    ]
    assert len(investigator.states) == 3
    assert synthesizer.states == []


def test_investigation_rejects_repeated_question() -> None:
    question = "What is revenue by month?"
    investigator = StubInvestigator(
        [
            _investigate(question),
            _investigate(question),
        ]
    )
    execution_service = StubExecutionService()
    synthesizer = StubInvestigationSynthesizer()

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=synthesizer,
    ).investigate(
        question="Why did revenue decline?",
        analysis=_build_analysis_result(),
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert "repeated an analytical question" in result.conclusion
    assert result.observation_count == 1
    assert execution_service.run_questions == [question]
    assert synthesizer.states == []


def test_repeated_question_detection_is_normalized() -> None:
    investigator = StubInvestigator(
        [
            _investigate("What is revenue by month?"),
            _investigate("  what   is REVENUE by month?  "),
        ]
    )
    execution_service = StubExecutionService()

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=StubInvestigationSynthesizer(),
    ).investigate(
        question="Why did revenue decline?",
        analysis=_build_analysis_result(),
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == 1
    assert execution_service.run_questions == ["What is revenue by month?"]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("What is revenue by month?", "what is revenue by month?"),
        (
            "  What   is   revenue   by month?  ",
            "what is revenue by month?",
        ),
        (
            "\nWHAT IS REVENUE BY MONTH?\t",
            "what is revenue by month?",
        ),
    ],
)
def test_normalizes_investigation_question(
    question: str,
    expected: str,
) -> None:
    assert InvestigationOrchestrator._normalize_question(question) == expected


def test_investigation_rejects_investigate_decision_without_question() -> None:
    malformed_decision = object.__new__(InvestigationDecision)

    object.__setattr__(
        malformed_decision,
        "action",
        InvestigationAction.INVESTIGATE,
    )
    object.__setattr__(
        malformed_decision,
        "reasoning",
        "More evidence is required.",
    )
    object.__setattr__(
        malformed_decision,
        "question",
        None,
    )

    investigator = StubInvestigator([malformed_decision])
    execution_service = StubExecutionService()
    synthesizer = StubInvestigationSynthesizer()

    with pytest.raises(
        InvestigationError,
        match="Investigator did not provide an analytical question.",
    ):
        _build_orchestrator(
            investigator=investigator,
            execution_service=execution_service,
            synthesizer=synthesizer,
        ).investigate(
            question="Why did revenue decline?",
            analysis=_build_analysis_result(),
        )

    assert execution_service.run_questions == []
    assert synthesizer.states == []


def test_investigation_preserves_executed_plan_provenance() -> None:
    class RepairedExecutionService:
        def __init__(self) -> None:
            self.run_questions: list[str] = []

        def run(
            self, question: str, *, original_question: str | None = None
        ) -> QueryExecution:
            self.run_questions.append(question)

            return QueryExecution(
                plan=QueryPlan(
                    question=question,
                    sql="SELECT AVG(score) AS average_score FROM assessments",
                ),
                result=QueryResult(
                    columns=("average_score",),
                    rows=((84.5,),),
                ),
            )

    investigator = StubInvestigator(
        [
            _investigate("What is the average assessment score?"),
            _finish(),
        ]
    )
    execution_service = RepairedExecutionService()
    synthesizer = StubInvestigationSynthesizer()

    result = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
    ).investigate(
        question="Investigate assessment performance.",
        analysis=_build_analysis_result(),
    )

    assert execution_service.run_questions == ["What is the average assessment score?"]
    assert result.observation_count == 1

    observation = result.observations[0]

    assert observation.question == "What is the average assessment score?"
    assert observation.sql == ("SELECT AVG(score) AS average_score FROM assessments")
    assert observation.result == QueryResult(
        columns=("average_score",),
        rows=((84.5,),),
    )


@pytest.mark.parametrize(
    "error",
    [
        QueryExecutionError("Analytical execution failed."),
        QueryRuntimeError("Query execution failed."),
        QueryResultLimitError("Result exceeded the row limit."),
        QueryTimeoutError("Query exceeded the timeout."),
        QueryPlanningError("Query planning failed."),
    ],
)
def test_investigation_recovers_from_query_failure(
    error: Exception,
) -> None:
    failed_question = "Calculate the unavailable measure."
    successful_question = "Count the available records."

    investigator = StubInvestigator(
        [
            _investigate(failed_question),
            _investigate(successful_question),
            _finish(),
        ]
    )
    execution_service = FailingExecutionService(failures={failed_question: error})
    synthesizer = StubInvestigationSynthesizer()

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=synthesizer,
    ).investigate(
        question="Investigate the dataset.",
        analysis=_build_analysis_result(),
    )

    assert result.observation_count == 1
    assert result.observations[0].question == successful_question
    assert execution_service.run_questions == [
        failed_question,
        successful_question,
    ]
    assert len(investigator.states) == 3

    failed_state = investigator.states[1]

    assert failed_state.observation_count == 0
    assert failed_state.failed_attempt_count == 1
    assert failed_state.failed_attempts[0].question == failed_question
    assert failed_state.failed_attempts[0].error_type == type(error).__name__
    assert failed_state.failed_attempts[0].message == to_public_error(error).message

    final_state = synthesizer.states[0]

    assert final_state.observation_count == 1
    assert final_state.failed_attempt_count == 1


def test_failed_query_diagnostics_do_not_reach_investigation_state() -> None:
    """Sensitive SQL diagnostics must not enter investigation state."""

    question = "Calculate the unavailable measure."
    secret = "super-secret-database-token"
    raw_sql = "SELECT private_salary FROM confidential_payroll"

    error = QueryRuntimeError(f"Query failed for {raw_sql}; credential={secret}")
    error.__cause__ = ValueError(f"Provider secret: {secret}")

    investigator = StubInvestigator(
        [
            _investigate(question),
            _finish(),
        ]
    )

    execution_service = FailingExecutionService(failures={question: error})
    synthesizer = StubInvestigationSynthesizer()

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=synthesizer,
    ).investigate(
        question="Investigate the dataset.",
        analysis=_build_analysis_result(),
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == 0
    assert execution_service.run_questions == [question]
    assert len(investigator.states) == 2

    failed_attempt = investigator.states[1].failed_attempts[0]

    assert failed_attempt.question == question
    assert failed_attempt.error_type == "QueryRuntimeError"
    assert failed_attempt.message == to_public_error(error).message

    assert raw_sql not in failed_attempt.message
    assert secret not in failed_attempt.message
    assert str(error) not in failed_attempt.message

    assert error.__cause__ is not None
    assert secret in str(error.__cause__)

    assert synthesizer.states == []


def test_investigation_rejects_query_validation_error() -> None:
    question = "Inspect the dataset using prohibited SQL."
    corrected_question = "Count available records."

    investigator = StubInvestigator(
        [
            _investigate(question),
            _investigate(corrected_question),
            _finish(),
        ]
    )
    execution_service = FailingExecutionService(
        failures={
            question: QueryValidationError(
                "Only read-only analytical SELECT queries are allowed."
            )
        }
    )
    synthesizer = StubInvestigationSynthesizer()

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=synthesizer,
    ).investigate(
        question="Investigate the dataset.",
        analysis=_build_analysis_result(),
    )

    assert result.observation_count == 1
    assert result.observations[0].question == corrected_question
    assert execution_service.run_questions == [question, corrected_question]
    assert investigator.states[1].failed_attempt_count == 1
    assert investigator.states[1].failed_attempts[0].error_type == (
        "QueryValidationError"
    )
    assert synthesizer.states[0].failed_attempt_count == 1


def test_investigation_cannot_synthesize_after_only_validation_failure() -> None:
    """Rejected SQL cannot provide evidence for a successful conclusion."""

    question = "Inspect the dataset using prohibited SQL."

    investigator = StubInvestigator(
        [
            _investigate(question),
            _finish(),
        ]
    )

    execution_service = FailingExecutionService(
        failures={
            question: QueryValidationError(
                "Only read-only analytical SELECT queries are allowed."
            )
        }
    )

    synthesizer = StubInvestigationSynthesizer()

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=synthesizer,
    ).investigate(
        question="Investigate the dataset.",
        analysis=_build_analysis_result(),
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == 0
    assert "all attempted analytical queries failed" in result.conclusion

    assert execution_service.run_questions == [question]
    assert len(investigator.states) == 2

    failed_state = investigator.states[1]

    assert failed_state.observation_count == 0
    assert failed_state.failed_attempt_count == 1
    assert failed_state.failed_attempts[0].question == question
    assert failed_state.failed_attempts[0].error_type == "QueryValidationError"

    assert synthesizer.states == []


def test_investigation_preserves_evidence_after_failure() -> None:
    first_question = "Count the available records."
    failed_question = "Calculate an unavailable measure."
    final_question = "Count distinct categories."

    investigator = StubInvestigator(
        [
            _investigate(first_question),
            _investigate(failed_question),
            _investigate(final_question),
            _finish(),
        ]
    )
    execution_service = FailingExecutionService(
        failures={
            failed_question: QueryRuntimeError("The requested measure does not exist.")
        }
    )
    synthesizer = StubInvestigationSynthesizer()

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=synthesizer,
    ).investigate(
        question="Investigate the dataset.",
        analysis=_build_analysis_result(),
    )

    assert result.observation_count == 2
    assert result.observations[0].question == first_question
    assert result.observations[1].question == final_question

    final_state = synthesizer.states[0]

    assert final_state.observation_count == 2
    assert final_state.failed_attempt_count == 1
    assert final_state.failed_attempts[0].question == failed_question


def test_investigation_rejects_repeated_failed_question() -> None:
    question = "Calculate the unavailable measure."
    investigator = StubInvestigator(
        [
            _investigate(question),
            _investigate(question),
        ]
    )
    execution_service = FailingExecutionService(
        failures={question: QueryRuntimeError("The requested measure does not exist.")}
    )
    synthesizer = StubInvestigationSynthesizer()

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=synthesizer,
    ).investigate(
        question="Investigate the dataset.",
        analysis=_build_analysis_result(),
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == 0
    assert execution_service.run_questions == [question]
    assert investigator.states[1].failed_attempt_count == 1
    assert synthesizer.states == []


def test_failed_queries_count_toward_maximum_steps() -> None:
    first_question = "First unavailable measure."
    second_question = "Second unavailable measure."

    investigator = StubInvestigator(
        [
            _investigate(first_question),
            _investigate(second_question),
            _investigate("Third unavailable measure."),
        ]
    )
    execution_service = FailingExecutionService(
        failures={
            first_question: QueryRuntimeError("First query failed."),
            second_question: QueryTimeoutError("Second query timed out."),
        }
    )
    synthesizer = StubInvestigationSynthesizer()

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=synthesizer,
        max_steps=2,
    ).investigate(
        question="Investigate the dataset.",
        analysis=_build_analysis_result(),
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == 0
    assert execution_service.run_questions == [
        first_question,
        second_question,
    ]
    assert len(investigator.states) == 3
    assert investigator.states[2].failed_attempt_count == 2
    assert synthesizer.states == []


def test_unexpected_execution_errors_are_not_suppressed() -> None:
    question = "Count the available records."
    investigator = StubInvestigator([_investigate(question)])
    execution_service = FailingExecutionService(
        failures={question: ValueError("Unexpected programming error.")}
    )
    synthesizer = StubInvestigationSynthesizer()

    with pytest.raises(
        ValueError,
        match="Unexpected programming error.",
    ):
        _build_orchestrator(
            investigator=investigator,
            execution_service=execution_service,
            synthesizer=synthesizer,
        ).investigate(
            question="Investigate the dataset.",
            analysis=_build_analysis_result(),
        )

    assert execution_service.run_questions == [question]
    assert synthesizer.states == []


def test_investigation_can_finish_after_recoverable_failure() -> None:
    question = "Calculate an unavailable measure."

    investigator = StubInvestigator(
        [
            _investigate(question),
            _finish(),
        ]
    )

    execution_service = FailingExecutionService(
        failures={question: QueryRuntimeError("The requested measure does not exist.")}
    )

    synthesizer = StubInvestigationSynthesizer()

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=synthesizer,
    ).investigate(
        question="Investigate the dataset.",
        analysis=_build_analysis_result(),
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == 0
    assert "all attempted analytical queries failed" in result.conclusion

    assert execution_service.run_questions == [question]
    assert len(investigator.states) == 2

    failed_state = investigator.states[1]

    assert failed_state.failed_attempt_count == 1
    assert failed_state.failed_attempts[0].question == question
    assert failed_state.failed_attempts[0].error_type == "QueryRuntimeError"

    assert synthesizer.states == []


def test_finishes_after_final_permitted_successful_query() -> None:
    """The last permitted query must remain available for synthesis."""

    investigator = StubInvestigator(
        [
            _investigate("First analytical question."),
            _investigate("Second analytical question."),
            _finish(),
        ]
    )
    execution_service = StubExecutionService()
    synthesizer = StubInvestigationSynthesizer()

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=synthesizer,
        max_steps=2,
    ).investigate(
        question="Investigate the dataset.",
        analysis=_build_analysis_result(),
    )

    assert result.observation_count == 2
    assert execution_service.run_questions == [
        "First analytical question.",
        "Second analytical question.",
    ]
    assert len(investigator.states) == 3
    assert investigator.states[2].observation_count == 2
    assert len(synthesizer.states) == 1
    assert synthesizer.states[0].observation_count == 2


def test_finishes_after_final_permitted_failed_query() -> None:
    """A failed final query cannot justify a synthesized conclusion."""

    question = "Unavailable measure."

    investigator = StubInvestigator(
        [
            _investigate(question),
            _finish(),
        ]
    )

    execution_service = FailingExecutionService(
        failures={question: QueryRuntimeError("The requested measure is unavailable.")}
    )

    synthesizer = StubInvestigationSynthesizer()

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=synthesizer,
        max_steps=1,
    ).investigate(
        question="Investigate the dataset.",
        analysis=_build_analysis_result(),
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == 0
    assert "all attempted analytical queries failed" in result.conclusion

    assert execution_service.run_questions == [question]
    assert len(investigator.states) == 2
    assert investigator.states[1].failed_attempt_count == 1

    assert synthesizer.states == []


def test_single_step_budget_rejects_second_query() -> None:
    """A final decision cannot execute a query beyond the budget."""

    investigator = StubInvestigator(
        [
            _investigate("First question."),
            _investigate("Second question."),
        ]
    )
    execution_service = StubExecutionService()
    synthesizer = StubInvestigationSynthesizer()

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=synthesizer,
        max_steps=1,
    ).investigate(
        question="Investigate the dataset.",
        analysis=_build_analysis_result(),
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == 1
    assert execution_service.run_questions == ["First question."]
    assert len(investigator.states) == 2
    assert synthesizer.states == []


def test_single_step_budget_can_finish_without_querying() -> None:
    """Finishing immediately does not consume the query budget."""

    investigator = StubInvestigator([_finish()])
    execution_service = StubExecutionService()
    synthesizer = StubInvestigationSynthesizer()

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=synthesizer,
        max_steps=1,
    ).investigate(
        question="Investigate the dataset.",
        analysis=_build_analysis_result(),
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == 0
    assert execution_service.run_questions == []
    assert len(investigator.states) == 1
    assert synthesizer.states == []


def test_mixed_success_and_failure_consume_query_budget() -> None:
    """Successful and failed attempts share the same query budget."""

    successful_question = "Count records."
    failed_question = "Calculate unavailable measure."

    investigator = StubInvestigator(
        [
            _investigate(successful_question),
            _investigate(failed_question),
            _finish(),
        ]
    )
    execution_service = FailingExecutionService(
        failures={failed_question: QueryRuntimeError("Measure is unavailable.")}
    )
    synthesizer = StubInvestigationSynthesizer()

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=synthesizer,
        max_steps=2,
    ).investigate(
        question="Investigate the dataset.",
        analysis=_build_analysis_result(),
    )

    assert execution_service.run_questions == [
        successful_question,
        failed_question,
    ]
    assert result.observation_count == 1
    assert len(investigator.states) == 3

    final_state = synthesizer.states[0]

    assert final_state.observation_count == 1
    assert final_state.failed_attempt_count == 1
    assert final_state.failed_attempts[0].question == failed_question


def test_investigation_propagates_prompt_budget_failure() -> None:
    """Prompt-budget failures must not be treated as recoverable SQL errors."""

    question = "Analyze revenue by region."

    investigator = StubInvestigator(
        [
            _investigate(question),
            _finish(),
        ]
    )

    budget_error = PromptBudgetExceededError(
        max_prompt_chars=100,
        actual_prompt_chars=150,
    )

    execution_service = FailingExecutionService(failures={question: budget_error})
    synthesizer = StubInvestigationSynthesizer()

    with pytest.raises(PromptBudgetExceededError) as exc_info:
        _build_orchestrator(
            investigator=investigator,
            execution_service=execution_service,
            synthesizer=synthesizer,
        ).investigate(
            question="Investigate revenue performance.",
            analysis=_build_analysis_result(),
        )

    assert exc_info.value is budget_error
    assert execution_service.run_questions == [question]
    assert len(investigator.states) == 1
    assert investigator.states[0].observation_count == 0
    assert investigator.states[0].failed_attempt_count == 0
    assert synthesizer.states == []


def test_investigation_propagates_provider_planning_failure() -> None:
    """Provider outages must not be recorded as recoverable SQL failures."""

    question = "Analyze revenue by region."
    provider_error = GeminiGenerationError("Provider unavailable.")
    planning_error = QueryPlanningError("Query planner text generation failed.")
    planning_error.__cause__ = provider_error

    investigator = StubInvestigator(
        [
            _investigate(question),
            _finish(),
        ]
    )
    execution_service = FailingExecutionService(failures={question: planning_error})
    synthesizer = StubInvestigationSynthesizer()

    with pytest.raises(QueryPlanningError) as exc_info:
        _build_orchestrator(
            investigator=investigator,
            execution_service=execution_service,
            synthesizer=synthesizer,
        ).investigate(
            question="Investigate revenue performance.",
            analysis=_build_analysis_result(),
        )

    assert exc_info.value is planning_error
    assert exc_info.value.__cause__ is provider_error
    assert execution_service.run_questions == [question]
    assert len(investigator.states) == 1
    assert investigator.states[0].failed_attempt_count == 0
    assert synthesizer.states == []


def test_validation_failure_consumes_step_budget_and_preserves_evidence() -> None:
    first = "Count records."
    invalid = "Attempt prohibited SQL."

    investigator = StubInvestigator(
        [
            _investigate(first),
            _investigate(invalid),
            _investigate("Another question."),
        ]
    )
    execution_service = FailingExecutionService(
        failures={invalid: QueryValidationError("Unsafe query rejected.")}
    )
    synthesizer = StubInvestigationSynthesizer()

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=synthesizer,
        max_steps=2,
    ).investigate(
        question="Inspect records.",
        analysis=_build_analysis_result(),
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == 1
    assert result.observations[0].question == first
    assert investigator.states[2].failed_attempts[0].error_type == (
        "QueryValidationError"
    )
    assert execution_service.run_questions == [first, invalid]
    assert synthesizer.states == []


def test_repeated_validation_failure_is_not_reexecuted() -> None:
    invalid = "Prohibited SQL request."
    investigator = StubInvestigator(
        [
            _investigate(invalid),
            _investigate(invalid),
        ]
    )
    execution_service = FailingExecutionService(
        failures={invalid: QueryValidationError("Unsafe query rejected.")}
    )

    result = _build_orchestrator(
        investigator=investigator,
        execution_service=execution_service,
        synthesizer=StubInvestigationSynthesizer(),
    ).investigate(
        question="Inspect records.",
        analysis=_build_analysis_result(),
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == 0
    assert execution_service.run_questions == [invalid]
