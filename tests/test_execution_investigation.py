from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder, DatasetAnalysisResult
from verisight.execution.investigation import InvestigationState
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation
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
