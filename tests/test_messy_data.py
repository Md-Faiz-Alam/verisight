"""Real-world messy files: read correctly, and every change reported."""

import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from verisight import VeriSight
from verisight.config import Settings
from verisight.ingestion.exceptions import DataLoadError
from verisight.ingestion.footers import remove_footer_rows
from verisight.ingestion.loaders.csv import CsvLoader
from verisight.ingestion.models import LoadedTable, SourceMetadata
from verisight.ingestion.service import DatasetLoader
from verisight.ingestion.temporal import has_ambiguous_dates, parse_flexible_dates

SETTINGS = Settings(_env_file=None, gemini_api_key=None)  # type: ignore[call-arg]


def _load(path: Path) -> LoadedTable:
    return DatasetLoader(SETTINGS).load([path]).tables[0]


def _csv(tmp_path: Path, text: str, name: str = "data.csv") -> LoadedTable:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return _load(path)


def _column(tmp_path: Path, values: Sequence[str]) -> LoadedTable:
    rows = "\n".join(f'{i},"{value}"' for i, value in enumerate(values))
    return _csv(tmp_path, f"row,value\n{rows}\n")


def _values(table: LoadedTable) -> list[object]:
    return [None if pd.isna(v) else v for v in table.data["value"]]


def _rules(table: LoadedTable) -> list[str]:
    return [note.rule for note in table.value_notes]


@pytest.mark.parametrize(
    ("values", "expected", "rule"),
    [
        (["(1,234.50)", "2,000.00", "500.00"], [-1234.5, 2000.0, 500.0], "accounting"),
        (["USD 100", "USD 200"], [100, 200], "currency_symbol"),
        (["100 USD", "-5 USD"], [100, -5], "currency_symbol"),
        (["100 €", "200 €"], [100, 200], "currency_symbol"),
        (["1.2K", "3K", "500"], [1200.0, 3000.0, 500.0], "abbreviated_numbers"),
        (["2M", "1.5B"], [2_000_000.0, 1_500_000_000.0], "abbreviated_numbers"),
        (["12 kg", "3.5 kg"], [12.0, 3.5], "unit_suffix"),
        (["1.234,50", "2.000,00"], [1234.5, 2000.0], "european_numbers"),
        (["1,5", "7"], [1.5, 7.0], "european_numbers"),
        ([" 12", "13 "], [12, 13], "padded_numbers"),
    ],
)
def test_number_formats(
    tmp_path: Path, values: list[str], expected: list[object], rule: str
) -> None:
    table = _column(tmp_path, values)

    assert _values(table) == expected
    assert _rules(table)[0].startswith(rule)


@pytest.mark.parametrize(
    "values",
    [
        ["12 kg", "3 lb"],
        ["1.2K", "abc"],
        ["USD 5", "EUR 6"],
        ["(abc)", "(def)"],
        ["1.5", "2,5"],
    ],
)
def test_unclear_numbers_stay_text(tmp_path: Path, values: list[str]) -> None:
    assert _values(_column(tmp_path, values)) == values


def test_a_lone_group_separator_is_read_but_flagged(tmp_path: Path) -> None:
    table = _column(tmp_path, ["1,234", "5,678"])

    assert _values(table) == [1234, 5678]
    assert "check this" in str(table.value_notes[0].detail)


def test_longer_grouping_needs_no_flag(tmp_path: Path) -> None:
    table = _column(tmp_path, ["1,234,567", "5,678"])

    assert "check this" not in str(table.value_notes[0].detail)


def test_semicolon_files_prove_comma_decimals(tmp_path: Path) -> None:
    table = _csv(tmp_path, "name;value\na;1,234\nb;5,678\n")

    assert _values(table) == [1.234, 5.678]
    assert _rules(table) == ["european_numbers"]


def test_a_few_stray_values_do_not_cost_the_column(tmp_path: Path) -> None:
    table = _column(tmp_path, [*(str(i) for i in range(1, 40)), "TBD"])

    assert _values(table)[-1] is None
    assert _values(table)[0] == 1
    assert _rules(table) == ["non_numeric_values"]
    assert table.value_notes[0].examples == ("TBD",)


