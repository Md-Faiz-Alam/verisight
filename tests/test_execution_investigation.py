import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder, DatasetAnalysisResult
from verisight.execution.decisions import InvestigationAction, InvestigationDecision
from verisight.execution.exceptions import QueryRuntimeError
from verisight.execution.execution import QueryExecution
from verisight.execution.investigation import (
    FailedQueryAttempt,
    InvestigationState,
)
from verisight.execution.investigation_compaction import InvestigationCompaction
from verisight.execution.investigation_prompting import InvestigationPromptBuilder
from verisight.execution.investigation_result import InvestigationStatus
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation
from verisight.execution.orchestration import InvestigationOrchestrator
from verisight.execution.planning import QueryPlan
from verisight.ingestion.schema import (
    ColumnSchema,
    DatasetSchema,
    LogicalType,
    TableSchema,
)
from verisight.profiling.models import DatasetProfile


def _build_analysis_result(
    *,
    schema: DatasetSchema | None = None,
) -> DatasetAnalysisResult:
    analysis = DatasetAnalysis(
        schema=schema if schema is not None else DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(),
    )

    return AnalysisResultBuilder().build(analysis)


def test_investigation_state_starts_without_observations() -> None:
    state = InvestigationState(
        question="Why did revenue decline?",
        analysis=_build_analysis_result(),
    )

    assert state.question == "Why did revenue decline?"
    assert state.observations == ()
    assert state.observation_count == 0
    assert state.remaining_steps is None


def test_investigation_state_exposes_query_context() -> None:
    schema = DatasetSchema(
        tables=(
            TableSchema(
                name="Sales",
                relation_name="sales",
                row_count=2,
                column_count=2,
                columns=(
                    ColumnSchema(
                        name="month",
                        physical_dtype="object",
                        logical_type=LogicalType.STRING,
                        nullable=False,
                        missing_count=0,
                    ),
                    ColumnSchema(
                        name="revenue",
                        physical_dtype="int64",
                        logical_type=LogicalType.INTEGER,
                        nullable=False,
                        missing_count=0,
                    ),
                ),
            ),
        ),
    )

    state = InvestigationState(
        question="Why did revenue decline?",
        analysis=_build_analysis_result(schema=schema),
    )

    context = state.context

    assert context.relation_count == 1

    relation = context.relations[0]

    assert relation.name == "Sales"
    assert relation.relation_name == "sales"
    assert relation.row_count == 2
    assert tuple(column.name for column in relation.columns) == (
        "month",
        "revenue",
    )
    assert relation.columns[0].logical_type is LogicalType.STRING
    assert relation.columns[1].logical_type is LogicalType.INTEGER


def test_add_observation_returns_new_investigation_state() -> None:
    state = InvestigationState(
        question="Why did revenue decline?",
        analysis=_build_analysis_result(),
    )

    observation = QueryObservation(
        question="What is revenue by month?",
        sql=("SELECT month, SUM(revenue) AS revenue FROM sales GROUP BY month"),
        result=QueryResult(
            columns=("month", "revenue"),
            rows=(
                ("January", 1000.0),
                ("February", 800.0),
            ),
        ),
    )

    updated = state.add_observation(observation)

    assert updated is not state

    assert state.observations == ()
    assert state.observation_count == 0

    assert updated.observations == (observation,)
    assert updated.observation_count == 1

    assert updated.question == state.question
    assert updated.analysis is state.analysis
    assert updated.context == state.context


def test_investigation_state_starts_without_failed_attempts() -> None:
    state = InvestigationState(
        question="Investigate the dataset.",
        analysis=_build_analysis_result(),
    )

    assert state.failed_attempts == ()
    assert state.failed_attempt_count == 0


def test_add_failed_attempt_preserves_existing_observations() -> None:
    observation = QueryObservation(
        question="Count the records.",
        sql="SELECT COUNT(*) AS total FROM records",
        result=QueryResult(
            columns=("total",),
            rows=((10,),),
        ),
    )

    original = InvestigationState(
        question="Investigate the dataset.",
        analysis=_build_analysis_result(),
        observations=(observation,),
    )

    attempt = FailedQueryAttempt(
        question="Calculate an unavailable measure.",
        error_type="QueryRuntimeError",
        message="The requested column does not exist.",
    )

    updated = original.add_failed_attempt(attempt)

    assert updated is not original
    assert original.failed_attempt_count == 0
    assert updated.failed_attempts == (attempt,)
    assert updated.failed_attempt_count == 1

    assert updated.observations == (observation,)
    assert updated.observation_count == 1
    assert updated.analysis is original.analysis


def test_add_observation_preserves_existing_failed_attempts() -> None:
    attempt = FailedQueryAttempt(
        question="Calculate an unavailable measure.",
        error_type="QueryRuntimeError",
        message="The requested column does not exist.",
    )

    original = InvestigationState(
        question="Investigate the dataset.",
        analysis=_build_analysis_result(),
        failed_attempts=(attempt,),
    )

    observation = QueryObservation(
        question="Count the records.",
        sql="SELECT COUNT(*) AS total FROM records",
        result=QueryResult(
            columns=("total",),
            rows=((10,),),
        ),
    )

    updated = original.add_observation(observation)

    assert updated.failed_attempts == (attempt,)
    assert updated.failed_attempt_count == 1
    assert updated.observations == (observation,)
    assert updated.observation_count == 1

    assert original.observations == ()


