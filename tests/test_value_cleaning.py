"""Messy values convert only under one clear rule, and every change is reported."""

import json
from pathlib import Path

import pandas as pd
import pytest

from verisight import VeriSight
from verisight.config import Settings
from verisight.execution.prompting import QueryPromptBuilder
from verisight.ingestion.models import LoadedTable, ValueNote
from verisight.ingestion.validation import validate_file
from verisight.quality.models import QualityIssueType
from verisight.quality.rules import value_note_issues


def _app() -> VeriSight:
    return VeriSight(
        settings=Settings(gemini_api_key=None, allow_llm_data_disclosure=False)
    )


def _csv(tmp_path: Path, text: str, name: str = "data.csv") -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def _table(path: Path) -> LoadedTable:
    return _app()._load_dataset(path).tables[0]


def _notes(table: LoadedTable) -> dict[tuple[str, str], ValueNote]:
    return {(note.column, note.rule): note for note in table.value_notes}


MESSY = (
    "Order ID, Amount ,Price,Discount,Status,Qty\n"
    '1,"1,234.50",$12.00,10%,Shipped ,3\n'
    "2,N/A,$8.50,5%,shipped,N/A\n"
    "3,99,$7.25,,SHIPPED,2\n"
    "4,-,$1.00,0%,Pending,4\n"
)


def test_messy_csv_is_typed_queryable_and_fully_reported(tmp_path: Path) -> None:
    source = _csv(tmp_path, MESSY, "orders.csv")
    app = _app()
    table = _table(source)

    assert list(table.data.columns) == [
        "Order ID",
        "Amount",
        "Price",
        "Discount",
        "Status",
        "Qty",
    ]
    assert table.data["Amount"].tolist()[0] == 1234.5
    assert table.data["Status"].tolist() == [
        "Shipped ",
        "shipped",
        "SHIPPED",
        "Pending",
    ]
    notes = _notes(table)
    assert notes[("Amount", "trimmed_column_name")].examples == (" Amount ",)
    assert notes[("Amount", "missing_value_markers")].affected_count == 2
    assert notes[("Amount", "missing_value_markers")].examples == ("N/A", "-")
    assert notes[("Amount", "thousands_separators")].examples == ("1,234.50",)
    assert notes[("Price", "currency_symbol")].detail == "$ removed"
    assert notes[("Price", "currency_symbol")].affected_count == 4
    assert notes[("Discount", "percent_sign")].affected_count == 3
    assert notes[("Status", "label_variants")].affected_count == 3
    assert notes[("Qty", "missing_value_markers")].affected_count == 1

    totals = app.execute(
        source,
        'SELECT SUM("Qty") AS qty, AVG("Amount") AS amount, AVG("Price") AS price, '
        'AVG("Discount") AS discount FROM orders',
    )
    assert totals.rows == ((9, 666.75, 7.1875, 5.0),)
    shipped = app.execute(
        source,
        "SELECT COUNT(*) AS n FROM orders WHERE LOWER(TRIM(\"Status\")) = 'shipped'",
    )
    assert shipped.rows == ((3,),)

    issues = {
        (issue.column_name, issue.issue_type)
        for issue in app.analyze(source).analysis.issues
    }
    assert ("Amount", QualityIssueType.MISSING_VALUE_MARKERS) in issues
    assert ("Price", QualityIssueType.FORMATTED_NUMBERS) in issues
    assert ("Status", QualityIssueType.LABEL_VARIANTS) in issues
    assert ("Amount", QualityIssueType.TRIMMED_COLUMN_NAME) in issues


@pytest.mark.parametrize(
    ("values", "expected"),
    [
        (["$1,234.00", "$5.00"], [1234.0, 5.0]),
        (["-$5.00", "$7.50"], [-5.0, 7.5]),
        (["10%", "N/A", "2.5%"], [10.0, None, 2.5]),
        (["1,234", "56", "?"], [1234, 56, None]),
    ],
    ids=["currency-with-groups", "negative-currency", "percent-markers", "groups"],
)
def test_single_formats_convert(
    tmp_path: Path, values: list[str], expected: list[float | None]
) -> None:
    rows = "\n".join(f'{i},"{value}"' for i, value in enumerate(values))
    data = _table(_csv(tmp_path, f"id,value\n{rows}\n")).data["value"]

    assert [None if pd.isna(value) else value for value in data] == expected


@pytest.mark.parametrize(
    "values",
    [
        ["NA", "Europe", "Asia"],
        ["007", "012"],
        ["$5.00", "€6.00"],
        ["N/A", "n/a"],
        ["12%", "13"],
    ],
    ids=[
        "na-is-a-label",
        "leading-zeros",
        "mixed-currencies",
        "only-markers",
        "partial-percent",
    ],
)
def test_uncertain_columns_stay_text(tmp_path: Path, values: list[str]) -> None:
    rows = "\n".join(f'{i},"{value}"' for i, value in enumerate(values))
    table = _table(_csv(tmp_path, f"id,value\n{rows}\n"))

    assert table.data["value"].tolist() == values
    allowed = {"label_variants", "mixed_currencies"}
    assert all(note.rule in allowed for note in table.value_notes)


