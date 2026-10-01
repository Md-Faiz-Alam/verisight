from verisight.ingestion.schema import LogicalType
from verisight.profiling.models import (
    ColumnProfile,
    DuplicateStatistics,
    MissingValueStatistics,
    NumericStatistics,
    TableProfile,
    TextStatistics,
)
from verisight.quality.models import (
    QualityIssueType,
    QualityScope,
    QualitySeverity,
)
from verisight.quality.rules import QualityRuleEngine


def make_missing_statistics(
    *,
    row_count: int,
    column_count: int,
    missing_cell_count: int = 0,
    rows_with_missing_count: int = 0,
    fully_missing_row_count: int = 0,
    columns_with_missing_count: int = 0,
) -> MissingValueStatistics:
    """Create deterministic table-level missing-value statistics."""

    total_cell_count = row_count * column_count

    return MissingValueStatistics(
        total_cell_count=total_cell_count,
        missing_cell_count=missing_cell_count,
        missing_cell_ratio=(
            missing_cell_count / total_cell_count if total_cell_count > 0 else 0.0
        ),
        rows_with_missing_count=rows_with_missing_count,
        rows_with_missing_ratio=(
            rows_with_missing_count / row_count if row_count > 0 else 0.0
        ),
        fully_missing_row_count=fully_missing_row_count,
        fully_missing_row_ratio=(
            fully_missing_row_count / row_count if row_count > 0 else 0.0
        ),
        columns_with_missing_count=columns_with_missing_count,
        columns_with_missing_ratio=(
            columns_with_missing_count / column_count if column_count > 0 else 0.0
        ),
    )


def make_duplicate_statistics(
    *,
    row_count: int,
    duplicate_row_count: int = 0,
    duplicate_group_row_count: int = 0,
) -> DuplicateStatistics:
    """Create deterministic table-level duplicate statistics."""

    return DuplicateStatistics(
        duplicate_row_count=duplicate_row_count,
        duplicate_row_ratio=(duplicate_row_count / row_count if row_count > 0 else 0.0),
        duplicate_group_row_count=duplicate_group_row_count,
        duplicate_group_row_ratio=(
            duplicate_group_row_count / row_count if row_count > 0 else 0.0
        ),
    )


def make_table_profile(
    *,
    name: str,
    relation_name: str,
    row_count: int,
    column_count: int,
    columns: tuple[ColumnProfile, ...] = (),
    missing_value_statistics: MissingValueStatistics | None = None,
    duplicate_statistics: DuplicateStatistics | None = None,
) -> TableProfile:
    """Create a table profile with canonical table-level statistics."""

    return TableProfile(
        name=name,
        relation_name=relation_name,
        row_count=row_count,
        column_count=column_count,
        columns=columns,
        missing_value_statistics=(
            missing_value_statistics
            if missing_value_statistics is not None
            else make_missing_statistics(
                row_count=row_count,
                column_count=column_count,
            )
        ),
        duplicate_statistics=(
            duplicate_statistics
            if duplicate_statistics is not None
            else make_duplicate_statistics(row_count=row_count)
        ),
    )