@pytest.mark.parametrize("remaining", [-1, True], ids=["negative", "boolean"])
def test_remaining_steps_reject_invalid_budgets(remaining: int) -> None:
    with pytest.raises(ValueError, match="nonnegative integer"):
        InvestigationState(
            question="Measure the totals.",
            analysis=_build_analysis_result(),
            remaining_steps=remaining,
        )


def test_remaining_steps_consume_successes_and_failures_without_mutation() -> None:
    initial = InvestigationState(
        question="Compare before and after.",
        analysis=_build_analysis_result(),
        remaining_steps=2,
    )
    observation = QueryObservation(
        question="Measure before.",
        sql="SELECT 100 AS litres",
        result=QueryResult(columns=("litres",), rows=((100,),)),
    )
    failure = FailedQueryAttempt("Measure after.", "QueryRuntimeError", "Safe error.")

    observed = initial.add_observation(observation)
    exhausted = observed.add_failed_attempt(failure)

    assert initial.remaining_steps == 2
    assert initial.observations == ()
    assert observed.remaining_steps == 1
    assert observed.failed_attempts == ()
    assert exhausted.remaining_steps == 0
    assert exhausted.observations == (observation,)
    assert exhausted.failed_attempts == (failure,)
    assert exhausted.add_observation(observation).remaining_steps == 0
    assert exhausted.add_failed_attempt(failure).remaining_steps == 0


@pytest.mark.parametrize("remaining", [2, 1, 0])
def test_full_and_compact_prompts_preserve_actual_remaining_attempts(
    remaining: int,
) -> None:
    state = InvestigationState(
        question="Measure accepted litres before and after, then compare.",
        analysis=_build_analysis_result(),
        remaining_steps=2,
    )
    for index in range(2 - remaining):
        state = state.add_observation(
            QueryObservation(
                question=f"Measure period {index}.",
                sql=f"SELECT {100 + index} AS litres",
                result=QueryResult(columns=("litres",), rows=((100 + index,),)),
            )
        )

    full = InvestigationPromptBuilder().build(state)
    compact = InvestigationCompaction().investigator_prompt(state)

    for prompt in (full, compact):
        assert f"ANALYTICAL ATTEMPTS REMAINING\n{remaining}\n" in prompt
        assert (
            "Successful and failed analytical attempts both consume this budget"
            in prompt
        )
        assert "When no analytical attempts remain, choose finish" in prompt
        assert "Do not assume another query will be available" in prompt
        assert "Never invent an unmeasured comparison group or period" in prompt
    assert state.observation_count == 2 - remaining
    assert state.remaining_steps == remaining


@pytest.mark.parametrize("finish_at_zero", [False, True])
def test_runtime_budget_reaches_investigator_and_remains_authoritative(
    finish_at_zero: bool,
) -> None:
    class Investigator:
        def __init__(self) -> None:
            self.states: list[InvestigationState] = []

        def decide(self, state: InvestigationState) -> InvestigationDecision:
            self.states.append(state)
            if finish_at_zero and state.remaining_steps == 0:
                return InvestigationDecision(
                    InvestigationAction.FINISH, "Budget exhausted."
                )
            return InvestigationDecision(
                InvestigationAction.INVESTIGATE,
                "Collect another measurement.",
                f"Measure aspect {len(self.states)}.",
            )

    class Runner:
        def __init__(self) -> None:
            self.questions: list[str] = []

        def run(
            self, question: str, *, original_question: str | None = None
        ) -> QueryExecution:
            self.questions.append(question)
            if len(self.questions) == 1:
                raise QueryRuntimeError("Measurement unavailable.")
            return QueryExecution(
                QueryPlan(question, "SELECT 100 AS litres"),
                QueryResult(columns=("litres",), rows=((100,),)),
            )

    class Synthesizer:
        def __init__(self) -> None:
            self.states: list[InvestigationState] = []

        def synthesize(self, state: InvestigationState) -> str:
            self.states.append(state)
            return "Only one measurement is available; no comparison is established."

    investigator = Investigator()
    runner = Runner()
    synthesizer = Synthesizer()

    result = InvestigationOrchestrator(
        execution_service=runner,
        investigator=investigator,
        synthesizer=synthesizer,
        max_steps=2,
    ).investigate(
        question="Measure before and after, then compare.",
        analysis=_build_analysis_result(),
    )

    assert [state.remaining_steps for state in investigator.states] == [2, 1, 0]
    assert [
        (state.observation_count, state.failed_attempt_count)
        for state in investigator.states
    ] == [(0, 0), (0, 1), (1, 1)]
    assert len(runner.questions) == 2
    assert result.observation_count == 1
    assert result.failed_attempt_count == 1
    assert result.generated_claims == ()
    assert result.narrative_verified is False
    if finish_at_zero:
        assert result.status is InvestigationStatus.COMPLETE
        assert "no comparison is established" in result.conclusion
        assert synthesizer.states[0].remaining_steps == 0
    else:
        assert result.status is InvestigationStatus.INCOMPLETE
        assert "maximum number of analytical steps" in result.conclusion
        assert synthesizer.states == []
