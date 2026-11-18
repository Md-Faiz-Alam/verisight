"""Audit checks that read only the SQL and the loaded rows, in any language."""

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from verisight.config import Settings
from verisight.execution.sql_audit import audit_sql
from verisight.ingestion.models import LoadedDataset
from verisight.ingestion.service import DatasetLoader

STRUCTURAL = {
    "identifier_aggregated",
    "text_ordered",
    "join_key_format",
    "utc_dates",
}
# Questions in other languages: these checks never read the wording.
QUESTIONS = ("¿Cuál es el total?", "Quelle est la somme ?", "合計はいくらですか?")


def _load(tmp_path: Path, files: dict[str, str]) -> LoadedDataset:
    paths = []
    for name, text in files.items():
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    return DatasetLoader(Settings(_env_file=None)).load(paths)  # type: ignore[call-arg]


def _codes(dataset: LoadedDataset, sql: str, question: str = QUESTIONS[0]) -> set[str]:
    audit = audit_sql(question=question, sql=sql, result=None, dataset=dataset)
    assert audit.assessed
    return {finding.code for finding in audit.findings} & STRUCTURAL


def _orders(rows: int = 30) -> str:
    lines = ["order_id,year,amount,qty"]
    lines += [
        f"{1000 + i},{2000 + i % 20},{(i * 37) % 500 + 0.5},{i % 7}"
        for i in range(rows)
    ]
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize("question", QUESTIONS)
@pytest.mark.parametrize(
    ("sql", "flagged"),
    [
        ("SELECT SUM(order_id) FROM orders", True),
        ("SELECT AVG(order_id) FROM orders", True),
        ("SELECT SUM(year) FROM orders", True),
        # Counting identifiers, or averaging years, can be meant.
        ("SELECT COUNT(order_id) FROM orders", False),
        ("SELECT AVG(year) FROM orders", False),
        ("SELECT SUM(DISTINCT order_id) FROM orders", False),
        ("SELECT SUM(amount) FROM orders", False),
        ("SELECT SUM(qty) FROM orders", False),
        ("SELECT SUM(CASE WHEN order_id > 1010 THEN amount END) FROM orders", False),
    ],
)
def test_adding_up_identifiers_or_years_is_flagged(
    tmp_path: Path, sql: str, flagged: bool, question: str
) -> None:
    dataset = _load(tmp_path, {"orders.csv": _orders()})

    assert ("identifier_aggregated" in _codes(dataset, sql, question)) is flagged


def test_a_small_table_says_too_little_about_identifiers(tmp_path: Path) -> None:
    dataset = _load(tmp_path, {"orders.csv": _orders(rows=5)})

    assert _codes(dataset, "SELECT SUM(order_id) FROM orders") == set()


def _codes_file(values: list[Any]) -> dict[str, str]:
    return {"items.json": json.dumps([{"code": v, "label": "x"} for v in values])}


@pytest.mark.parametrize(
    ("values", "sql", "flagged"),
    [
        (
            ["9", "10", "100", "007"],
            "SELECT COUNT(*) FROM items WHERE code > '50'",
            True,
        ),
        (["9", "10", "100", "007"], "SELECT MAX(code) FROM items", True),
        (["9", "10", "100", "007"], "SELECT MIN(code) FROM items", True),
        (
            ["9", "10", "100", "007"],
            "SELECT COUNT(*) FROM items WHERE code BETWEEN '1' AND '50'",
            True,
        ),
        # Dates the loader could not read: day and month order is unknown.
        (
            ["01/02/2024", "03/04/2024", "11/12/2023"],
            "SELECT MAX(code) FROM items",
            True,
        ),
        # Cast first, equality, equal-length codes and ISO dates are all fine.
        (
            ["9", "10", "100", "007"],
            "SELECT MAX(CAST(code AS INTEGER)) FROM items",
            False,
        ),
        (
            ["9", "10", "100", "007"],
            "SELECT COUNT(*) FROM items WHERE code = '10'",
            False,
        ),
        (["001", "002", "010"], "SELECT MAX(code) FROM items", False),
        (["2024-01-05", "2024-01-10"], "SELECT MAX(code) FROM items", False),
        (["a", "b"], "SELECT MAX(code) FROM items", False),
    ],
)
def test_text_holding_numbers_or_dates_compared_by_order_is_flagged(
    tmp_path: Path, values: list[Any], sql: str, flagged: bool
) -> None:
    dataset = _load(tmp_path, _codes_file(values))

    assert ("text_ordered" in _codes(dataset, sql)) is flagged


CUSTOMERS = "customer_id,region\n" + "".join(
    f"c{i:03d},{'West' if i % 2 else 'East'}\n" for i in range(1, 21)
)