def test_clean_table_produces_no_quality_issues() -> None:
    profile = make_table_profile(
        name="orders",
        relation_name="orders",
        row_count=3,
        column_count=1,
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
    profile = make_table_profile(
        name="orders",
        relation_name="orders",
        row_count=4,
        column_count=1,
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
    profile = make_table_profile(
        name="customers",
        relation_name="customers",
        row_count=4,
        column_count=1,
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
    profile = make_table_profile(
        name="orders",
        relation_name="orders",
        row_count=4,
        column_count=1,
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
    profile = make_table_profile(
        name="orders",
        relation_name="orders",
        row_count=1,
        column_count=1,
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


def test_all_missing_column_produces_entirely_missing_warning() -> None:
    profile = make_table_profile(
        name="orders",
        relation_name="orders",
        row_count=3,
        column_count=1,
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

    issue = issues[0]

    assert issue.issue_type is QualityIssueType.ENTIRELY_MISSING_COLUMN
    assert issue.severity is QualitySeverity.WARNING
    assert issue.scope is QualityScope.COLUMN
    assert issue.table_name == "orders"
    assert issue.relation_name == "orders"
    assert issue.column_name == "status"
    assert issue.message == "Column is entirely missing."
    assert issue.affected_count == 3
    assert issue.affected_ratio == 1.0
    assert issue.evidence == {
        "missing_count": 3,
        "non_missing_count": 0,
        "row_count": 3,
    }


def test_empty_column_in_zero_row_table_is_not_entirely_missing() -> None:
    profile = make_table_profile(
        name="orders",
        relation_name="orders",
        row_count=0,
        column_count=1,
        columns=(
            ColumnProfile(
                name="status",
                logical_type=LogicalType.STRING,
                row_count=0,
                non_missing_count=0,
                missing_count=0,
                missing_ratio=0.0,
                distinct_count=0,
                distinct_ratio=0.0,
            ),
        ),
    )

    issues = QualityRuleEngine().evaluate(profile)

    assert issues == ()


def test_high_cardinality_string_column_produces_info_issue() -> None:
    profile = make_table_profile(
        name="customers",
        relation_name="customers",
        row_count=20,
        column_count=1,
        columns=(
            ColumnProfile(
                name="email",
                logical_type=LogicalType.STRING,
                row_count=20,
                non_missing_count=20,
                missing_count=0,
                missing_ratio=0.0,
                distinct_count=18,
                distinct_ratio=0.9,
            ),
        ),
    )

    issues = QualityRuleEngine().evaluate(profile)

    assert len(issues) == 1

    issue = issues[0]

    assert issue.issue_type is QualityIssueType.HIGH_CARDINALITY
    assert issue.severity is QualitySeverity.INFO
    assert issue.scope is QualityScope.COLUMN
    assert issue.table_name == "customers"
    assert issue.column_name == "email"
    assert issue.affected_count == 18
    assert issue.affected_ratio == 0.9
    assert issue.evidence == {
        "distinct_count": 18,
        "non_missing_count": 20,
        "distinct_ratio": 0.9,
        "minimum_non_missing_count": 20,
        "distinct_ratio_threshold": 0.9,
    }


def test_high_cardinality_requires_minimum_observed_values() -> None:
    profile = make_table_profile(
        name="customers",
        relation_name="customers",
        row_count=19,
        column_count=1,
        columns=(
            ColumnProfile(
                name="email",
                logical_type=LogicalType.STRING,
                row_count=19,
                non_missing_count=19,
                missing_count=0,
                missing_ratio=0.0,
                distinct_count=19,
                distinct_ratio=1.0,
            ),
        ),
    )

    issues = QualityRuleEngine().evaluate(profile)

    assert issues == ()


def test_high_cardinality_requires_threshold_ratio() -> None:
    profile = make_table_profile(
        name="customers",
        relation_name="customers",
        row_count=20,
        column_count=1,
        columns=(
            ColumnProfile(
                name="city",
                logical_type=LogicalType.STRING,
                row_count=20,
                non_missing_count=20,
                missing_count=0,
                missing_ratio=0.0,
                distinct_count=17,
                distinct_ratio=0.85,
            ),
        ),
    )

    issues = QualityRuleEngine().evaluate(profile)

    assert issues == ()


def test_high_cardinality_does_not_flag_numeric_column() -> None:
    profile = make_table_profile(
        name="orders",
        relation_name="orders",
        row_count=20,
        column_count=1,
        columns=(
            ColumnProfile(
                name="order_id",
                logical_type=LogicalType.INTEGER,
                row_count=20,
                non_missing_count=20,
                missing_count=0,
                missing_ratio=0.0,
                distinct_count=20,
                distinct_ratio=1.0,
            ),
        ),
    )

    issues = QualityRuleEngine().evaluate(profile)

    assert issues == ()


def test_high_cardinality_uses_non_missing_observations() -> None:
    profile = make_table_profile(
        name="customers",
        relation_name="customers",
        row_count=25,
        column_count=1,
        columns=(
            ColumnProfile(
                name="email",
                logical_type=LogicalType.STRING,
                row_count=25,
                non_missing_count=20,
                missing_count=5,
                missing_ratio=0.2,
                distinct_count=18,
                distinct_ratio=0.9,
            ),
        ),
    )

    issues = QualityRuleEngine().evaluate(profile)

    assert tuple(issue.issue_type for issue in issues) == (
        QualityIssueType.MISSING_VALUES,
        QualityIssueType.HIGH_CARDINALITY,
    )


def test_fully_missing_rows_produce_table_warning() -> None:
    profile = make_table_profile(
        name="orders",
        relation_name="orders",
        row_count=4,
        column_count=2,
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
    profile = make_table_profile(
        name="orders",
        relation_name="orders",
        row_count=4,
        column_count=2,
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
    profile = make_table_profile(
        name="orders",
        relation_name="orders",
        row_count=3,
        column_count=1,
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
    profile = make_table_profile(
        name="orders",
        relation_name="orders",
        row_count=4,
        column_count=1,
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


def test_non_finite_numeric_values_produce_column_warning() -> None:
    profile = make_table_profile(
        name="measurements",
        relation_name="measurements",
        row_count=4,
        column_count=1,
        columns=(
            ColumnProfile(
                name="temperature",
                logical_type=LogicalType.FLOAT,
                row_count=4,
                non_missing_count=4,
                missing_count=0,
                missing_ratio=0.0,
                distinct_count=4,
                distinct_ratio=1.0,
                minimum=1.0,
                maximum=2.0,
                numeric_statistics=NumericStatistics(
                    minimum=1.0,
                    maximum=2.0,
                    mean=1.5,
                    median=1.5,
                    standard_deviation=0.5,
                    non_finite_count=2,
                    non_finite_ratio=0.5,
                ),
            ),
        ),
    )

    issues = QualityRuleEngine().evaluate(profile)

    assert len(issues) == 1

    issue = issues[0]

    assert issue.issue_type is QualityIssueType.NON_FINITE_VALUES
    assert issue.severity is QualitySeverity.WARNING
    assert issue.scope is QualityScope.COLUMN
    assert issue.table_name == "measurements"
    assert issue.relation_name == "measurements"
    assert issue.column_name == "temperature"
    assert issue.affected_count == 2
    assert issue.affected_ratio == 0.5
    assert issue.evidence == {
        "non_finite_count": 2,
        "non_missing_count": 4,
        "non_finite_ratio": 0.5,
    }


def test_finite_numeric_values_produce_no_non_finite_issue() -> None:
    profile = make_table_profile(
        name="measurements",
        relation_name="measurements",
        row_count=3,
        column_count=1,
        columns=(
            ColumnProfile(
                name="temperature",
                logical_type=LogicalType.FLOAT,
                row_count=3,
                non_missing_count=3,
                missing_count=0,
                missing_ratio=0.0,
                distinct_count=3,
                distinct_ratio=1.0,
                minimum=1.0,
                maximum=3.0,
                numeric_statistics=NumericStatistics(
                    minimum=1.0,
                    maximum=3.0,
                    mean=2.0,
                    median=2.0,
                    standard_deviation=1.0,
                    non_finite_count=0,
                    non_finite_ratio=0.0,
                ),
            ),
        ),
    )

    issues = QualityRuleEngine().evaluate(profile)

    assert issues == ()