def test_stray_values_also_work_for_dates(tmp_path: Path) -> None:
    days = [f"2024-01-{i:02d}" for i in range(1, 25)]
    table = _column(tmp_path, [*days, "TBD"])

    assert str(table.data["value"].dtype) == "datetime64[ns]"
    assert _rules(table) == ["non_numeric_values"]


@pytest.mark.parametrize(
    "values",
    [
        # Too few rows to tell a stray from real text.
        ["1", "2", "TBD"],
        # Too many that are not numbers.
        [*(str(i) for i in range(30)), *("x" for _ in range(5))],
        # Too many different labels.
        [*(str(i) for i in range(200)), "a", "b", "c", "d", "e", "f"],
        # Number-shaped values that still cannot be read.
        [*(f"1.2.{i}" for i in range(30)), "TBD"],
    ],
)
def test_columns_that_are_really_text_are_left_alone(
    tmp_path: Path, values: list[str]
) -> None:
    assert "non_numeric_values" not in _rules(_column(tmp_path, values))


def test_stray_rule_skips_identifier_columns(tmp_path: Path) -> None:
    rows = "\n".join(f"{i}" for i in range(30))
    table = _csv(tmp_path, f"item_code\n{rows}\nA12\n")

    assert table.data["item_code"].iloc[-1] == "A12"


@pytest.mark.parametrize(
    ("values", "expected", "detail"),
    [
        (["12/25/2026", "01/02/2026"], "2026-12-25", "month first"),
        (["25/12/2026", "01/02/2026"], "2026-12-25", "day first"),
        (["25.12.26", "01.02.26"], "2026-12-25", "day first"),
        (["25-12-2026 10:30", "01-02-2026 09:15"], "2026-12-25 10:30:00", "day first"),
        (
            ["25/12/2026 10:30:05", "01/02/2026 09:15:00"],
            "2026-12-25 10:30:05",
            "day first",
        ),
        (["Jan 5, 2024", "Feb 6, 2024"], "2024-01-05", "month names"),
        (["5 January 2024", "6 February 2024"], "2024-01-05", "month names"),
        (["05-Jan-24", "06-Feb-24"], "2024-01-05", "month names"),
        (
            ["2024-01-05T10:00:00Z", "2024-01-05T12:00:00+02:00"],
            "2024-01-05 10:00:00",
            "UTC",
        ),
    ],
)
def test_clear_date_formats(
    tmp_path: Path, values: list[str], expected: str, detail: str
) -> None:
    table = _column(tmp_path, values)

    assert str(table.data["value"].dtype) == "datetime64[ns]"
    assert str(table.data["value"].iloc[0]).removesuffix(" 00:00:00") == expected
    assert _rules(table) == ["date_format"]
    assert detail in str(table.value_notes[0].detail)


def test_conflicting_date_orders_are_reported(tmp_path: Path) -> None:
    values = ["25/12/2026", "12/25/2026"]
    table = _column(tmp_path, values)

    assert _values(table) == values
    assert _rules(table) == ["ambiguous_dates"]


def test_day_or_month_first_is_never_guessed(tmp_path: Path) -> None:
    values = ["03/04/2026", "05/06/2026"]
    table = _column(tmp_path, values)

    assert _values(table) == values
    assert _rules(table) == ["ambiguous_dates"]


@pytest.mark.parametrize(
    "values",
    [
        # A proven order, but no such date.
        ["31/02/2026", "13/01/2026"],
        ["Jan 5, 2024", "Soon"],
        ["9999-99-99T00:00:00Z", "2024-01-01T00:00:00Z"],
    ],
)
def test_impossible_dates_stay_text(tmp_path: Path, values: list[str]) -> None:
    table = _column(tmp_path, values)

    assert _values(table) == values
    assert "date_format" not in _rules(table)
    assert "ambiguous_dates" not in _rules(table)


