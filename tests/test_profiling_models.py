import pandas as pd

from verisight.ingestion.schema import LogicalType
from verisight.profiling.models import (
    ColumnProfile,
    DatasetProfile,
    DatetimeStatistics,
    DuplicateStatistics,
    MissingValueStatistics,
    NumericStatistics,
    TableProfile,
    TextStatistics,
)


def test_numeric_statistics_store_descriptive_values() -> None:
    statistics = NumericStatistics(
        minimum=10,
        maximum=50,
        mean=30.0,
        median=30.0,
        standard_deviation=15.81,
    )

    assert statistics.minimum == 10
    assert statistics.maximum == 50
    assert statistics.mean == 30.0
    assert statistics.median == 30.0
    assert statistics.standard_deviation == 15.81


def test_numeric_statistics_allow_missing_standard_deviation() -> None:
    statistics = NumericStatistics(
        minimum=10,
        maximum=10,
        mean=10.0,
        median=10.0,
        standard_deviation=None,
    )

    assert statistics.standard_deviation is None


def test_text_statistics_store_descriptive_values() -> None:
    statistics = TextStatistics(
        minimum_length=0,
        maximum_length=10,
        mean_length=4.5,
        empty_count=1,
        empty_ratio=0.25,
        most_frequent_value="active",
        most_frequent_count=3,
        most_frequent_ratio=0.75,
    )

    assert statistics.minimum_length == 0
    assert statistics.maximum_length == 10
    assert statistics.mean_length == 4.5
    assert statistics.empty_count == 1
    assert statistics.empty_ratio == 0.25
    assert statistics.most_frequent_value == "active"
    assert statistics.most_frequent_count == 3
    assert statistics.most_frequent_ratio == 0.75


def test_datetime_statistics_store_descriptive_values() -> None:
    earliest = pd.Timestamp("2026-01-01")
    latest = pd.Timestamp("2026-01-10")

    statistics = DatetimeStatistics(
        earliest=earliest,
        latest=latest,
        span=pd.Timedelta(days=9),
        timezone=None,
    )

    assert statistics.earliest == earliest
    assert statistics.latest == latest
    assert statistics.span == pd.Timedelta(days=9)
    assert statistics.timezone is None


def test_missing_value_statistics_store_table_measurements() -> None:
    statistics = MissingValueStatistics(
        total_cell_count=12,
        missing_cell_count=4,
        missing_cell_ratio=4 / 12,
        rows_with_missing_count=3,
        rows_with_missing_ratio=0.75,
        fully_missing_row_count=1,
        fully_missing_row_ratio=0.25,
        columns_with_missing_count=2,
        columns_with_missing_ratio=2 / 3,
    )

    assert statistics.total_cell_count == 12
    assert statistics.missing_cell_count == 4
    assert statistics.missing_cell_ratio == 4 / 12
    assert statistics.rows_with_missing_count == 3
    assert statistics.rows_with_missing_ratio == 0.75
    assert statistics.fully_missing_row_count == 1
    assert statistics.fully_missing_row_ratio == 0.25
    assert statistics.columns_with_missing_count == 2
    assert statistics.columns_with_missing_ratio == 2 / 3


def test_duplicate_statistics_store_table_measurements() -> None:
    statistics = DuplicateStatistics(
        duplicate_row_count=2,
        duplicate_row_ratio=0.5,
        duplicate_group_row_count=3,
        duplicate_group_row_ratio=0.75,
    )

    assert statistics.duplicate_row_count == 2
    assert statistics.duplicate_row_ratio == 0.5
    assert statistics.duplicate_group_row_count == 3
    assert statistics.duplicate_group_row_ratio == 0.75


