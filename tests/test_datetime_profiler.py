import pandas as pd

from verisight.ingestion.schema import LogicalType
from verisight.profiling.column import ColumnProfiler


def test_profiles_datetime_range() -> None:
    series = pd.Series(
        pd.to_datetime(
            [
                "2026-01-10",
                "2026-01-01",
                "2026-01-05",
            ]
        )
    )

    profile = ColumnProfiler().profile(
        name="event_time",
        series=series,
        logical_type=LogicalType.DATETIME,
    )

    statistics = profile.datetime_statistics
    assert statistics is not None

    assert statistics.earliest == pd.Timestamp("2026-01-01")
    assert statistics.latest == pd.Timestamp("2026-01-10")
    assert statistics.span == pd.Timedelta(days=9)
    assert statistics.timezone is None

    assert profile.minimum == pd.Timestamp("2026-01-01")
    assert profile.maximum == pd.Timestamp("2026-01-10")


def test_datetime_statistics_ignore_missing_values() -> None:
    series = pd.Series(
        [
            pd.Timestamp("2026-01-01"),
            pd.NaT,
            pd.Timestamp("2026-01-04"),
            pd.NaT,
        ],
        dtype="datetime64[ns]",
    )

    profile = ColumnProfiler().profile(
        name="event_time",
        series=series,
        logical_type=LogicalType.DATETIME,
    )

    statistics = profile.datetime_statistics
    assert statistics is not None

    assert profile.row_count == 4
    assert profile.non_missing_count == 2
    assert profile.missing_count == 2

    assert statistics.earliest == pd.Timestamp("2026-01-01")
    assert statistics.latest == pd.Timestamp("2026-01-04")
    assert statistics.span == pd.Timedelta(days=3)


def test_single_datetime_has_zero_span() -> None:
    series = pd.Series(
        pd.to_datetime(
            [
                "2026-05-15",
            ]
        )
    )

    profile = ColumnProfiler().profile(
        name="created_at",
        series=series,
        logical_type=LogicalType.DATETIME,
    )

    statistics = profile.datetime_statistics
    assert statistics is not None

    assert statistics.earliest == pd.Timestamp("2026-05-15")
    assert statistics.latest == pd.Timestamp("2026-05-15")
    assert statistics.span == pd.Timedelta(0)


def test_all_missing_datetime_has_no_datetime_statistics() -> None:
    series = pd.Series(
        [pd.NaT, pd.NaT],
        dtype="datetime64[ns]",
    )

    profile = ColumnProfiler().profile(
        name="created_at",
        series=series,
        logical_type=LogicalType.DATETIME,
    )

    assert profile.datetime_statistics is None
    assert profile.minimum is None
    assert profile.maximum is None


def test_empty_datetime_has_no_datetime_statistics() -> None:
    series = pd.Series([], dtype="datetime64[ns]")

    profile = ColumnProfiler().profile(
        name="created_at",
        series=series,
        logical_type=LogicalType.DATETIME,
    )

    assert profile.datetime_statistics is None


def test_datetime_column_does_not_receive_other_statistics() -> None:
    series = pd.Series(
        pd.to_datetime(
            [
                "2026-01-01",
                "2026-01-02",
            ]
        )
    )

    profile = ColumnProfiler().profile(
        name="created_at",
        series=series,
        logical_type=LogicalType.DATETIME,
    )

    assert profile.datetime_statistics is not None
    assert profile.numeric_statistics is None
    assert profile.text_statistics is None