def test_date_helpers_handle_empty_columns() -> None:
    empty = pd.Series([None], dtype=object)

    assert parse_flexible_dates(empty) is None
    assert has_ambiguous_dates(pd.Series(["Jan"], dtype=object)) is False


def test_text_placeholders_become_missing_and_doubtful_words_stay(
    tmp_path: Path,
) -> None:
    table = _column(tmp_path, ["Open", "N/A", "unknown", "None", "Closed", " "])

    assert _values(table) == ["Open", None, "unknown", "None", "Closed", None]
    assert _rules(table) == ["text_missing_labels", "possible_missing_labels"]


def test_na_stays_a_label_in_text(tmp_path: Path) -> None:
    assert _values(_column(tmp_path, ["NA", "Europe"])) == ["NA", "Europe"]


def _orders(footer: str) -> str:
    rows = "\n".join(f"INV{i},R{i % 3},{i * 10}" for i in range(1, 11))
    return f"invoice,region,amount\n{rows}\n{footer}\n"


@pytest.mark.parametrize(
    "footer",
    [
        "TOTAL,,550",
        "Grand Total,,550",
        "Subtotal,,550",
        "Sum,,550",
        "Totals for Q1,,550",
    ],
)
def test_total_footer_is_removed(tmp_path: Path, footer: str) -> None:
    table = _csv(tmp_path, _orders(footer))

    assert len(table.data) == 10
    assert int(table.data["amount"].sum()) == 550
    assert _rules(table) == ["footer_total_rows"]


def test_average_footer_is_removed(tmp_path: Path) -> None:
    table = _csv(tmp_path, _orders("Average,,55"))

    assert len(table.data) == 10


@pytest.mark.parametrize(
    "footer",
    [
        # Labelled like a summary, but the number is not the total.
        "Total,,999",
        # Not a summary label.
        "INV99,R1,550",
        # No number at all.
        "Total,,",
        # Zero proves nothing.
        "Total,,0",
    ],
)
def test_rows_that_only_look_like_summaries_stay(tmp_path: Path, footer: str) -> None:
    table = _csv(tmp_path, _orders(footer))

    assert len(table.data) == 11
    assert "footer_total_rows" not in _rules(table)


def test_summary_needs_rows_above_it(tmp_path: Path) -> None:
    assert len(_csv(tmp_path, "item,cost\na,1\nTotal,1\n").data) == 2


def test_removing_a_footer_lets_dates_be_read(tmp_path: Path) -> None:
    rows = "\n".join(f"2024-01-{d:02d},{d * 10}" for d in range(1, 11))
    table = _csv(tmp_path, f"day,amount\n{rows}\nTOTAL,550\n")

    assert str(table.data["day"].dtype) == "datetime64[ns]"
    assert len(table.data) == 10


def test_footer_with_formatted_numbers(tmp_path: Path) -> None:
    table = _csv(
        tmp_path,
        'item,cost\na,"$1,000.00"\nb,"$2,000.00"\nc,"($500.00)"\nd,"$50.00"\n'
        'Total,"$2,550.00"\n',
    )

    assert table.data["cost"].tolist() == [1000.0, 2000.0, -500.0, 50.0]


def test_several_footer_rows_are_checked_together(tmp_path: Path) -> None:
    rows = "\n".join(f"i{i},{i}" for i in range(1, 6))
    table = _csv(tmp_path, f"item,cost\n{rows}\nSubtotal,15\nTotal,15\n")

    assert len(table.data) == 5


def test_three_footer_rows_can_all_be_removed(tmp_path: Path) -> None:
    rows = "\n".join(f"i{i},{i}" for i in range(1, 6))
    text = f"item,cost\n{rows}\nSubtotal,15\nTotal,15\nGrand Total,15\n"

    assert len(_csv(tmp_path, text).data) == 5


def test_number_in_a_text_column_does_not_prove_a_summary(tmp_path: Path) -> None:
    table = _csv(tmp_path, "item,note,cost\na,x,1\nb,y,2\nc,z,3\nTotal,6,99\n")

    assert len(table.data) == 4


