from verisight.analysis.insights import (
    AnalysisInsight,
    InsightScope,
    InsightType,
)
from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import DatasetAnalysisResult
from verisight.analysis.summary import AnalysisSummary
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_formatting import (
    InvestigationStateFormatter,
)
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation
from verisight.ingestion.schema import (
    ColumnSchema,
    DatasetSchema,
    LogicalType,
    TableSchema,
)
from verisight.profiling.models import DatasetProfile
from verisight.quality.models import (
    QualityIssue,
    QualityIssueType,
    QualityScope,
    QualitySeverity,
)


def _build_state(
    *,
    observations: tuple[QueryObservation, ...] = (),
    schema: DatasetSchema | None = None,
) -> InvestigationState:
    issue = QualityIssue(
        issue_type=QualityIssueType.MISSING_VALUES,
        severity=QualitySeverity.WARNING,
        scope=QualityScope.COLUMN,
        table_name="Orders",
        relation_name="orders",
        column_name="amount",
        message="Column 'amount' contains missing values.",
        affected_count=2,
        affected_ratio=0.2,
        evidence={
            "missing_count": 2,
            "missing_ratio": 0.2,
        },
    )

    analysis = DatasetAnalysis(
        schema=schema if schema is not None else DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(issue,),
    )

    summary = AnalysisSummary(
        table_count=1,
        total_row_count=10,
        total_column_count=4,
        issue_count=1,
        info_issue_count=0,
        warning_issue_count=1,
        error_issue_count=0,
        table_issue_count=0,
        column_issue_count=1,
        affected_relation_names=("orders",),
    )

    insight = AnalysisInsight(
        insight_type=InsightType.DATA_QUALITY,
        scope=InsightScope.COLUMN,
        message="Column 'amount' contains missing values.",
        table_name="Orders",
        relation_name="orders",
        column_name="amount",
        evidence={
            "missing_count": 2,
            "missing_ratio": 0.2,
        },
    )

    result = DatasetAnalysisResult(
        analysis=analysis,
        summary=summary,
        insights=(insight,),
    )

    return InvestigationState(
        question="Why did revenue decline?",
        analysis=result,
        observations=observations,
    )


def _build_summary(
    *,
    issue_count: int = 0,
    table_issue_count: int = 0,
    column_issue_count: int = 0,
    affected_relation_names: tuple[str, ...] = (),
) -> AnalysisSummary:
    return AnalysisSummary(
        table_count=1,
        total_row_count=10,
        total_column_count=4,
        issue_count=issue_count,
        info_issue_count=0,
        warning_issue_count=issue_count,
        error_issue_count=0,
        table_issue_count=table_issue_count,
        column_issue_count=column_issue_count,
        affected_relation_names=affected_relation_names,
    )


def test_formats_investigation_state() -> None:
    state = _build_state()

    formatted = InvestigationStateFormatter().format(state)

    assert formatted == (
        "ORIGINAL QUESTION\n"
        "Why did revenue decline?\n"
        "\n"
        "DATASET SUMMARY\n"
        "Tables: 1\n"
        "Rows: 10\n"
        "Columns: 4\n"
        "Quality issues: 1\n"
        "Info issues: 0\n"
        "Warning issues: 1\n"
        "Error issues: 0\n"
        "\n"
        "QUERYABLE DATASET STRUCTURE\n"
        "None\n"
        "\n"
        "DETERMINISTIC INSIGHTS\n"
        "1. [data_quality] Column 'amount' contains missing values.\n"
        '   Evidence: {"missing_count":2,"missing_ratio":0.2}\n'
        "\n"
        "DATA QUALITY FINDINGS\n"
        "1. [warning] [missing_values] orders.amount: "
        "Column 'amount' contains missing values.\n"
        '   Evidence: {"missing_count":2,"missing_ratio":0.2}\n'
        "\n"
        "EXECUTED OBSERVATIONS\n"
        "None"
    )


def test_formats_queryable_dataset_structure() -> None:
    schema = DatasetSchema(
        tables=(
            TableSchema(
                name="Sales",
                relation_name="sales",
                row_count=16,
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
                        nullable=True,
                        missing_count=1,
                    ),
                ),
            ),
        ),
    )

    formatted = InvestigationStateFormatter().format(_build_state(schema=schema))

    assert (
        "QUERYABLE DATASET STRUCTURE\n"
        "\n"
        "RELATION sales\n"
        "Display name: Sales\n"
        "Rows: 16\n"
        "Columns:\n"
        "- month | logical_type=string | physical_dtype=object | "
        "nullable=false\n"
        "- revenue | logical_type=integer | physical_dtype=int64 | "
        "nullable=true"
    ) in formatted