def test_dates_with_markers_become_dates(tmp_path: Path) -> None:
    table = _table(_csv(tmp_path, "day\n2026-01-31\nN/A\n2026-02-01\n"))

    assert str(table.data["day"].dtype) == "datetime64[ns]"
    assert [note.rule for note in table.value_notes] == ["missing_value_markers"]


def test_json_numbers_mixed_with_markers(tmp_path: Path) -> None:
    source = tmp_path / "readings.json"
    source.write_text(
        json.dumps(
            [
                {"count": 3, "rate": 1.5, "huge": 2**60, "flag": True, "code": "12"},
                {
                    "count": "N/A",
                    "rate": "N/A",
                    "huge": "N/A",
                    "flag": "N/A",
                    "code": "7",
                },
                {"count": 4, "rate": 2, "huge": 1, "flag": False, "code": "9"},
            ]
        ),
        encoding="utf-8",
    )
    table = _table(source)
    data = table.data

    assert str(data["count"].dtype) == "Int64"
    assert data["count"].isna().tolist() == [False, True, False]
    assert data["rate"].tolist()[0] == 1.5
    assert pd.isna(data["rate"].tolist()[1])
    # Exact huge integers, booleans and numeric-looking text keep their values.
    assert data["huge"].tolist() == [2**60, "N/A", 1]
    assert data["flag"].tolist() == [True, "N/A", False]
    assert data["code"].tolist() == ["12", "7", "9"]
    assert {note.column for note in table.value_notes} == {"count", "rate"}


def test_excel_numbers_mixed_with_markers(tmp_path: Path) -> None:
    path = tmp_path / "book.xlsx"
    pd.DataFrame(
        {"amount": [5, "N/A", 7], "label": ["2026-01-31", "2026-02-01", "n/a"]}
    ).to_excel(path, index=False)

    table = _table(path)

    assert str(table.data["amount"].dtype) == "Int64"
    # ISO text with a marker in a spreadsheet becomes dates too.
    assert str(table.data["label"].dtype) == "datetime64[ns]"
    assert {(note.column, note.rule) for note in table.value_notes} == {
        ("amount", "missing_value_markers"),
        ("label", "missing_value_markers"),
    }


def test_plain_text_numbers_and_dates_without_markers_are_untouched(
    tmp_path: Path,
) -> None:
    path = tmp_path / "plain.xlsx"
    pd.DataFrame({"code": ["12", "7"], "day": ["2026-01-31", "2026-02-01"]}).to_excel(
        path, index=False
    )

    table = _table(path)

    assert table.data["code"].tolist() == ["12", "7"]
    assert table.data["day"].tolist() == ["2026-01-31", "2026-02-01"]
    assert table.value_notes == ()


def test_header_trimming_never_creates_collisions(tmp_path: Path) -> None:
    table = _table(_csv(tmp_path, " amount,Amount , total \n1,2,3\n"))

    assert list(table.data.columns) == [" amount", "Amount ", "total"]
    assert [(note.column, note.rule) for note in table.value_notes] == [
        ("total", "trimmed_column_name")
    ]


def test_colliding_padded_headers_are_left_alone(tmp_path: Path) -> None:
    table = _table(_csv(tmp_path, " amount,Amount \n1,2\n"))

    assert list(table.data.columns) == [" amount", "Amount "]
    assert table.value_notes == ()


def test_label_variant_examples_are_bounded(tmp_path: Path) -> None:
    rows = "".join(f"G{i}\ng{i}\n g{i}\nG{i} \n" for i in range(7))
    table = _table(_csv(tmp_path, f"group\n{rows}"))

    (note,) = table.value_notes
    assert note.affected_count == 28
    assert len(note.examples) == 5
    assert note.examples[0].count(" / ") == 2


def test_value_note_issue_ratio_handles_empty_tables(tmp_path: Path) -> None:
    path = _csv(tmp_path, "value\n1\n")
    table = LoadedTable(
        name="empty",
        data=pd.DataFrame({"value": []}),
        source=validate_file(path, max_size_mb=1),
    )
    table.value_notes = (
        ValueNote(column="value", rule="percent_sign", affected_count=0, examples=()),
    )

    (issue,) = value_note_issues(table)

    assert issue.affected_ratio is None
    assert issue.issue_type is QualityIssueType.FORMATTED_NUMBERS


def test_planner_prompt_explains_label_variants() -> None:
    from verisight.execution.context import QueryContext
    from verisight.execution.planning import QueryRequest
    from verisight.execution.prompting import LABEL_VARIANT_RULES

    prompt = QueryPromptBuilder().build(
        QueryRequest(
            question="Count shipped orders.", context=QueryContext(relations=())
        )
    )

    assert LABEL_VARIANT_RULES in prompt
    assert "LOWER(TRIM(column))" in prompt
