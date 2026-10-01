import pytest

from verisight.quality.models import (
    QualityIssue,
    QualityIssueType,
    QualityScope,
    QualitySeverity,
)


def test_quality_issue_type_values_are_stable() -> None:
    assert QualityIssueType.MISSING_VALUES.value == "missing_values"
    assert QualityIssueType.FULLY_MISSING_ROWS.value == "fully_missing_rows"
    assert QualityIssueType.DUPLICATE_ROWS.value == "duplicate_rows"
    assert QualityIssueType.EMPTY_STRINGS.value == "empty_strings"
    assert QualityIssueType.CONSTANT_COLUMN.value == "constant_column"
    assert QualityIssueType.HIGH_CARDINALITY.value == "high_cardinality"


def test_quality_severity_values_are_stable() -> None:
    assert QualitySeverity.INFO.value == "info"
    assert QualitySeverity.WARNING.value == "warning"
    assert QualitySeverity.ERROR.value == "error"


def test_quality_scope_values_are_stable() -> None:
    assert QualityScope.TABLE.value == "table"
    assert QualityScope.COLUMN.value == "column"


def test_quality_issue_stores_table_level_finding() -> None:
    issue = QualityIssue(
        issue_type=QualityIssueType.DUPLICATE_ROWS,
        severity=QualitySeverity.WARNING,
        scope=QualityScope.TABLE,
        table_name="Orders 2026",
        relation_name="orders_2026",
        message="Table contains duplicate rows.",
        affected_count=5,
        affected_ratio=0.25,
        evidence={
            "duplicate_row_count": 5,
            "row_count": 20,
        },
    )

    assert issue.issue_type is QualityIssueType.DUPLICATE_ROWS
    assert issue.severity is QualitySeverity.WARNING
    assert issue.scope is QualityScope.TABLE
    assert issue.table_name == "Orders 2026"
    assert issue.relation_name == "orders_2026"
    assert issue.column_name is None
    assert issue.message == "Table contains duplicate rows."
    assert issue.affected_count == 5
    assert issue.affected_ratio == 0.25
    assert issue.evidence == {
        "duplicate_row_count": 5,
        "row_count": 20,
    }


def test_quality_issue_stores_column_level_finding() -> None:
    issue = QualityIssue(
        issue_type=QualityIssueType.MISSING_VALUES,
        severity=QualitySeverity.WARNING,
        scope=QualityScope.COLUMN,
        table_name="Orders 2026",
        relation_name="orders_2026",
        column_name="amount",
        message="Column contains missing values.",
        affected_count=3,
        affected_ratio=0.15,
        evidence={
            "missing_count": 3,
            "non_missing_count": 17,
            "row_count": 20,
        },
    )

    assert issue.scope is QualityScope.COLUMN
    assert issue.table_name == "Orders 2026"
    assert issue.relation_name == "orders_2026"
    assert issue.column_name == "amount"
    assert issue.affected_count == 3
    assert issue.affected_ratio == 0.15


def test_quality_issue_allows_no_affected_measurement() -> None:
    issue = QualityIssue(
        issue_type=QualityIssueType.CONSTANT_COLUMN,
        severity=QualitySeverity.INFO,
        scope=QualityScope.COLUMN,
        table_name="orders",
        relation_name="orders",
        column_name="status",
        message="Column contains only one distinct non-missing value.",
    )

    assert issue.affected_count is None
    assert issue.affected_ratio is None


def test_quality_issue_has_independent_evidence_dictionary() -> None:
    first = QualityIssue(
        issue_type=QualityIssueType.CONSTANT_COLUMN,
        severity=QualitySeverity.INFO,
        scope=QualityScope.COLUMN,
        table_name="orders",
        relation_name="orders",
        column_name="status",
        message="Constant column.",
    )

    second = QualityIssue(
        issue_type=QualityIssueType.CONSTANT_COLUMN,
        severity=QualitySeverity.INFO,
        scope=QualityScope.COLUMN,
        table_name="orders",
        relation_name="orders",
        column_name="country",
        message="Constant column.",
    )

    assert first.evidence == {}
    assert second.evidence == {}
    assert first.evidence is not second.evidence


def test_quality_issue_is_immutable() -> None:
    issue = QualityIssue(
        issue_type=QualityIssueType.DUPLICATE_ROWS,
        severity=QualitySeverity.WARNING,
        scope=QualityScope.TABLE,
        table_name="orders",
        relation_name="orders",
        message="Table contains duplicate rows.",
    )

    assert issue.table_name == "orders"
    assert issue.relation_name == "orders"


def test_quality_issue_evidence_is_immutable() -> None:
    issue = QualityIssue(
        issue_type=QualityIssueType.MISSING_VALUES,
        severity=QualitySeverity.WARNING,
        scope=QualityScope.COLUMN,
        table_name="orders",
        relation_name="orders",
        column_name="amount",
        message="Column contains missing values.",
        evidence={"missing_count": 3},
    )

    with pytest.raises(TypeError):
        issue.evidence["missing_count"] = 999  # type: ignore[index]


def test_quality_issue_copies_evidence_on_construction() -> None:
    evidence: dict[str, object] = {"missing_count": 3}

    issue = QualityIssue(
        issue_type=QualityIssueType.MISSING_VALUES,
        severity=QualitySeverity.WARNING,
        scope=QualityScope.COLUMN,
        table_name="orders",
        relation_name="orders",
        column_name="amount",
        message="Column contains missing values.",
        evidence=evidence,
    )

    evidence["missing_count"] = 999

    assert issue.evidence["missing_count"] == 3
