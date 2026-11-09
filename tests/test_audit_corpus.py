"""Correct and deliberately wrong SQL, on generated tables.

This protects the audit against regressions. Because the cases were written with
the audit in view, its catch rate here does not estimate the rate on new mistakes.
Mistakes marked as not caught are real limits, kept so they stay visible.
"""

from pathlib import Path
from typing import NamedTuple

import pytest

from verisight.config import Settings
from verisight.execution.context import QueryContext, QueryContextBuilder
from verisight.execution.sql_audit import audit_sql
from verisight.execution.validation import review_population
from verisight.ingestion.models import LoadedDataset
from verisight.ingestion.service import DatasetLoader

SETTINGS = Settings(allow_llm_data_disclosure=False, gemini_api_key=None)
ORDERS = (
    "order_id,region,status,channel,year,amount,discount,note,day,product,bill_to,ship_to\n"
    "1,East,Shipped,Web,2022,100,5,,2024-03-01,Pen,1,2\n"
    "2,East,Returned,web ,2022,250,,x,2024-03-02,Pen Refill,2,3\n"
    "3,West,Shipped,Store,2023,40,2,,2024-03-01,Ink,3,1\n"
    "4,West,Open,Web,2023,90,1,y,2024-03-02,Pen,1,1\n"
    "5,North,Shipped,Store,2023,300,8,,2024-03-02,Cap,2,2\n"
    "6,North,Open,Web,2024,70,3,z,2024-03-01,Ink,3,2\n"
)
ITEMS = "order_id,sku\n1,a\n1,b\n2,c\n3,d\n3,e\n3,f\n4,g\n5,h\n6,i\n"
CUSTOMERS = "customer_id,area\n1,East\n2,West\n3,North\n"


class Pair(NamedTuple):
    question: str
    correct: str
    wrong: str
    caught: bool


def _count(condition: str) -> str:
    return f"SELECT COUNT(*) FROM orders WHERE {condition}"


def _total(condition: str) -> str:
    return f"SELECT SUM(amount) FROM orders WHERE {condition}"


def _minus(first: str, second: str) -> tuple[str, str]:
    return (
        f"SELECT ({_total(first)}) - ({_total(second)})",
        f"SELECT ({_total(second)}) - ({_total(first)})",
    )