def test_formats_relation_without_columns() -> None:
    schema = DatasetSchema(
        tables=(
            TableSchema(
                name="Empty",
                relation_name="empty",
                row_count=0,
                column_count=0,
                columns=(),
            ),
        ),
    )

    formatted = InvestigationStateFormatter().format(_build_state(schema=schema))

    assert ("RELATION empty\nDisplay name: Empty\nRows: 0\nColumns:\nNone") in formatted


def test_formats_executed_observation() -> None:
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

    formatted = InvestigationStateFormatter().format(
        _build_state(observations=(observation,))
    )

    assert "EXECUTED OBSERVATIONS" in formatted
    assert "OBSERVATION 1" in formatted
    assert "Question: What is revenue by month?" in formatted
    assert (
        "SELECT month, SUM(revenue) AS revenue FROM sales GROUP BY month"
    ) in formatted
    assert "Columns: month, revenue" in formatted
    assert "Row count: 2" in formatted
    assert '["January",1000.0]' in formatted
    assert '["February",800.0]' in formatted


def test_formats_empty_analysis_sections() -> None:
    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(),
    )

    state = InvestigationState(
        question="What happened?",
        analysis=DatasetAnalysisResult(
            analysis=analysis,
            summary=AnalysisSummary(
                table_count=0,
                total_row_count=0,
                total_column_count=0,
                issue_count=0,
                info_issue_count=0,
                warning_issue_count=0,
                error_issue_count=0,
                table_issue_count=0,
                column_issue_count=0,
                affected_relation_names=(),
            ),
            insights=(),
        ),
    )

    formatted = InvestigationStateFormatter().format(state)

    assert "QUERYABLE DATASET STRUCTURE\nNone" in formatted
    assert "DETERMINISTIC INSIGHTS\nNone" in formatted
    assert "DATA QUALITY FINDINGS\nNone" in formatted
    assert "EXECUTED OBSERVATIONS\nNone" in formatted


def test_formats_empty_query_result() -> None:
    observation = QueryObservation(
        question="Which customers have negative revenue?",
        sql="SELECT customer FROM sales WHERE revenue < 0",
        result=QueryResult(
            columns=("customer",),
            rows=(),
        ),
    )

    formatted = InvestigationStateFormatter().format(
        _build_state(observations=(observation,))
    )

    assert "Columns: customer\nRows: None" in formatted


def test_formats_insight_without_evidence() -> None:
    insight = AnalysisInsight(
        insight_type=InsightType.DATA_QUALITY,
        scope=InsightScope.TABLE,
        message="The dataset contains a noteworthy pattern.",
        table_name="Orders",
        relation_name="orders",
        column_name=None,
        evidence={},
    )

    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(),
    )

    state = InvestigationState(
        question="What happened?",
        analysis=DatasetAnalysisResult(
            analysis=analysis,
            summary=_build_summary(),
            insights=(insight,),
        ),
    )

    formatted = InvestigationStateFormatter().format(state)

    assert "1. [data_quality] The dataset contains a noteworthy pattern." in formatted
    assert "Evidence:" not in formatted


def test_formats_table_quality_issue_without_column_name() -> None:
    issue = QualityIssue(
        issue_type=QualityIssueType.MISSING_VALUES,
        severity=QualitySeverity.WARNING,
        scope=QualityScope.TABLE,
        table_name="Orders",
        relation_name="orders",
        column_name=None,
        message="The table contains missing values.",
        affected_count=2,
        affected_ratio=0.2,
        evidence={
            "missing_count": 2,
        },
    )

    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(issue,),
    )

    state = InvestigationState(
        question="What happened?",
        analysis=DatasetAnalysisResult(
            analysis=analysis,
            summary=_build_summary(
                issue_count=1,
                table_issue_count=1,
                affected_relation_names=("orders",),
            ),
            insights=(),
        ),
    )

    formatted = InvestigationStateFormatter().format(state)

    assert (
        "1. [warning] [missing_values] orders: The table contains missing values."
    ) in formatted
    assert (
        "1. [warning] [missing_values] orders.amount: "
        "The table contains missing values."
    ) not in formatted


def test_formats_quality_issue_without_evidence() -> None:
    issue = QualityIssue(
        issue_type=QualityIssueType.MISSING_VALUES,
        severity=QualitySeverity.WARNING,
        scope=QualityScope.COLUMN,
        table_name="Orders",
        relation_name="orders",
        column_name="amount",
        message="Column 'amount' contains missing values.",
        affected_count=2,
        affected_ratio=0.2,
        evidence={},
    )

    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(issue,),
    )

    state = InvestigationState(
        question="What happened?",
        analysis=DatasetAnalysisResult(
            analysis=analysis,
            summary=_build_summary(
                issue_count=1,
                column_issue_count=1,
                affected_relation_names=("orders",),
            ),
            insights=(),
        ),
    )

    formatted = InvestigationStateFormatter().format(state)

    assert (
        "1. [warning] [missing_values] orders.amount: "
        "Column 'amount' contains missing values."
    ) in formatted
    assert "Evidence:" not in formatted
