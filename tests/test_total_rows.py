"""Rows that hold the total of other rows are found, reported and reviewed."""

from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from verisight import VeriSight
from verisight.config import Settings
from verisight.execution.context import (
    ObservedCategoryValues,
    QueryContext,
    QueryContextBuilder,
)
from verisight.execution.formatting import QueryContextFormatter
from verisight.execution.validation import review_population
from verisight.ingestion.models import LoadedDataset, LoadedTable, SourceMetadata
from verisight.ingestion.schema import SchemaInferer
from verisight.quality import totals
from verisight.quality.models import QualityIssueType, QualitySeverity
from verisight.quality.totals import TotalRow, find_total_rows


def _table(data: pd.DataFrame, name: str = "sales") -> LoadedTable:
    source = SourceMetadata(
        path=Path(f"{name}.csv"),
        file_name=f"{name}.csv",
        file_extension=".csv",
        file_size_bytes=1,
    )
    return LoadedTable(name=name, data=data, source=source)


def _find(data: pd.DataFrame) -> tuple[TotalRow, ...]:
    return find_total_rows(data, SchemaInferer().infer_table(_table(data)).columns)


def _yearly() -> pd.DataFrame:
    rows = []
    for year, parts in ((2020, (5, 7, 9)), (2021, (4, 6, 1)), (2022, (2, 3, 8))):
        rows.append(("All causes", year, sum(parts)))
        rows.extend(zip(("Flood", "Storm", "Heat"), (year,) * 3, parts, strict=True))
    return pd.DataFrame(rows, columns=["cause", "year", "deaths"])


def test_total_row_per_integer_year_is_found() -> None:
    # An all-missing measure has nothing to compare and is ignored.
    assert _find(_yearly().assign(blank=float("nan"))) == (
        TotalRow("cause", "All causes", ("deaths",), ("year",), 3, 3),
    )


def test_total_row_per_text_group_with_several_measures() -> None:
    data = pd.DataFrame(
        {
            "month": ["Jan"] * 4 + ["Feb"] * 4,
            "region": ["North", "South", "East", "Total"] * 2,
            "sales": [1.5, 2.25, 3.0, 6.75, 4.0, 1.0, 2.0, 7.0],
            "units": [1, 2, 3, 6, 4, 5, 6, 15],
        }
    )

    assert _find(data) == (
        TotalRow("region", "Total", ("sales", "units"), ("month",), 2, 2),
    )


def test_two_parts_and_a_total_in_every_group() -> None:
    data = pd.DataFrame(
        {
            "sex": ["Male", "Female", "Total"] * 2,
            "year": [2020] * 3 + [2021] * 3,
            "people": [10, 12, 22, 11, 14, 25],
        }
    )

    assert _find(data) == (TotalRow("sex", "Total", ("people",), ("year",), 2, 2),)


def test_single_total_row_for_the_whole_table() -> None:
    data = pd.DataFrame(
        {
            "item": ["Rent", "Food", "Travel", "Power", "Grand total"],
            "cost": [
                Decimal("10.10"),
                Decimal("4.20"),
                Decimal("3.30"),
                Decimal("2.00"),
                Decimal("19.60"),
            ],
        },
        dtype=object,
    )

    found = _find(data)

    assert [(row.value, row.keys, row.matched_groups) for row in found] == [
        ("Grand total", (), 1)
    ]


@pytest.mark.parametrize(
    "data",
    [
        # A sum that matches in only one of two groups is a coincidence.
        pd.DataFrame(
            {
                "kind": ["a", "b", "c"] * 2,
                "year": [1, 1, 1, 2, 2, 2],
                "n": [1, 1, 2, 2, 3, 4],
            }
        ),
        # Zero totals match any zero parts and are never reported.
        pd.DataFrame(
            {
                "kind": ["a", "b", "c", "d"] * 2,
                "year": [1] * 4 + [2] * 4,
                "n": [0] * 8,
            }
        ),
        # A value repeated within a group is not one total row.
        pd.DataFrame(
            {
                "kind": ["t", "t", "a", "b", "c"] * 2,
                "year": [1] * 5 + [2] * 5,
                "n": [3, 3, 1, 1, 1] * 2,
            }
        ),
        # One matching group of two is not enough evidence.
        pd.DataFrame(
            {
                "kind": ["t", "a", "b", "t", "a", "b"],
                "year": [1, 1, 1, 2, 2, 2],
                "n": [3, 1, 2, 9, 1, 2],
                "z": ["x"] * 6,
            }
        ),
        # Too few rows to hold a total and three parts.
        pd.DataFrame({"kind": ["t", "a", "b"], "n": [3, 1, 2]}),
        # Missing amounts only: nothing to compare.
        pd.DataFrame({"kind": ["t", "a", "b", "c"], "n": [None] * 4}, dtype=object),
    ],
)
def test_coincidences_and_weak_evidence_are_not_reported(data: pd.DataFrame) -> None:
    assert _find(data) == ()


