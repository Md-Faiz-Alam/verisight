"""ISO 8601 date columns in CSV and JSON become datetimes; nothing else does."""

import json
from pathlib import Path

import pandas as pd
import pytest

from verisight import VeriSight
from verisight.config import Settings
from verisight.ingestion.schema import LogicalType, SchemaInferer
from verisight.ingestion.temporal import parse_iso_datetimes


def _app() -> VeriSight:
    return VeriSight(
        settings=Settings(gemini_api_key=None, allow_llm_data_disclosure=False)
    )


@pytest.mark.parametrize(
    "values",
    [
        ["2026-01-31", "2024-02-29"],
        ["2026-01-31 10:15", "2026-01-31T10:15:30"],
        ["2026-01-31 10:15:30.123456789", "2026-02-01"],
        ["2026-01-31", None, "2026-03-01"],
    ],
    ids=["dates", "times", "fractional-and-mixed", "with-missing"],
)
def test_iso_values_become_datetimes(values: list[str | None]) -> None:
    parsed = parse_iso_datetimes(pd.Series(values, dtype=object, name="day"))

    assert parsed is not None
    assert str(parsed.dtype) == "datetime64[ns]"
    assert parsed.name == "day"
    assert parsed.isna().tolist() == [value is None for value in values]
    first = values[0]
    assert first is not None
    assert parsed.iloc[0] == pd.Timestamp(first)


@pytest.mark.parametrize(
    "values",
    [
        ["03/04/2026", "03/05/2026"],
        ["2026-01-31", "31-01-2026"],
        ["2026-02-30"],
        ["2026-13-01"],
        ["2026-01-31T10:15:00Z"],
        ["2026-01-31T10:15:00+05:30"],
        ["0001-01-01"],
        [" 2026-01-31"],
        ["2026-01"],
        ["2026-W05"],
        ["2026-01-31", 5],
        [None, None],
        [],
    ],
    ids=[
        "regional-format",
        "one-bad-value",
        "impossible-day",
        "impossible-month",
        "utc-offset",
        "numeric-offset",
        "out-of-range-year",
        "padded",
        "month-only",
        "week-date",
        "mixed-types",
        "all-missing",
        "empty",
    ],
)
def test_everything_else_stays_unchanged(values: list[object]) -> None:
    assert parse_iso_datetimes(pd.Series(values, dtype=object)) is None


def test_csv_dates_support_sql_date_functions_and_profiles(tmp_path: Path) -> None:
    source = tmp_path / "sales.csv"
    source.write_text(
        "day,stamp,regional,code,amount\n"
        "2026-01-31,2026-01-31 10:15:00,03/04/2026,2026,5\n"
        "2026-02-01,2026-02-01T08:00:00,03/05/2026,2027,7\n"
        ",2026-03-05 09:30,,2028,1\n",
        encoding="utf-8",
    )
    app = _app()
    dataset = app._load_dataset(source)

    types = {
        column.name: column.logical_type
        for column in SchemaInferer().infer_dataset(dataset).tables[0].columns
    }
    assert types == {
        "day": LogicalType.DATETIME,
        "stamp": LogicalType.DATETIME,
        "regional": LogicalType.STRING,
        "code": LogicalType.INTEGER,
        "amount": LogicalType.INTEGER,
    }
    monthly = app.execute(
        source,
        "SELECT strftime(day, '%Y-%m') AS month, SUM(amount) AS total FROM sales "
        "WHERE day IS NOT NULL GROUP BY 1 ORDER BY 1",
    )
    assert monthly.rows == (("2026-01", 5), ("2026-02", 7))
    span = app.execute(
        source, "SELECT date_diff('day', MIN(stamp), MAX(stamp)) AS days FROM sales"
    )
    assert span.rows == ((33,),)


def test_json_dates_become_datetimes_without_changing_other_columns(
    tmp_path: Path,
) -> None:
    source = tmp_path / "events.json"
    source.write_text(
        json.dumps(
            [
                {"day": "2026-01-31", "label": "2026-01-31", "amount": 5},
                {"day": None, "label": "launch", "amount": 7},
                {"day": "2026-02-01", "label": "2026-02-01", "amount": 3},
            ]
        ),
        encoding="utf-8",
    )
    app = _app()
    data = app._load_dataset(source).tables[0].data

    assert str(data["day"].dtype) == "datetime64[ns]"
    assert data["label"].tolist() == ["2026-01-31", "launch", "2026-02-01"]
    assert str(data["amount"].dtype) == "int64"
    yearly = app.execute(
        source,
        "SELECT YEAR(day) AS year, SUM(amount) AS total FROM events "
        "WHERE day IS NOT NULL GROUP BY 1",
    )
    assert yearly.rows == ((2026, 8),)
