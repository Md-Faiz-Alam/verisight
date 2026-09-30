from verisight.ingestion.schema import LogicalType
from verisight.profiling.models import (
    ColumnProfile,
    DuplicateStatistics,
    MissingValueStatistics,
    TableProfile,
    TextStatistics,
)
from verisight.quality.models import (
    QualityIssueType,
    QualityScope,
    QualitySeverity,
)
from verisight.quality.rules import QualityRuleEngine


def test_clean_table_produces_no_quality_issues() -> None:
    profile = TableProfile(
        name="orders",
        row_count=3,
        column_count=1,
        duplicate_row_count=0,
        duplicate_row_ratio=0.0,
        columns=(
            ColumnProfile(
                name="amount",
                logical_type=LogicalType.INTEGER,
                row_count=3,
                non_missing_count=3,
                missing_count=0,
                missing_ratio=0.0,
                distinct_count=3,
                distinct_ratio=1.0,
            ),
        ),
    )

    issues = QualityRuleEngine().evaluate(profile)

    assert issues == ()


def test_missing_values_produce_column_warning() -> None:
    profile = TableProfile(
        name="orders",
        row_count=4,
        column_count=1,
        duplicate_row_count=0,
        duplicate_row_ratio=0.0,
        columns=(
            ColumnProfile(
                name="amount",
                logical_type=LogicalType.FLOAT,
                row_count=4,
                non_missing_count=3,
                missing_count=1,
                missing_ratio=0.25,
                distinct_count=3,
                distinct_ratio=1.0,
            ),
        ),
    )

    issues = QualityRuleEngine().evaluate(profile)

    assert len(issues) == 1

    issue = issues[0]

    assert issue.issue_type is QualityIssueType.MISSING_VALUES
    assert issue.severity is QualitySeverity.WARNING
    assert issue.scope is QualityScope.COLUMN
    assert issue.table_name == "orders"
    assert issue.column_name == "amount"
    assert issue.affected_count == 1
    assert issue.affected_ratio == 0.25
    assert issue.evidence == {
        "missing_count": 1,
        "non_missing_count": 3,
        "row_count": 4,
    }


def test_empty_strings_produce_column_warning() -> None:
    profile = TableProfile(
        name="customers",
        row_count=4,
        column_count=1,
        duplicate_row_count=0,
        duplicate_row_ratio=0.0,
        columns=(
            ColumnProfile(
                name="name",
                logical_type=LogicalType.STRING,
                row_count=4,
                non_missing_count=4,
                missing_count=0,
                missing_ratio=0.0,
                distinct_count=3,
                distinct_ratio=0.75,
                text_statistics=TextStatistics(
                    minimum_length=0,
                    maximum_length=5,
                    mean_length=2.5,
                    empty_count=1,
                    empty_ratio=0.25,
                ),
            ),
        ),
    )

    issues = QualityRuleEngine().evaluate(profile)

    assert len(issues) == 1

    issue = issues[0]

    assert issue.issue_type is QualityIssueType.EMPTY_STRINGS
    assert issue.severity is QualitySeverity.WARNING
    assert issue.scope is QualityScope.COLUMN
    assert issue.column_name == "name"
    assert issue.affected_count == 1
    assert issue.affected_ratio == 0.25


def test_constant_column_produces_info_issue() -> None:
    profile = TableProfile(
        name="orders",
        row_count=4,
        column_count=1,
        duplicate_row_count=0,
        duplicate_row_ratio=0.0,
        columns=(
            ColumnProfile(
                name="status",
                logical_type=LogicalType.STRING,
                row_count=4,
                non_missing_count=4,
                missing_count=0,
                missing_ratio=0.0,
                distinct_count=1,
                distinct_ratio=0.25,
            ),
        ),
    )

    issues = QualityRuleEngine().evaluate(profile)

    assert len(issues) == 1

    issue = issues[0]

    assert issue.issue_type is QualityIssueType.CONSTANT_COLUMN
    assert issue.severity is QualitySeverity.INFO
    assert issue.scope is QualityScope.COLUMN
    assert issue.column_name == "status"
    assert issue.affected_count == 4
    assert issue.affected_ratio == 1.0


def test_single_observed_value_is_not_flagged_as_constant() -> None:
    profile = TableProfile(
        name="orders",
        row_count=1,
        column_count=1,
        duplicate_row_count=0,
        duplicate_row_ratio=0.0,
        columns=(
            ColumnProfile(
                name="status",
                logical_type=LogicalType.STRING,
                row_count=1,
                non_missing_count=1,
                missing_count=0,
                missing_ratio=0.0,
                distinct_count=1,
                distinct_ratio=1.0,
            ),
        ),
    )

    issues = QualityRuleEngine().evaluate(profile)

    assert issues == ()