def test_column_profile_stores_structural_metrics() -> None:
    profile = ColumnProfile(
        name="value",
        logical_type=LogicalType.INTEGER,
        row_count=4,
        non_missing_count=3,
        missing_count=1,
        missing_ratio=0.25,
        distinct_count=3,
        distinct_ratio=1.0,
        minimum=10,
        maximum=30,
    )

    assert profile.name == "value"
    assert profile.logical_type is LogicalType.INTEGER
    assert profile.row_count == 4
    assert profile.non_missing_count == 3
    assert profile.missing_count == 1
    assert profile.missing_ratio == 0.25
    assert profile.distinct_count == 3
    assert profile.distinct_ratio == 1.0
    assert profile.minimum == 10
    assert profile.maximum == 30
    assert profile.numeric_statistics is None
    assert profile.text_statistics is None
    assert profile.datetime_statistics is None


def test_column_profile_can_store_numeric_statistics() -> None:
    statistics = NumericStatistics(
        minimum=10,
        maximum=30,
        mean=20.0,
        median=20.0,
        standard_deviation=10.0,
    )

    profile = ColumnProfile(
        name="amount",
        logical_type=LogicalType.FLOAT,
        row_count=3,
        non_missing_count=3,
        missing_count=0,
        missing_ratio=0.0,
        distinct_count=3,
        distinct_ratio=1.0,
        minimum=10.0,
        maximum=30.0,
        numeric_statistics=statistics,
    )

    assert profile.numeric_statistics is statistics
    assert profile.text_statistics is None


def test_column_profile_can_store_text_statistics() -> None:
    statistics = TextStatistics(
        minimum_length=1,
        maximum_length=5,
        mean_length=3.0,
        empty_count=0,
        empty_ratio=0.0,
    )

    profile = ColumnProfile(
        name="name",
        logical_type=LogicalType.STRING,
        row_count=3,
        non_missing_count=3,
        missing_count=0,
        missing_ratio=0.0,
        distinct_count=3,
        distinct_ratio=1.0,
        text_statistics=statistics,
    )

    assert profile.text_statistics is statistics
    assert profile.numeric_statistics is None


def test_column_profile_has_no_text_statistics_by_default() -> None:
    profile = ColumnProfile(
        name="value",
        logical_type=LogicalType.INTEGER,
        row_count=1,
        non_missing_count=1,
        missing_count=0,
        missing_ratio=0.0,
        distinct_count=1,
        distinct_ratio=1.0,
    )

    assert profile.text_statistics is None


def test_column_profile_has_no_datetime_statistics_by_default() -> None:
    profile = ColumnProfile(
        name="value",
        logical_type=LogicalType.INTEGER,
        row_count=1,
        non_missing_count=1,
        missing_count=0,
        missing_ratio=0.0,
        distinct_count=1,
        distinct_ratio=1.0,
    )

    assert profile.datetime_statistics is None


def test_table_profile_stores_table_metrics() -> None:
    profile = TableProfile(
        name="orders",
        row_count=10,
        column_count=3,
        duplicate_row_count=2,
        duplicate_row_ratio=0.2,
        columns=(),
    )

    assert profile.name == "orders"
    assert profile.row_count == 10
    assert profile.column_count == 3
    assert profile.duplicate_row_count == 2
    assert profile.duplicate_row_ratio == 0.2
    assert profile.columns == ()


def test_table_profile_has_no_missing_statistics_by_default() -> None:
    profile = TableProfile(
        name="orders",
        row_count=0,
        column_count=0,
        duplicate_row_count=0,
        duplicate_row_ratio=0.0,
        columns=(),
    )

    assert profile.missing_value_statistics is None


def test_table_profile_has_no_duplicate_statistics_by_default() -> None:
    profile = TableProfile(
        name="orders",
        row_count=0,
        column_count=0,
        duplicate_row_count=0,
        duplicate_row_ratio=0.0,
        columns=(),
    )

    assert profile.duplicate_statistics is None


def test_dataset_profile_reports_table_count() -> None:
    table = TableProfile(
        name="orders",
        row_count=10,
        column_count=3,
        duplicate_row_count=0,
        duplicate_row_ratio=0.0,
        columns=(),
    )

    profile = DatasetProfile(tables=(table,))

    assert profile.tables == (table,)
    assert profile.table_count == 1


def test_empty_dataset_profile_has_zero_tables() -> None:
    profile = DatasetProfile(tables=())

    assert profile.table_count == 0
