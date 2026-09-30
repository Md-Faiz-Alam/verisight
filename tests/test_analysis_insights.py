from dataclasses import FrozenInstanceError

import pytest

from verisight.analysis.insights import (
    AnalysisInsight,
    InsightGenerator,
    InsightScope,
    InsightType,
)
from verisight.analysis.models import DatasetAnalysis
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile, TableProfile
from verisight.quality.models import (
    QualityIssue,
    QualityIssueType,
    QualityScope,
    QualitySeverity,
)


def make_table_profile(
    *,
    name: str,
    relation_name: str,
    row_count: int,
    column_count: int,
) -> TableProfile:
    """Create a minimal table profile for insight tests."""

    return TableProfile(
        name=name,
        relation_name=relation_name,
        row_count=row_count,
        column_count=column_count,
        duplicate_row_count=0,
        duplicate_row_ratio=0.0,
        columns=(),
    )


def make_quality_issue(
    *,
    table_name: str,
    relation_name: str,
    scope: QualityScope,
    column_name: str | None = None,
    message: str = "Test quality issue.",
    evidence: dict[str, object] | None = None,
) -> QualityIssue:
    """Create a quality issue for insight tests."""

    return QualityIssue(
        issue_type=QualityIssueType.MISSING_VALUES,
        severity=QualitySeverity.WARNING,
        scope=scope,
        table_name=table_name,
        relation_name=relation_name,
        column_name=column_name,
        message=message,
        evidence={} if evidence is None else evidence,
    )


def test_insight_type_values_are_stable() -> None:
    assert InsightType.DATASET_STRUCTURE.value == "dataset_structure"
    assert InsightType.TABLE_STRUCTURE.value == "table_structure"
    assert InsightType.DATA_QUALITY.value == "data_quality"


def test_insight_scope_values_are_stable() -> None:
    assert InsightScope.DATASET.value == "dataset"
    assert InsightScope.TABLE.value == "table"
    assert InsightScope.COLUMN.value == "column"


def test_analysis_insight_stores_dataset_observation() -> None:
    insight = AnalysisInsight(
        insight_type=InsightType.DATASET_STRUCTURE,
        scope=InsightScope.DATASET,
        message="Dataset contains two tables.",
        evidence={
            "table_count": 2,
            "total_row_count": 15,
        },
    )

    assert insight.insight_type is InsightType.DATASET_STRUCTURE
    assert insight.scope is InsightScope.DATASET
    assert insight.message == "Dataset contains two tables."
    assert insight.table_name is None
    assert insight.relation_name is None
    assert insight.column_name is None
    assert insight.evidence == {
        "table_count": 2,
        "total_row_count": 15,
    }


def test_analysis_insight_stores_table_observation() -> None:
    insight = AnalysisInsight(
        insight_type=InsightType.TABLE_STRUCTURE,
        scope=InsightScope.TABLE,
        message="Table contains 10 rows and 3 columns.",
        table_name="orders",
        relation_name="orders",
        evidence={
            "row_count": 10,
            "column_count": 3,
        },
    )

    assert insight.table_name == "orders"
    assert insight.relation_name == "orders"
    assert insight.column_name is None


def test_analysis_insight_stores_column_observation() -> None:
    insight = AnalysisInsight(
        insight_type=InsightType.DATA_QUALITY,
        scope=InsightScope.COLUMN,
        message="Column contains missing values.",
        table_name="orders",
        relation_name="orders",
        column_name="amount",
        evidence={"missing_count": 3},
    )

    assert insight.table_name == "orders"
    assert insight.relation_name == "orders"
    assert insight.column_name == "amount"


def test_analysis_insights_have_independent_evidence() -> None:
    first = AnalysisInsight(
        insight_type=InsightType.DATASET_STRUCTURE,
        scope=InsightScope.DATASET,
        message="First insight.",
    )

    second = AnalysisInsight(
        insight_type=InsightType.DATASET_STRUCTURE,
        scope=InsightScope.DATASET,
        message="Second insight.",
    )

    assert first.evidence == {}
    assert second.evidence == {}
    assert first.evidence is not second.evidence


def test_analysis_insight_is_immutable() -> None:
    insight = AnalysisInsight(
        insight_type=InsightType.DATASET_STRUCTURE,
        scope=InsightScope.DATASET,
        message="Dataset structure.",
    )

    with pytest.raises(FrozenInstanceError):
        insight.message = "Changed."  # type: ignore[misc]


def test_generator_creates_dataset_structure_insight() -> None:
    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(
            tables=(
                make_table_profile(
                    name="orders",
                    relation_name="orders",
                    row_count=10,
                    column_count=3,
                ),
                make_table_profile(
                    name="customers",
                    relation_name="customers",
                    row_count=5,
                    column_count=2,
                ),
            )
        ),
        issues=(),
    )

    insights = InsightGenerator().generate(analysis)

    assert insights[0].insight_type is InsightType.DATASET_STRUCTURE
    assert insights[0].scope is InsightScope.DATASET
    assert insights[0].message == "Dataset contains 2 table(s)."
    assert insights[0].table_name is None
    assert insights[0].relation_name is None
    assert insights[0].column_name is None
    assert insights[0].evidence == {
        "table_count": 2,
        "total_row_count": 15,
        "total_column_count": 5,
    }


