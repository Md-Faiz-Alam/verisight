import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import (
    AnalysisResultBuilder,
    DatasetAnalysisResult,
)
from verisight.execution.decisions import (
    InvestigationAction,
    InvestigationDecision,
)
from verisight.execution.exceptions import InvestigationError
from verisight.execution.execution import QueryExecution
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_result import InvestigationResult
from verisight.execution.models import QueryResult
from verisight.execution.orchestration import InvestigationOrchestrator
from verisight.execution.planning import QueryPlan
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
    """Deterministic analytical execution service for tests."""

    def __init__(self) -> None:
        self.run_questions: list[str] = []

    def run(self, question: str) -> QueryExecution:
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


class StubInvestigationSynthesizer:
    """Deterministic investigation synthesizer for orchestration tests."""

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


def test_investigation_finishes_without_querying() -> None:
    investigator = StubInvestigator(
        [
            InvestigationDecision(
                action=InvestigationAction.FINISH,
                reasoning="Existing evidence is sufficient.",
            )
        ]
    )
    execution_service = StubExecutionService()
    synthesizer = StubInvestigationSynthesizer(
        conclusion="The existing evidence supports the final conclusion."
    )

    orchestrator = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
    )

    result = orchestrator.investigate(
        question="Why did revenue decline?",
        analysis=_build_analysis_result(),
    )

    assert isinstance(result, InvestigationResult)
    assert result.question == "Why did revenue decline?"
    assert result.conclusion == ("The existing evidence supports the final conclusion.")
    assert result.observations == ()
    assert result.observation_count == 0

    assert execution_service.run_questions == []

    assert len(synthesizer.states) == 1
    assert synthesizer.states[0].question == "Why did revenue decline?"
    assert synthesizer.states[0].observation_count == 0


def test_investigation_executes_requested_observation() -> None:
    investigator = StubInvestigator(
        [
            InvestigationDecision(
                action=InvestigationAction.INVESTIGATE,
                reasoning="Revenue should be examined over time.",
                question="What is revenue by month?",
            ),
            InvestigationDecision(
                action=InvestigationAction.FINISH,
                reasoning="The evidence is sufficient.",
            ),
        ]
    )
    execution_service = StubExecutionService()
    synthesizer = StubInvestigationSynthesizer(
        conclusion="Revenue changed across the observed period."
    )

    orchestrator = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
    )

    result = orchestrator.investigate(
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

    assert len(synthesizer.states) == 1
    assert synthesizer.states[0].observation_count == 1
    assert synthesizer.states[0].observations[0] == observation


def test_investigator_receives_updated_state() -> None:
    investigator = StubInvestigator(
        [
            InvestigationDecision(
                action=InvestigationAction.INVESTIGATE,
                reasoning="More evidence is required.",
                question="What is revenue by month?",
            ),
            InvestigationDecision(
                action=InvestigationAction.FINISH,
                reasoning="The observation answers the question.",
            ),
        ]
    )
    synthesizer = StubInvestigationSynthesizer()

    orchestrator = InvestigationOrchestrator(
        execution_service=StubExecutionService(),
        investigator=investigator,
        synthesizer=synthesizer,
    )

    orchestrator.investigate(
        question="Why did revenue decline?",
        analysis=_build_analysis_result(),
    )

    assert len(investigator.states) == 2
    assert investigator.states[0].observation_count == 0
    assert investigator.states[1].observation_count == 1

    assert len(synthesizer.states) == 1
    assert synthesizer.states[0].observation_count == 1


def test_investigation_can_execute_multiple_observations() -> None:
    investigator = StubInvestigator(
        [
            InvestigationDecision(
                action=InvestigationAction.INVESTIGATE,
                reasoning="First inspect revenue over time.",
                question="What is revenue by month?",
            ),
            InvestigationDecision(
                action=InvestigationAction.INVESTIGATE,
                reasoning="Now inspect customer contribution.",
                question="What is revenue by customer?",
            ),
            InvestigationDecision(
                action=InvestigationAction.FINISH,
                reasoning="The available evidence is sufficient.",
            ),
        ]
    )

    execution_service = StubExecutionService()
    synthesizer = StubInvestigationSynthesizer(
        conclusion="The observations support the final conclusion."
    )

    orchestrator = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
    )

    result = orchestrator.investigate(
        question="Why did revenue decline?",
        analysis=_build_analysis_result(),
    )

    assert result.conclusion == ("The observations support the final conclusion.")
    assert result.observation_count == 2

    assert execution_service.run_questions == [
        "What is revenue by month?",
        "What is revenue by customer?",
    ]

    assert len(synthesizer.states) == 1
    assert synthesizer.states[0].observation_count == 2


def test_investigation_result_preserves_analysis() -> None:
    analysis = _build_analysis_result()

    investigator = StubInvestigator(
        [
            InvestigationDecision(
                action=InvestigationAction.FINISH,
                reasoning="The deterministic evidence is sufficient.",
            )
        ]
    )
    synthesizer = StubInvestigationSynthesizer()

    result = InvestigationOrchestrator(
        execution_service=StubExecutionService(),
        investigator=investigator,
        synthesizer=synthesizer,
    ).investigate(
        question="Inspect the dataset.",
        analysis=analysis,
    )

    assert result.analysis is analysis
    assert synthesizer.states[0].analysis is analysis