ALL_TOTAL = "SELECT SUM(amount) FROM orders"
EAST = _total("region = 'East'")
AT_LEAST = "How many orders have an amount of at least 100?"
ABOVE = "How many orders have an amount of more than 100?"
RANGE = "What is the mean amount from 2022 to 2023?"
BETWEEN = "SELECT AVG(amount) FROM orders WHERE year BETWEEN 2022 AND 2023"
NO_NOTE = "How many orders have no recorded note?"
MANY_REGIONS = "SELECT COUNT(DISTINCT region) FROM orders"
EAST_PRODUCTS = "SELECT COUNT(DISTINCT product) FROM orders WHERE region = 'East'"
SHARE = (
    "SELECT 100.0 * COUNT(*) FILTER (WHERE status = 'Shipped') / COUNT(*) FROM orders"
)
FEW_SHARE = "SELECT COUNT(*) FILTER (WHERE status = 'Shipped') / 100.0 FROM orders"
JOINED = "SELECT SUM(o.amount) FROM orders o JOIN items i ON o.order_id = i.order_id"
BILLED = (
    "SELECT COUNT(*) FROM orders o JOIN customers c ON o.{} = c.customer_id "
    "WHERE c.area = 'East'"
)
PAIRS = {
    "drops_a_named_value": Pair(
        "What is the total amount for East orders?", EAST, ALL_TOTAL, True
    ),
    "value_not_in_column": Pair(
        "What is the total amount for East orders?",
        EAST,
        _total("region = 'Eest'"),
        True,
    ),
    "misses_spellings": Pair(
        "How many orders came from Web?",
        _count("LOWER(TRIM(channel)) = 'web'"),
        _count("channel = 'Web'"),
        True,
    ),
    "sum_for_average": Pair(
        "What is the average amount?",
        "SELECT AVG(amount) FROM orders",
        ALL_TOTAL,
        True,
    ),
    "mean_for_median": Pair(
        "What is the median amount?",
        "SELECT MEDIAN(amount) FROM orders",
        "SELECT AVG(amount) FROM orders",
        True,
    ),
    "highest_without_filter": Pair(
        "What is the highest amount for West orders?",
        "SELECT MAX(amount) FROM orders WHERE region = 'West'",
        "SELECT MAX(amount) FROM orders",
        True,
    ),
    "maximum_for_lowest": Pair(
        "What is the lowest amount?",
        "SELECT MIN(amount) FROM orders",
        "SELECT MAX(amount) FROM orders",
        True,
    ),
    "year_left_out": Pair(
        "How many orders are from 2023?",
        _count("year = 2023"),
        "SELECT COUNT(*) FROM orders",
        True,
    ),
    "at_least_written_strictly": Pair(
        AT_LEAST, _count("amount >= 100"), _count("amount > 100"), True
    ),
    "more_than_written_loosely": Pair(
        ABOVE, _count("amount > 100"), _count("amount >= 100"), True
    ),
    "threshold_not_used": Pair(
        AT_LEAST, _count("amount >= 100"), _count("amount >= 50"), True
    ),
    "range_drops_the_start": Pair(
        RANGE, BETWEEN, "SELECT AVG(amount) FROM orders WHERE year > 2022", True
    ),
    "range_drops_the_end": Pair(
        RANGE, BETWEEN, "SELECT AVG(amount) FROM orders WHERE year < 2023", True
    ),
    "not_null_for_missing": Pair(
        NO_NOTE, _count("note IS NULL"), _count("note IS NOT NULL"), True
    ),
    "never_tests_missing": Pair(
        NO_NOTE, _count("note IS NULL"), "SELECT COUNT(*) FROM orders", True
    ),
    "rows_for_different_values": Pair(
        "How many different regions are there?",
        MANY_REGIONS,
        "SELECT COUNT(region) FROM orders",
        True,
    ),
    "rows_for_different_filtered": Pair(
        "How many different products were sold in East?",
        EAST_PRODUCTS,
        _count("region = 'East'"),
        True,
    ),
    "reversed_values": Pair(
        "Give East minus West in total amount.",
        *_minus("region = 'East'", "region = 'West'"),
        True,
    ),
    "reversed_years": Pair(
        "Give the 2023 value minus the 2022 value.",
        *_minus("year = 2023", "year = 2022"),
        True,
    ),
    "reversed_dates": Pair(
        "Give March 1 minus March 2.",
        *_minus("day = DATE '2024-03-01'", "day = DATE '2024-03-02'"),
        True,
    ),
    "reversed_columns": Pair(
        "Give amount minus discount.",
        "SELECT amount - discount FROM orders",
        "SELECT discount - amount FROM orders",
        True,
    ),
    "like_takes_in_too_much": Pair(
        "How many Pen orders are there?",
        _count("product = 'Pen'"),
        _count("product LIKE '%Pen%'"),
        True,
    ),
    "percentage_divided_down": Pair(
        "What percent of orders are Shipped?", SHARE, FEW_SHARE, True
    ),
    "join_repeats_rows": Pair("What is the total amount?", ALL_TOTAL, JOINED, True),
    "missing_counted_as_zero": Pair(
        "What is the average discount?",
        "SELECT AVG(discount) FROM orders",
        "SELECT AVG(COALESCE(discount, 0)) FROM orders",
        True,
    ),
    "wrong_measure_column": Pair(
        "What did the orders cost altogether?",
        ALL_TOTAL,
        "SELECT SUM(discount) FROM orders",
        False,
    ),
    "opposite_filter": Pair(
        "How many orders did not ship?",
        _count("status <> 'Shipped'"),
        _count("status = 'Shipped'"),
        False,
    ),
    "synonym_dropped": Pair(
        "How many orders were sent back?",
        _count("status = 'Returned'"),
        "SELECT COUNT(*) FROM orders",
        False,
    ),
    "wrong_join_column": Pair(
        "How many orders were billed to customers in the East area?",
        BILLED.format("bill_to"),
        BILLED.format("ship_to"),
        False,
    ),
    "under_includes_the_limit": Pair(
        "How many orders have an amount under 100?",
        _count("amount < 100"),
        _count("amount <= 100"),
        False,
    ),
    "rows_for_entities": Pair(
        "How many products were sold?",
        "SELECT COUNT(DISTINCT product) FROM orders",
        "SELECT COUNT(product) FROM orders",
        False,
    ),
}


@pytest.fixture(scope="module")
def shop(
    tmp_path_factory: pytest.TempPathFactory,
) -> tuple[LoadedDataset, QueryContext]:
    folder: Path = tmp_path_factory.mktemp("shop")
    paths = []
    for name, text in (
        ("orders", ORDERS),
        ("items", ITEMS),
        ("customers", CUSTOMERS),
    ):
        path = folder / f"{name}.csv"
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    dataset = DatasetLoader(SETTINGS).load(paths)
    return dataset, QueryContextBuilder().build_from_dataset(dataset)


def _flagged(
    shop: tuple[LoadedDataset, QueryContext], question: str, sql: str
) -> list[str]:
    dataset, context = shop
    audit = audit_sql(
        question=question,
        sql=sql,
        result=None,
        dataset=dataset,
        total_rows=context.total_rows,
        categories=context.review_categories,
    )
    found = [finding.detail for finding in audit.findings]
    if review_population(question, sql, context).status == "review_required":
        found.append("population review")
    return found


@pytest.mark.parametrize("name", PAIRS)
def test_correct_sql_gets_no_warning(
    shop: tuple[LoadedDataset, QueryContext], name: str
) -> None:
    pair = PAIRS[name]

    assert _flagged(shop, pair.question, pair.correct) == []


@pytest.mark.parametrize("name", PAIRS)
def test_each_wrong_query_is_caught_or_a_known_limit(
    shop: tuple[LoadedDataset, QueryContext], name: str
) -> None:
    pair = PAIRS[name]

    assert bool(_flagged(shop, pair.question, pair.wrong)) is pair.caught


def test_the_audit_meets_its_pass_mark() -> None:
    caught = sum(pair.caught for pair in PAIRS.values())

    assert caught / len(PAIRS) >= 0.75