def test_generator_creates_table_structure_insights() -> None:
    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(
            tables=(
                make_table_profile(
                    name="orders",
                    relation_name="orders",
                    row_count=10,
                    column_count=3,
                ),
                make_table_profile(
                    name="customers",
                    relation_name="customers",
                    row_count=5,
                    column_count=2,
                ),
            )
        ),
        issues=(),
    )

    insights = InsightGenerator().generate(analysis)

    table_insights = insights[1:]

    assert tuple(insight.insight_type for insight in table_insights) == (
        InsightType.TABLE_STRUCTURE,
        InsightType.TABLE_STRUCTURE,
    )
    assert tuple(insight.scope for insight in table_insights) == (
        InsightScope.TABLE,
        InsightScope.TABLE,
    )
    assert tuple(insight.table_name for insight in table_insights) == (
        "orders",
        "customers",
    )
    assert tuple(insight.relation_name for insight in table_insights) == (
        "orders",
        "customers",
    )
    assert table_insights[0].message == (
        "Table 'orders' contains 10 row(s) and 3 column(s)."
    )
    assert table_insights[0].evidence == {
        "row_count": 10,
        "column_count": 3,
    }
    assert table_insights[1].evidence == {
        "row_count": 5,
        "column_count": 2,
    }


def test_generator_preserves_duplicate_table_display_names() -> None:
    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(
            tables=(
                make_table_profile(
                    name="sales",
                    relation_name="sales",
                    row_count=10,
                    column_count=2,
                ),
                make_table_profile(
                    name="sales",
                    relation_name="sales_2",
                    row_count=20,
                    column_count=4,
                ),
            )
        ),
        issues=(),
    )

    insights = InsightGenerator().generate(analysis)

    table_insights = insights[1:]

    assert tuple(insight.table_name for insight in table_insights) == (
        "sales",
        "sales",
    )
    assert tuple(insight.relation_name for insight in table_insights) == (
        "sales",
        "sales_2",
    )


def test_generator_converts_table_quality_issue_to_insight() -> None:
    issue = make_quality_issue(
        table_name="orders",
        relation_name="orders",
        scope=QualityScope.TABLE,
        message="Table contains duplicate rows.",
        evidence={"duplicate_row_count": 2},
    )

    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(issue,),
    )

    insights = InsightGenerator().generate(analysis)

    quality_insight = insights[-1]

    assert quality_insight.insight_type is InsightType.DATA_QUALITY
    assert quality_insight.scope is InsightScope.TABLE
    assert quality_insight.table_name == "orders"
    assert quality_insight.relation_name == "orders"
    assert quality_insight.column_name is None
    assert quality_insight.message == "Table contains duplicate rows."
    assert quality_insight.evidence == {
        "duplicate_row_count": 2,
    }


def test_generator_converts_column_quality_issue_to_insight() -> None:
    issue = make_quality_issue(
        table_name="orders",
        relation_name="orders",
        scope=QualityScope.COLUMN,
        column_name="amount",
        message="Column contains missing values.",
        evidence={"missing_count": 3},
    )

    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(issue,),
    )

    insights = InsightGenerator().generate(analysis)

    quality_insight = insights[-1]

    assert quality_insight.insight_type is InsightType.DATA_QUALITY
    assert quality_insight.scope is InsightScope.COLUMN
    assert quality_insight.table_name == "orders"
    assert quality_insight.relation_name == "orders"
    assert quality_insight.column_name == "amount"
    assert quality_insight.message == "Column contains missing values."
    assert quality_insight.evidence == {
        "missing_count": 3,
    }


def test_generator_preserves_deterministic_insight_order() -> None:
    first_issue = make_quality_issue(
        table_name="orders",
        relation_name="orders",
        scope=QualityScope.TABLE,
        message="First issue.",
    )
    second_issue = make_quality_issue(
        table_name="customers",
        relation_name="customers",
        scope=QualityScope.COLUMN,
        column_name="email",
        message="Second issue.",
    )

    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(
            tables=(
                make_table_profile(
                    name="orders",
                    relation_name="orders",
                    row_count=10,
                    column_count=2,
                ),
                make_table_profile(
                    name="customers",
                    relation_name="customers",
                    row_count=5,
                    column_count=3,
                ),
            )
        ),
        issues=(
            first_issue,
            second_issue,
        ),
    )

    insights = InsightGenerator().generate(analysis)

    assert tuple(insight.insight_type for insight in insights) == (
        InsightType.DATASET_STRUCTURE,
        InsightType.TABLE_STRUCTURE,
        InsightType.TABLE_STRUCTURE,
        InsightType.DATA_QUALITY,
        InsightType.DATA_QUALITY,
    )

    assert tuple(insight.message for insight in insights[-2:]) == (
        "First issue.",
        "Second issue.",
    )


def test_empty_analysis_produces_dataset_structure_insight() -> None:
    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(),
    )

    insights = InsightGenerator().generate(analysis)

    assert len(insights) == 1
    assert insights[0].insight_type is InsightType.DATASET_STRUCTURE
    assert insights[0].scope is InsightScope.DATASET
    assert insights[0].message == "Dataset contains 0 table(s)."
    assert insights[0].evidence == {
        "table_count": 0,
        "total_row_count": 0,
        "total_column_count": 0,
    }


def test_generator_copies_quality_issue_evidence() -> None:
    issue = make_quality_issue(
        table_name="orders",
        relation_name="orders",
        scope=QualityScope.COLUMN,
        column_name="amount",
        evidence={"missing_count": 3},
    )

    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(issue,),
    )

    insights = InsightGenerator().generate(analysis)

    quality_insight = insights[-1]

    assert quality_insight.evidence == issue.evidence
    assert quality_insight.evidence is not issue.evidence
