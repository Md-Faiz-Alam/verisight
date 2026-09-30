import pandas as pd
from pandas.testing import assert_series_equal

from verisight.ingestion.schema import LogicalType
from verisight.profiling.column import ColumnProfiler


def test_profiles_timezone_aware_datetime() -> None:
    series = pd.Series(
        pd.to_datetime(
            [
                "2026-01-01 10:00:00",
                "2026-01-01 12:00:00",
                "2026-01-01 11:00:00",
            ],
            utc=True,
        )
    )

    profile = ColumnProfiler().profile(
        name="event_time",
        series=series,
        logical_type=LogicalType.DATETIME,
    )

    statistics = profile.datetime_statistics
    assert statistics is not None

    assert statistics.earliest == pd.Timestamp(
        "2026-01-01 10:00:00",
        tz="UTC",
    )
    assert statistics.latest == pd.Timestamp(
        "2026-01-01 12:00:00",
        tz="UTC",
    )
    assert statistics.span == pd.Timedelta(hours=2)
    assert statistics.timezone == "UTC"


def test_datetime_preserves_subday_precision() -> None:
    series = pd.Series(
        pd.to_datetime(
            [
                "2026-01-01 10:15:30",
                "2026-01-01 10:16:45",
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

    assert statistics.span == pd.Timedelta(minutes=1, seconds=15)


def test_datetime_profiling_does_not_mutate_source_series() -> None:
    series = pd.Series(
        [
            pd.Timestamp("2026-01-01"),
            pd.NaT,
            pd.Timestamp("2026-01-03"),
        ],
        dtype="datetime64[ns]",
        name="event_time",
    )
    original = series.copy(deep=True)

    ColumnProfiler().profile(
        name="event_time",
        series=series,
        logical_type=LogicalType.DATETIME,
    )

    assert_series_equal(series, original)


def test_datetime_values_are_not_added_to_string_statistics() -> None:
    series = pd.Series(
        pd.to_datetime(
            [
                "2026-01-01",
                "2026-01-02",
            ]
        )
    )

    profile = ColumnProfiler().profile(
        name="event_time",
        series=series,
        logical_type=LogicalType.DATETIME,
    )

    assert profile.datetime_statistics is not None
    assert profile.text_statistics is None