@pytest.mark.parametrize(
    ("orders", "flagged"),
    [
        # Upper case against lower case: no exact match, all loose matches.
        ("".join(f"{i},C{i:03d},5\n" for i in range(1, 21)), True),
        ("".join(f"{i},c{i:03d},5\n" for i in range(1, 21)), False),
        # Keys that really are different are not a formatting problem.
        ("".join(f"{i},z{i:03d},5\n" for i in range(1, 21)), False),
    ],
)
def test_join_keys_written_differently_are_flagged(
    tmp_path: Path, orders: str, flagged: bool
) -> None:
    dataset = _load(
        tmp_path,
        {
            "orders.csv": "order_id,customer_id,amount\n" + orders,
            "customers.csv": CUSTOMERS,
        },
    )
    sql = (
        "SELECT SUM(o.amount) FROM orders AS o JOIN customers AS c "
        "ON o.customer_id = c.customer_id WHERE c.region = 'West'"
    )

    assert ("join_key_format" in _codes(dataset, sql)) is flagged


def test_join_keys_that_lost_their_leading_zeros_are_flagged(tmp_path: Path) -> None:
    # Codes like 007 stay text; the same codes typed as numbers lose the zeros.
    dataset = _load(
        tmp_path,
        {
            "stores.csv": "store_code,city\n"
            + "".join(f"{i:03d},City{i}\n" for i in range(1, 21)),
            "sales.csv": "sale_id,store_code,amount\n"
            + "".join(f"{i},{i},5\n" for i in range(1, 21)),
        },
    )
    sql = (
        "SELECT SUM(s.amount) FROM sales AS s JOIN stores AS t "
        "ON s.store_code = t.store_code"
    )

    assert "join_key_format" in _codes(dataset, sql)


def test_a_join_with_no_keys_on_one_side_is_left_to_other_checks(
    tmp_path: Path,
) -> None:
    dataset = _load(
        tmp_path,
        {
            "orders.csv": "order_id,customer_id,amount\n1,,5\n2,,6\n",
            "customers.csv": CUSTOMERS,
        },
    )
    sql = (
        "SELECT SUM(o.amount) FROM orders AS o JOIN customers AS c "
        "ON o.customer_id = c.customer_id"
    )

    assert _codes(dataset, sql) == set()


BENCHMARK = Path(__file__).resolve().parents[1] / "evaluation" / "benchmark"


def test_no_structural_check_fires_on_the_public_benchmark(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location(
        "benchmark_for_audit", BENCHMARK / "make_benchmark.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["benchmark_for_audit"] = module
    spec.loader.exec_module(module)
    answerable = [q for q in module.build(tmp_path) if q.control_sql is not None]

    assert len(answerable) == 20
    for question in answerable:
        dataset = DatasetLoader(Settings(_env_file=None)).load(  # type: ignore[call-arg]
            [BENCHMARK / "data" / name for name in question.files]
        )
        found = _codes(dataset, question.control_sql, question.text)
        assert found == set(), question.question_id


ZONED = "event_id,ts\n1,2024-01-02T01:00:00+05:30\n2,2024-01-02T10:00:00+00:00\n"
UTC_ONLY = "event_id,ts\n1,2024-01-02T01:00:00Z\n2,2024-01-02T10:00:00+00:00\n"


@pytest.mark.parametrize(
    ("sql", "flagged"),
    [
        (
            "SELECT COUNT(*) FROM events WHERE CAST(ts AS DATE) = DATE '2024-01-02'",
            True,
        ),
        ("SELECT DATE_TRUNC('month', ts), COUNT(*) FROM events GROUP BY 1", True),
        ("SELECT YEAR(ts) FROM events", True),
        ("SELECT date_part('day', ts) FROM events", True),
        ("SELECT COUNT(*) FROM events WHERE ts >= '2024-01-02'", True),
        (
            "SELECT COUNT(*) FROM events "
            "WHERE (ts) BETWEEN '2024-01-01' AND '2024-01-31'",
            True,
        ),
        # Exact instants, and times compared as times, are the same in any zone.
        ("SELECT MAX(ts) FROM events", False),
        ("SELECT COUNT(*) FROM events WHERE ts >= '2024-01-02 05:00:00'", False),
        ("SELECT CAST(ts AS VARCHAR) FROM events", False),
        ("SELECT upper(CAST(ts AS VARCHAR)) FROM events", False),
    ],
)
def test_dates_read_from_times_moved_to_utc_are_flagged(
    tmp_path: Path, sql: str, flagged: bool
) -> None:
    dataset = _load(tmp_path, {"events.csv": ZONED})

    assert ("utc_dates" in _codes(dataset, sql)) is flagged


def test_times_already_in_utc_move_no_date(tmp_path: Path) -> None:
    dataset = _load(tmp_path, {"events.csv": UTC_ONLY})
    sql = "SELECT COUNT(*) FROM events WHERE CAST(ts AS DATE) = DATE '2024-01-02'"

    assert _codes(dataset, sql) == set()
    assert dataset.tables[0].value_notes[0].detail == "time zones converted to UTC"