def test_footer_ignores_text_and_infinite_cells(tmp_path: Path) -> None:
    source = SourceMetadata(Path("x.json"), "x.json", ".json", 1)
    data = pd.DataFrame(
        {
            "name": ["a", "b", "c", "Total"],
            "note": ["x", "y", "z", float("inf")],
            "extra": [object(), object(), object(), object()],
            "flag": [True, False, True, True],
            "cost": [1, 2, 3, 6],
        }
    )
    table = LoadedTable(name="x", data=data, source=source)

    assert [note.rule for note in remove_footer_rows(table)] == ["footer_total_rows"]
    assert len(table.data) == 3


def test_empty_table_has_no_footer() -> None:
    source = SourceMetadata(Path("x.json"), "x.json", ".json", 1)
    table = LoadedTable(name="x", data=pd.DataFrame(), source=source)

    assert remove_footer_rows(table) == []


def test_title_rows_above_a_csv_header_are_skipped(tmp_path: Path) -> None:
    table = _csv(
        tmp_path, "Quarterly Report\nGenerated today\n\nid,amount\n1,10\n2,20\n"
    )

    assert list(table.data.columns) == ["id", "amount"]
    assert table.data["amount"].tolist() == [10, 20]
    assert _rules(table) == ["skipped_title_rows"]
    assert table.value_notes[0].examples == ("Quarterly Report", "Generated today")


@pytest.mark.parametrize(
    "text",
    [
        # A row of numbers must never become column names.
        "a,b\n1,2,3\n4,5,6\n",
        # Nothing below the title has a consistent width.
        "Report\nid,amount\n1,2,3\n",
    ],
)
def test_unclear_layouts_are_still_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / "data.csv"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(DataLoadError, match="delimiter detection"):
        _load(path)


def test_duplicate_names_avoid_taken_names(tmp_path: Path) -> None:
    table = _csv(tmp_path, "a,a,a_2\n1,2,3\n")

    assert list(table.data.columns) == ["a", "a_3", "a_2"]
    assert table.value_notes[0].rule == "renamed_duplicate_column"


def test_excel_title_rows_are_skipped(tmp_path: Path) -> None:
    rows = [["Sales Report 2024", None], ["id", "amount"], [1, 10], [2, 20]]
    path = tmp_path / "report.xlsx"
    pd.DataFrame(rows).to_excel(path, index=False, header=False)

    table = _load(path)

    assert list(table.data.columns) == ["id", "amount"]
    assert table.data["amount"].tolist() == [10, 20]
    assert _rules(table) == ["skipped_title_rows"]
    assert table.value_notes[0].examples == ("Sales Report 2024",)


def test_excel_numeric_rows_never_become_headers(tmp_path: Path) -> None:
    path = tmp_path / "numbers.xlsx"
    pd.DataFrame([["only", None], [1, 2]]).to_excel(path, index=False, header=False)

    table = _load(path)

    assert list(table.data.columns) == ["only", "unnamed_2"]
    assert table.data["only"].tolist() == [1]


def test_excel_cells_far_below_the_header_need_a_header(tmp_path: Path) -> None:
    rows = [["value", None], *([i, None] for i in range(25)), [1, 900]]
    path = tmp_path / "wide.xlsx"
    pd.DataFrame(rows, dtype=object).to_excel(path, index=False, header=False)

    with pytest.raises(DataLoadError, match="without source headers"):
        _load(path)


def test_tsv_uses_tabs(tmp_path: Path) -> None:
    table = _csv(tmp_path, "a\tb\n1\t2\n", "data.tsv")

    assert table.data["b"].tolist() == [2]
    assert table.source.csv_delimiter == "\t"


@pytest.mark.parametrize("name", ["data.jsonl", "data.ndjson", "data.json"])
def test_json_lines(tmp_path: Path, name: str) -> None:
    table = _csv(tmp_path, '{"a": 1}\n\n{"a": 2}\n', name)

    assert table.data["a"].tolist() == [1, 2]
    assert _rules(table) == ["reshaped_json"]