def test_unique_text_keys_and_large_tables_are_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = _yearly().assign(note=[f"n{i}" for i in range(12)])
    assert _find(data) == ()

    monkeypatch.setattr(totals, "MAX_ROWS", 5)
    assert _find(_yearly()) == ()


def test_work_budget_stops_the_search(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(totals, "MAX_ROW_CHECKS", 13)

    assert _find(_yearly()) == ()


def test_total_rows_become_a_quality_warning() -> None:
    table = _table(_yearly())

    (issue,) = totals.total_row_issues(table)

    assert issue.issue_type is QualityIssueType.TOTAL_ROW
    assert issue.severity is QualitySeverity.WARNING
    assert issue.column_name == "cause"
    assert issue.affected_count == 3
    assert "'All causes'" in issue.message
    assert "within each year" in issue.message
    assert dict(issue.evidence)["keys"] == ("year",)


def test_whole_table_total_message_has_no_group(tmp_path: Path) -> None:
    path = tmp_path / "budget.csv"
    path.write_text("item,cost\nRent,10\nFood,4\nTravel,3\nTotal,17\n", "utf-8")

    issues = VeriSight(settings=Settings()).analyze(path).analysis.issues

    (issue,) = [i for i in issues if i.issue_type is QualityIssueType.TOTAL_ROW]
    assert "within each" not in issue.message


def _context() -> QueryContext:
    dataset = LoadedDataset(tables=[_table(_yearly(), "deaths")])
    return QueryContextBuilder().build_from_dataset(dataset)


def test_context_lists_total_rows_for_the_sql_writer() -> None:
    context = _context()

    text = QueryContextFormatter().format(context)

    assert context.total_rows[0].value == "All causes"
    assert context.total_rows[0].group_by == ("year",)
    assert "ROWS THAT HOLD TOTALS" in text
    assert '"value": "All causes"' in text


@pytest.mark.parametrize(
    ("sql", "codes"),
    [
        (
            "SELECT SUM(deaths) FROM deaths WHERE year = 2021",
            ["total_rows_not_excluded"],
        ),
        ("SELECT SUM(deaths) FROM deaths WHERE cause <> 'All causes'", []),
        ("SELECT cause, SUM(deaths) FROM deaths GROUP BY cause", []),
        ("SELECT deaths FROM deaths WHERE year = 2021", []),
        ("SELECT SUM(d.deaths) FROM deaths d JOIN deaths e ON d.year = e.year", []),
        ("SELECT 1; SELECT 2", []),
        ("SELECT (", []),
    ],
)
def test_review_flags_sums_that_include_total_rows(sql: str, codes: list[str]) -> None:
    review = review_population("How many people died in 2021?", sql, _context())

    assert [warning.code for warning in review.warnings] == codes
    assert (review.status == "review_required") is bool(codes)


def test_review_reports_both_a_missing_filter_and_total_rows() -> None:
    review = review_population(
        "How many people died in floods?",
        "SELECT SUM(deaths) FROM deaths",
        _context(),
    )

    assert [(w.mentioned_value, w.code) for w in review.warnings] == [
        ("Flood", "question_category_not_explicitly_selected"),
        ("All causes", "total_rows_not_excluded"),
    ]


def test_review_categories_cover_columns_beyond_the_prompt_limit() -> None:
    kinds = [f"Kind{i:02d}" for i in range(12)]
    data = pd.DataFrame({"kind": kinds, "n": range(12)})
    dataset = LoadedDataset(tables=[_table(data, "items")])

    context = QueryContextBuilder().build_from_dataset(dataset)
    review = review_population(
        "How many Kind07 items are there?", "SELECT SUM(n) FROM items", context
    )

    assert context.observed_categories == ()
    assert context.review_categories[0].observed_nonmissing_values == tuple(kinds)
    assert review.warnings[0].mentioned_value == "Kind07"
    assert "Kind07" not in QueryContextFormatter().format(context)


def test_review_categories_respect_their_size_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from verisight.execution import context as context_module

    monkeypatch.setattr(context_module, "_REVIEW_VALUES_BUDGET", 10)
    data = pd.DataFrame({"a": ["alpha", "beta"], "b": ["gamma", "delta"]})
    dataset = LoadedDataset(tables=[_table(data, "letters")])

    context = QueryContextBuilder().build_from_dataset(dataset)

    assert [item.column for item in context.review_categories] == ["a"]


@pytest.mark.parametrize(
    ("value", "question", "flagged"),
    [
        ("Earthquake", "Total deaths from earthquakes?", True),
        ("Flood", "Total deaths from Floods?", True),
        ("Category", "How many categories?", True),
        ("Day", "How many days?", True),
        ("Box", "How many boxes?", True),
        ("Earthquake", "Total deaths excluding earthquakes?", False),
        ("A1", "How many A1s?", False),
    ],
)
def test_category_mentions_include_regular_plurals(
    value: str, question: str, flagged: bool
) -> None:
    context = QueryContext(
        relations=(),
        review_categories=(ObservedCategoryValues("t", "kind", (value, "Other")),),
    )

    review = review_population(question, "SELECT COUNT(*) FROM t", context)

    assert (review.status == "review_required") is flagged