def test_finish_reasoning_is_not_used_as_conclusion() -> None:
    investigator = StubInvestigator(
        [
            InvestigationDecision(
                action=InvestigationAction.FINISH,
                reasoning="Enough evidence has been collected.",
            )
        ]
    )
    synthesizer = StubInvestigationSynthesizer(
        conclusion="Revenue declined in the observed data."
    )

    result = InvestigationOrchestrator(
        execution_service=StubExecutionService(),
        investigator=investigator,
        synthesizer=synthesizer,
    ).investigate(
        question="Why did revenue decline?",
        analysis=_build_analysis_result(),
    )

    assert result.conclusion == "Revenue declined in the observed data."
    assert result.conclusion != "Enough evidence has been collected."


def test_synthesizer_is_called_only_after_finish() -> None:
    investigator = StubInvestigator(
        [
            InvestigationDecision(
                action=InvestigationAction.INVESTIGATE,
                reasoning="More evidence is required.",
                question="What is revenue by month?",
            ),
            InvestigationDecision(
                action=InvestigationAction.FINISH,
                reasoning="The evidence is now sufficient.",
            ),
        ]
    )
    synthesizer = StubInvestigationSynthesizer()

    orchestrator = InvestigationOrchestrator(
        execution_service=StubExecutionService(),
        investigator=investigator,
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

    orchestrator = InvestigationOrchestrator(
        execution_service=StubExecutionService(),
        investigator=investigator,
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

    assert synthesizer.states == []


def test_investigation_rejects_non_positive_max_steps() -> None:
    with pytest.raises(
        ValueError,
        match="Maximum investigation steps must be positive.",
    ):
        InvestigationOrchestrator(
            execution_service=StubExecutionService(),
            investigator=StubInvestigator([]),
            synthesizer=StubInvestigationSynthesizer(),
            max_steps=0,
        )


def test_investigation_stops_at_maximum_steps() -> None:
    investigator = StubInvestigator(
        [
            InvestigationDecision(
                action=InvestigationAction.INVESTIGATE,
                reasoning="More evidence is required.",
                question="What is revenue by month?",
            ),
            InvestigationDecision(
                action=InvestigationAction.INVESTIGATE,
                reasoning="Different evidence is still required.",
                question="What is revenue by customer?",
            ),
        ]
    )

    execution_service = StubExecutionService()
    synthesizer = StubInvestigationSynthesizer()

    orchestrator = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
        max_steps=2,
    )

    with pytest.raises(
        InvestigationError,
        match="Investigation exceeded the maximum number of steps.",
    ):
        orchestrator.investigate(
            question="Why did revenue decline?",
            analysis=_build_analysis_result(),
        )

    assert len(execution_service.run_questions) == 2
    assert synthesizer.states == []


def test_investigation_rejects_repeated_question() -> None:
    investigator = StubInvestigator(
        [
            InvestigationDecision(
                action=InvestigationAction.INVESTIGATE,
                reasoning="Revenue should be examined over time.",
                question="What is revenue by month?",
            ),
            InvestigationDecision(
                action=InvestigationAction.INVESTIGATE,
                reasoning="The same evidence should be checked again.",
                question="What is revenue by month?",
            ),
        ]
    )

    execution_service = StubExecutionService()
    synthesizer = StubInvestigationSynthesizer()

    orchestrator = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
    )

    with pytest.raises(
        InvestigationError,
        match="Investigator requested a repeated analytical question.",
    ):
        orchestrator.investigate(
            question="Why did revenue decline?",
            analysis=_build_analysis_result(),
        )

    assert execution_service.run_questions == ["What is revenue by month?"]
    assert synthesizer.states == []


def test_repeated_question_detection_is_normalized() -> None:
    investigator = StubInvestigator(
        [
            InvestigationDecision(
                action=InvestigationAction.INVESTIGATE,
                reasoning="Revenue should be examined over time.",
                question="What is revenue by month?",
            ),
            InvestigationDecision(
                action=InvestigationAction.INVESTIGATE,
                reasoning="The same evidence should be checked again.",
                question="  what   is REVENUE by month?  ",
            ),
        ]
    )

    execution_service = StubExecutionService()
    synthesizer = StubInvestigationSynthesizer()

    orchestrator = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
    )

    with pytest.raises(
        InvestigationError,
        match="Investigator requested a repeated analytical question.",
    ):
        orchestrator.investigate(
            question="Why did revenue decline?",
            analysis=_build_analysis_result(),
        )

    assert execution_service.run_questions == ["What is revenue by month?"]
    assert synthesizer.states == []


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        (
            "What is revenue by month?",
            "what is revenue by month?",
        ),
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

    orchestrator = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
    )

    with pytest.raises(
        InvestigationError,
        match="Investigator did not provide an analytical question.",
    ):
        orchestrator.investigate(
            question="Why did revenue decline?",
            analysis=_build_analysis_result(),
        )

    assert execution_service.run_questions == []
    assert synthesizer.states == []


def test_investigation_preserves_executed_plan_provenance() -> None:
    class RepairedExecutionService:
        def __init__(self) -> None:
            self.run_questions: list[str] = []

        def run(self, question: str) -> QueryExecution:
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
            InvestigationDecision(
                action=InvestigationAction.INVESTIGATE,
                reasoning="Assessment performance should be quantified.",
                question="What is the average assessment score?",
            ),
            InvestigationDecision(
                action=InvestigationAction.FINISH,
                reasoning="The requested evidence is available.",
            ),
        ]
    )

    execution_service = RepairedExecutionService()
    synthesizer = StubInvestigationSynthesizer(
        conclusion="The executed observation provides the requested evidence."
    )

    orchestrator = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
    )

    result = orchestrator.investigate(
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
