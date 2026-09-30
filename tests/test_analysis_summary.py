from dataclasses import FrozenInstanceError

import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.summary import AnalysisSummarizer, AnalysisSummary
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
    """Create a minimal table profile for summary tests."""

    return TableProfile(
        name=name,
        relation_name=relation_name,
        row_count=row_count,
        column_count=column_count,
        duplicate_row_count=0,
        duplicate_row_ratio=0.0,
        columns=(),
    )


def make_issue(
    *,
    table_name: str,
    relation_name: str,
    issue_type: QualityIssueType,
    severity: QualitySeverity,
    scope: QualityScope,
    column_name: str | None = None,
) -> QualityIssue:
    """Create a quality issue for summary tests."""

    return QualityIssue(
        issue_type=issue_type,
        severity=severity,
        scope=scope,
        table_name=table_name,
        relation_name=relation_name,
        column_name=column_name,
        message="Test quality issue.",
    )


def test_summarizes_dataset_structure() -> None:
    profile = DatasetProfile(
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
    )

    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=profile,
        issues=(),
    )

    summary = AnalysisSummarizer().summarize(analysis)

    assert summary.table_count == 2
    assert summary.total_row_count == 15
    assert summary.total_column_count == 5


def test_summarizes_issue_severities() -> None:
    issues = (
        make_issue(
            table_name="orders",
            relation_name="orders",
            issue_type=QualityIssueType.CONSTANT_COLUMN,
            severity=QualitySeverity.INFO,
            scope=QualityScope.COLUMN,
            column_name="status",
        ),
        make_issue(
            table_name="orders",
            relation_name="orders",
            issue_type=QualityIssueType.MISSING_VALUES,
            severity=QualitySeverity.WARNING,
            scope=QualityScope.COLUMN,
            column_name="amount",
        ),
        make_issue(
            table_name="orders",
            relation_name="orders",
            issue_type=QualityIssueType.DUPLICATE_ROWS,
            severity=QualitySeverity.ERROR,
            scope=QualityScope.TABLE,
        ),
    )

    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=issues,
    )

    summary = AnalysisSummarizer().summarize(analysis)

    assert summary.issue_count == 3
    assert summary.info_issue_count == 1
    assert summary.warning_issue_count == 1
    assert summary.error_issue_count == 1


def test_summarizes_issue_scopes() -> None:
    issues = (
        make_issue(
            table_name="orders",
            relation_name="orders",
            issue_type=QualityIssueType.MISSING_VALUES,
            severity=QualitySeverity.WARNING,
            scope=QualityScope.COLUMN,
            column_name="amount",
        ),
        make_issue(
            table_name="orders",
            relation_name="orders",
            issue_type=QualityIssueType.EMPTY_STRINGS,
            severity=QualitySeverity.WARNING,
            scope=QualityScope.COLUMN,
            column_name="status",
        ),
        make_issue(
            table_name="orders",
            relation_name="orders",
            issue_type=QualityIssueType.DUPLICATE_ROWS,
            severity=QualitySeverity.WARNING,
            scope=QualityScope.TABLE,
        ),
    )

    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=issues,
    )

    summary = AnalysisSummarizer().summarize(analysis)

    assert summary.table_issue_count == 1
    assert summary.column_issue_count == 2


def test_reports_distinct_affected_tables_by_relation_identity() -> None:
    issues = (
        make_issue(
            table_name="sales",
            relation_name="sales",
            issue_type=QualityIssueType.MISSING_VALUES,
            severity=QualitySeverity.WARNING,
            scope=QualityScope.COLUMN,
            column_name="amount",
        ),
        make_issue(
            table_name="sales",
            relation_name="sales",
            issue_type=QualityIssueType.DUPLICATE_ROWS,
            severity=QualitySeverity.WARNING,
            scope=QualityScope.TABLE,
        ),
        make_issue(
            table_name="sales",
            relation_name="sales_2",
            issue_type=QualityIssueType.EMPTY_STRINGS,
            severity=QualitySeverity.WARNING,
            scope=QualityScope.COLUMN,
            column_name="status",
        ),
    )

    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=issues,
    )

    summary = AnalysisSummarizer().summarize(analysis)

    assert summary.affected_table_count == 2
    assert summary.affected_relation_names == (
        "sales",
        "sales_2",
    )


def test_preserves_first_affected_table_order() -> None:
    issues = (
        make_issue(
            table_name="customers",
            relation_name="customers",
            issue_type=QualityIssueType.EMPTY_STRINGS,
            severity=QualitySeverity.WARNING,
            scope=QualityScope.COLUMN,
            column_name="name",
        ),
        make_issue(
            table_name="orders",
            relation_name="orders",
            issue_type=QualityIssueType.DUPLICATE_ROWS,
            severity=QualitySeverity.WARNING,
            scope=QualityScope.TABLE,
        ),
        make_issue(
            table_name="customers",
            relation_name="customers",
            issue_type=QualityIssueType.MISSING_VALUES,
            severity=QualitySeverity.WARNING,
            scope=QualityScope.COLUMN,
            column_name="email",
        ),
    )

    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=issues,
    )

    summary = AnalysisSummarizer().summarize(analysis)

    assert summary.affected_relation_names == (
        "customers",
        "orders",
    )


def test_empty_analysis_produces_zero_summary() -> None:
    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(),
    )

    summary = AnalysisSummarizer().summarize(analysis)

    assert summary.table_count == 0
    assert summary.total_row_count == 0
    assert summary.total_column_count == 0

    assert summary.issue_count == 0
    assert summary.info_issue_count == 0
    assert summary.warning_issue_count == 0
    assert summary.error_issue_count == 0

    assert summary.table_issue_count == 0
    assert summary.column_issue_count == 0

    assert summary.affected_table_count == 0
    assert summary.affected_relation_names == ()


def test_analysis_summary_is_immutable() -> None:
    summary = AnalysisSummary(
        table_count=1,
        total_row_count=10,
        total_column_count=3,
        issue_count=2,
        info_issue_count=0,
        warning_issue_count=2,
        error_issue_count=0,
        table_issue_count=1,
        column_issue_count=1,
        affected_relation_names=("orders",),
    )

    with pytest.raises(FrozenInstanceError):
        summary.table_count = 2  # type: ignore[misc]