def test_all_missing_column_is_not_flagged_as_constant() -> None:
    profile = TableProfile(
        name="orders",
        row_count=3,
        column_count=1,
        duplicate_row_count=0,
        duplicate_row_ratio=0.0,
        columns=(
            ColumnProfile(
                name="status",
                logical_type=LogicalType.STRING,
                row_count=3,
                non_missing_count=0,
                missing_count=3,
                missing_ratio=1.0,
                distinct_count=0,
                distinct_ratio=0.0,
            ),
        ),
    )

    issues = QualityRuleEngine().evaluate(profile)

    assert len(issues) == 1
    assert issues[0].issue_type is QualityIssueType.MISSING_VALUES


def test_fully_missing_rows_produce_table_warning() -> None:
    profile = TableProfile(
        name="orders",
        row_count=4,
        column_count=2,
        duplicate_row_count=0,
        duplicate_row_ratio=0.0,
        columns=(),
        missing_value_statistics=MissingValueStatistics(
            total_cell_count=8,
            missing_cell_count=3,
            missing_cell_ratio=3 / 8,
            rows_with_missing_count=2,
            rows_with_missing_ratio=0.5,
            fully_missing_row_count=1,
            fully_missing_row_ratio=0.25,
            columns_with_missing_count=2,
            columns_with_missing_ratio=1.0,
        ),
    )

    issues = QualityRuleEngine().evaluate(profile)

    assert len(issues) == 1

    issue = issues[0]

    assert issue.issue_type is QualityIssueType.FULLY_MISSING_ROWS
    assert issue.severity is QualitySeverity.WARNING
    assert issue.scope is QualityScope.TABLE
    assert issue.column_name is None
    assert issue.affected_count == 1
    assert issue.affected_ratio == 0.25


def test_duplicate_rows_produce_table_warning() -> None:
    profile = TableProfile(
        name="orders",
        row_count=4,
        column_count=2,
        duplicate_row_count=2,
        duplicate_row_ratio=0.5,
        columns=(),
        duplicate_statistics=DuplicateStatistics(
            duplicate_row_count=2,
            duplicate_row_ratio=0.5,
            duplicate_group_row_count=3,
            duplicate_group_row_ratio=0.75,
        ),
    )

    issues = QualityRuleEngine().evaluate(profile)

    assert len(issues) == 1

    issue = issues[0]

    assert issue.issue_type is QualityIssueType.DUPLICATE_ROWS
    assert issue.severity is QualitySeverity.WARNING
    assert issue.scope is QualityScope.TABLE
    assert issue.column_name is None
    assert issue.affected_count == 2
    assert issue.affected_ratio == 0.5
    assert issue.evidence == {
        "duplicate_row_count": 2,
        "duplicate_group_row_count": 3,
        "row_count": 4,
    }


def test_zero_duplicate_statistics_produce_no_issue() -> None:
    profile = TableProfile(
        name="orders",
        row_count=3,
        column_count=1,
        duplicate_row_count=0,
        duplicate_row_ratio=0.0,
        columns=(),
        duplicate_statistics=DuplicateStatistics(
            duplicate_row_count=0,
            duplicate_row_ratio=0.0,
            duplicate_group_row_count=0,
            duplicate_group_row_ratio=0.0,
        ),
    )

    issues = QualityRuleEngine().evaluate(profile)

    assert issues == ()


def test_multiple_findings_are_returned_deterministically() -> None:
    profile = TableProfile(
        name="orders",
        row_count=4,
        column_count=1,
        duplicate_row_count=1,
        duplicate_row_ratio=0.25,
        columns=(
            ColumnProfile(
                name="status",
                logical_type=LogicalType.STRING,
                row_count=4,
                non_missing_count=3,
                missing_count=1,
                missing_ratio=0.25,
                distinct_count=1,
                distinct_ratio=1 / 3,
                text_statistics=TextStatistics(
                    minimum_length=0,
                    maximum_length=0,
                    mean_length=0.0,
                    empty_count=3,
                    empty_ratio=1.0,
                ),
            ),
        ),
        missing_value_statistics=MissingValueStatistics(
            total_cell_count=4,
            missing_cell_count=1,
            missing_cell_ratio=0.25,
            rows_with_missing_count=1,
            rows_with_missing_ratio=0.25,
            fully_missing_row_count=1,
            fully_missing_row_ratio=0.25,
            columns_with_missing_count=1,
            columns_with_missing_ratio=1.0,
        ),
        duplicate_statistics=DuplicateStatistics(
            duplicate_row_count=1,
            duplicate_row_ratio=0.25,
            duplicate_group_row_count=2,
            duplicate_group_row_ratio=0.5,
        ),
    )

    issues = QualityRuleEngine().evaluate(profile)

    assert tuple(issue.issue_type for issue in issues) == (
        QualityIssueType.MISSING_VALUES,
        QualityIssueType.EMPTY_STRINGS,
        QualityIssueType.CONSTANT_COLUMN,
        QualityIssueType.FULLY_MISSING_ROWS,
        QualityIssueType.DUPLICATE_ROWS,
    )