def test_broken_json_is_still_refused(tmp_path: Path) -> None:
    path = tmp_path / "data.json"
    path.write_text("{broken", encoding="utf-8")

    with pytest.raises(DataLoadError):
        _load(path)


def test_wrapped_json_rows_are_found(tmp_path: Path) -> None:
    payload = {"data": [{"a": 1}, {"a": 2}], "meta": {"n": 2}}
    table = _csv(tmp_path, json.dumps(payload), "data.json")

    assert table.data["a"].tolist() == [1, 2]
    assert "'data'" in str(table.value_notes[0].detail)


def test_two_row_lists_are_not_guessed_between(tmp_path: Path) -> None:
    payload = {"a": [{"x": 1}], "b": [{"y": 2}]}
    table = _csv(tmp_path, json.dumps(payload), "data.json")

    assert list(table.data.columns) == ["a", "b"]


def test_deeply_nested_json_is_flattened(tmp_path: Path) -> None:
    rows = [{"a": {"b": {"c": 1}}}, {"a": {"b": {"c": 2}}}]
    table = _csv(tmp_path, json.dumps(rows), "data.json")

    assert table.data["a.b.c"].tolist() == [1, 2]


def test_nesting_is_flattened_only_so_deep(tmp_path: Path) -> None:
    rows = [{"a": {"b": {"c": {"d": {"e": {"f": 1}}}}}}]
    table = _csv(tmp_path, json.dumps(rows), "data.json")

    assert list(table.data.columns) == ["a.b.c.d.e"]


def test_missing_nested_objects_stay_missing(tmp_path: Path) -> None:
    rows = [{"id": 1, "a": {"b": 1}}, {"id": 2, "a": None}]
    table = _csv(tmp_path, json.dumps(rows), "data.json")

    assert table.data["a.b"].iloc[0] == 1
    assert list(table.data.columns) == ["id", "a.b"]


def test_mixed_shapes_stay_in_one_column(tmp_path: Path) -> None:
    rows = [{"a": {"b": 1}}, {"a": 5}]
    table = _csv(tmp_path, json.dumps(rows), "data.json")

    assert list(table.data.columns) == ["a"]


def test_flattening_never_overwrites_a_field(tmp_path: Path) -> None:
    rows = [{"a": {"b": 1}, "a.b": 2}]
    table = _csv(tmp_path, json.dumps(rows), "data.json")

    assert table.data["a"].iloc[0] == {"b": 1}


def test_empty_json_reports_nothing(tmp_path: Path) -> None:
    path = tmp_path / "data.jsonl"
    path.write_text("\n", encoding="utf-8")

    assert JsonFree.load(path).value_notes == ()


class JsonFree:
    """Load one JSON Lines file without the dataset-level steps."""

    @staticmethod
    def load(path: Path) -> LoadedTable:
        from verisight.ingestion.loaders.json import JsonLoader

        return JsonLoader(SETTINGS).load(path)


def test_new_findings_appear_in_the_report(tmp_path: Path) -> None:
    path = tmp_path / "data.csv"
    path.write_text(_orders("TOTAL,,550"), encoding="utf-8")

    issues = VeriSight(settings=SETTINGS).analyze(path).analysis.issues

    removed = [i for i in issues if i.issue_type.value == "removed_rows"]
    assert len(removed) == 1
    assert removed[0].evidence["examples"] == ("TOTAL",)


def test_exact_values_survive_reformatting(tmp_path: Path) -> None:
    table = _column(tmp_path, ["$0.1", "$0.2"])

    assert [Decimal(str(v)) for v in table.data["value"]] == [
        Decimal("0.1"),
        Decimal("0.2"),
    ]


def test_loader_reports_nothing_for_clean_files(tmp_path: Path) -> None:
    assert _csv(tmp_path, "a,b\n1,2\n").value_notes == ()
    assert CsvLoader._rename_duplicates(["a", "b"]) == (["a", "b"], ())
