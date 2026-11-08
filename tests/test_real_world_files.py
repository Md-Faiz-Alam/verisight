"""Damage found in real exports, each read back to the value it should hold."""

from pathlib import Path

import pandas as pd
import pytest

from verisight.config import Settings
from verisight.ingestion.models import LoadedTable
from verisight.ingestion.service import DatasetLoader

SETTINGS = Settings(allow_llm_data_disclosure=False, gemini_api_key=None)
HEADER = "item,region,amount\n"
BODY = "".join(f"i{n},East,{n * 10}\n" for n in range(1, 7))


def _table(tmp_path: Path, text: str, name: str = "data.csv") -> LoadedTable:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return DatasetLoader(SETTINGS).load([path]).tables[0]


def _column(tmp_path: Path, name: str, values: list[str]) -> LoadedTable:
    return _table(tmp_path, f"{name},other\n" + "".join(f"{v},x\n" for v in values))


def _rules(table: LoadedTable) -> list[str]:
    return [note.rule for note in table.value_notes]


def test_blank_rows_are_removed_and_reported(tmp_path: Path) -> None:
    table = _table(tmp_path, HEADER + "i0,East,5\n,,\n  , ,\n" + BODY)

    assert len(table.data) == 7
    assert "blank_rows" in _rules(table)
    assert table.value_notes[0].affected_count == 2


def test_a_single_column_keeps_its_empty_cells(tmp_path: Path) -> None:
    text = '[{"score": 1}, {"score": null}, {"score": 3}]'
    table = _table(tmp_path, text, "data.json")

    assert len(table.data) == 3
    assert "blank_rows" not in _rules(table)


def test_a_table_of_nothing_but_blank_rows_is_left_for_the_quality_report(
    tmp_path: Path,
) -> None:
    table = _table(tmp_path, "a,b\n,\n,\n")

    assert "blank_rows" not in _rules(table)


def test_a_repeated_header_is_removed_and_the_column_stays_numeric(
    tmp_path: Path,
) -> None:
    table = _table(tmp_path, HEADER + BODY + "item,region,amount\n" + BODY)

    assert len(table.data) == 12
    assert "repeated_header_rows" in _rules(table)
    assert pd.api.types.is_numeric_dtype(table.data["amount"])


def test_a_row_that_only_starts_like_the_header_stays(tmp_path: Path) -> None:
    assert len(_table(tmp_path, HEADER + "item,East,70\n" + BODY).data) == 7


def test_one_matching_cell_is_not_a_repeated_header(tmp_path: Path) -> None:
    assert len(_table(tmp_path, HEADER + "item,,\n" + BODY).data) == 7


@pytest.mark.parametrize(
    "ending",
    ["Source: national agency", "Notes", "* estimated", "Total", "Grand Total,,"],
)
def test_closing_notes_and_bare_labels_are_removed(tmp_path: Path, ending: str) -> None:
    table = _table(tmp_path, f"{HEADER}{BODY}{ending}\n")

    assert len(table.data) == 6
    assert "note_rows" in _rules(table)
    assert pd.api.types.is_numeric_dtype(table.data["amount"])


@pytest.mark.parametrize("ending", ["Source: x,y,z", "plain words", "5,,"])
def test_other_last_rows_stay(tmp_path: Path, ending: str) -> None:
    assert len(_table(tmp_path, f"{HEADER}{BODY}{ending}\n").data) == 7


def test_three_closing_notes_are_all_removed(tmp_path: Path) -> None:
    table = _table(tmp_path, f"{HEADER}{BODY}Source: x\nNotes\nTotal\n")

    assert len(table.data) == 6


def test_a_note_needs_rows_above_it(tmp_path: Path) -> None:
    assert len(_table(tmp_path, f"{HEADER}a,b,1\nSource: x\n").data) == 2


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["$12.80", "13", "$1,000.00", "2,500"], [12.8, 13.0, 1000.0, 2500.0]),
        (["1,23,456.50", "12,345.5"], [123456.5, 12345.5]),
        (["−5.5", "5.5-", "7.5", "–2.5"], [-5.5, -5.5, 7.5, -2.5]),
    ],
)
def test_numbers_written_in_several_ways_are_read(
    tmp_path: Path, values: list[str], expected: list[float]
) -> None:
    table = _table(tmp_path, "value,other\n" + "".join(f'"{v}",x\n' for v in values))

    assert table.data["value"].tolist() == expected


def test_an_unusual_minus_is_reported(tmp_path: Path) -> None:
    assert "minus_signs" in _rules(_column(tmp_path, "value", ["−5", "7"]))


def test_a_trailing_dash_in_a_code_column_stays_text(tmp_path: Path) -> None:
    table = _column(tmp_path, "code", ["12-", "34-", "56"])

    assert table.data["code"].tolist() == ["12-", "34-", "56"]


@pytest.mark.parametrize(
    "values",
    [
        ["$5", "€6", "7"],
        ["$5", "seven", "7"],
        ["GBP100", "7"],
    ],
)
def test_currency_that_is_not_clear_stays_as_loaded(
    tmp_path: Path, values: list[str]
) -> None:
    table = _column(tmp_path, "value", values)

    assert table.data["value"].tolist() == values


def test_unknown_beside_numbers_means_no_value(tmp_path: Path) -> None:
    values = [str(n) for n in range(30)] + ["unknown"] * 6
    table = _column(tmp_path, "value", values)

    assert pd.api.types.is_numeric_dtype(table.data["value"])
    assert int(table.data["value"].isna().sum()) == 6
    assert "missing_value_markers" in _rules(table)


def test_a_column_of_only_unknown_stays_as_loaded(tmp_path: Path) -> None:
    table = _column(tmp_path, "value", ["unknown", "unknown"])

    assert table.data["value"].tolist() == ["unknown", "unknown"]


def test_unknown_beside_words_stays_a_category(tmp_path: Path) -> None:
    table = _column(tmp_path, "value", ["red", "unknown", "blue"])

    assert table.data["value"].tolist() == ["red", "unknown", "blue"]


@pytest.mark.parametrize(
    "values",
    [
        ["2012/01/31", "2012/02/29"],
        ["2012.01.31", "2012.02.29"],
        ["2012-01-31", "2012/02/29", "01-Mar-2012"],
    ],
)
def test_clear_date_formats_are_read(tmp_path: Path, values: list[str]) -> None:
    table = _column(tmp_path, "value", values)

    assert pd.api.types.is_datetime64_any_dtype(table.data["value"])
    assert table.data["value"].iloc[0] == pd.Timestamp(2012, 1, 31)
    assert table.data["value"].name == "value"


def test_mixed_dates_with_one_unclear_value_stay_text(tmp_path: Path) -> None:
    values = ["2012-01-31", "2012/02/29", "03/04/2012"]

    assert _column(tmp_path, "value", values).data["value"].tolist() == values
