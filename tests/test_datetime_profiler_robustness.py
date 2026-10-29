import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from pandas.testing import assert_series_equal

from verisight import VeriSight
from verisight.cli import main
from verisight.config import Settings
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


@pytest.mark.parametrize("timezone", [None, "UTC"])
def test_wide_datetime_range_preserves_endpoints_and_marks_overflow(
    timezone: str | None,
) -> None:
    earliest = pd.Timestamp("1900-01-01", tz=timezone)
    latest = pd.Timestamp("2200-01-01", tz=timezone)
    series = pd.Series(
        [latest, pd.NaT, earliest],
        dtype=("datetime64[ns]" if timezone is None else "datetime64[ns, UTC]"),
    )
    original = series.copy(deep=True)

    profile = ColumnProfiler().profile(
        name="event_time", series=series, logical_type=LogicalType.DATETIME
    )

    statistics = profile.datetime_statistics
    assert statistics is not None
    assert statistics.earliest == earliest
    assert statistics.latest == latest
    assert statistics.span is None
    assert statistics.span_overflow is True
    assert statistics.timezone == timezone
    assert profile.minimum == earliest
    assert profile.maximum == latest
    assert profile.missing_count == 1
    assert_series_equal(series, original)


@pytest.mark.parametrize("extra_nanoseconds", [-1, 0, 1])
def test_datetime_span_at_nanosecond_representation_boundary(
    extra_nanoseconds: int,
) -> None:
    earliest = pd.Timestamp("1900-01-01")
    latest = earliest + pd.Timedelta.max
    latest += pd.Timedelta(extra_nanoseconds, unit="ns")
    series = pd.Series([earliest, latest], dtype="datetime64[ns]")

    profile = ColumnProfiler().profile(
        name="event_time", series=series, logical_type=LogicalType.DATETIME
    )

    statistics = profile.datetime_statistics
    assert statistics is not None
    assert statistics.earliest == earliest
    assert statistics.latest == latest
    if extra_nanoseconds > 0:
        assert statistics.span is None
        assert statistics.span_overflow is True
    else:
        assert statistics.span == pd.Timedelta(
            pd.Timedelta.max.value + extra_nanoseconds, unit="ns"
        )
        assert statistics.span_overflow is False


def test_datetime_span_retains_nanosecond_precision() -> None:
    earliest = pd.Timestamp("2026-01-01 00:00:00.000000001")
    latest = pd.Timestamp("2026-01-01 00:00:00.000000002")
    profile = ColumnProfiler().profile(
        name="event_time",
        series=pd.Series([earliest, latest]),
        logical_type=LogicalType.DATETIME,
    )

    statistics = profile.datetime_statistics
    assert statistics is not None
    assert statistics.earliest == earliest
    assert statistics.latest == latest
    assert statistics.span == pd.Timedelta(1, unit="ns")
    assert statistics.span_overflow is False


def test_wide_excel_dates_support_analysis_sql_and_cli_export(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "dates.xlsx"
    pd.DataFrame(
        {"event_date": [pd.Timestamp("1900-01-01"), pd.Timestamp("2200-01-01")]}
    ).to_excel(source, index=False)
    before = source.read_bytes()
    destination = tmp_path / "profile.json"
    app = VeriSight(
        settings=Settings(gemini_api_key=None, allow_llm_data_disclosure=False)
    )

    with patch(
        "verisight.execution.gemini.GeminiTextGenerationClient.generate",
        side_effect=AssertionError("Model calls forbidden"),
    ) as generate:
        analysis = app.analyze(source)
        result = app.execute(source, "SELECT COUNT(*) AS count FROM sheet1")
        exit_code = main(["profile", str(source), "--output", str(destination)])
    generate.assert_not_called()

    statistics = analysis.analysis.profile.tables[0].columns[0].datetime_statistics
    assert statistics is not None
    assert statistics.span is None
    assert statistics.span_overflow is True
    assert result.rows == ((2,),)
    assert exit_code == 0
    exported = json.loads(destination.read_text(encoding="utf-8"))
    printed = json.loads(capsys.readouterr().out)
    assert exported == printed
    column = exported["profile"]["profiles"]["tables"][0]["columns"][0]
    assert column["minimum"] == "1900-01-01T00:00:00"
    assert column["maximum"] == "2200-01-01T00:00:00"
    assert column["datetime_statistics"]["span"] is None
    assert column["datetime_statistics"]["span_overflow"] is True
    assert source.read_bytes() == before
