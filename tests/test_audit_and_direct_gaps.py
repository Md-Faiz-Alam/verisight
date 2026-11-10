"""Mistakes the SQL audit must name, and questions answered without a model."""

import logging
from collections.abc import Callable
from pathlib import Path

import pytest

from verisight.config import Settings
from verisight.execution.context import QueryContextBuilder
from verisight.execution.direct import Clarification, DirectAnswer, DirectAnswerer
from verisight.execution.engine import DuckDBExecutor
from verisight.execution.sql_audit import audit_sql
from verisight.execution.validation import _question_mentions_category
from verisight.ingestion.models import LoadedDataset
from verisight.ingestion.service import DatasetLoader
from verisight.logging import LOGGER_NAME, SecretRedactingFormatter
from verisight.web import create_app
from verisight.web.store import RateLimiter

SETTINGS = Settings(allow_llm_data_disclosure=False, gemini_api_key=None)
ROWS = (
    "product,genre,region,year,price,alt_price,note,sold_on\n"
    "pen,Comedy,East,2023,10,1,,2024-04-30\n"
    "ink,Romantic Comedy,East,2024,20,2,x,2024-05-01\n"
    "cap,Drama,West,2024,30,3,,2024-05-01\n"
    "pen,Comedy,West,2024,40,4,y,2024-04-30\n"
)


@pytest.fixture
def shop(tmp_path: Path) -> LoadedDataset:
    path = tmp_path / "orders.csv"
    path.write_text(ROWS, encoding="utf-8")
    return DatasetLoader(SETTINGS).load([path])


def _codes(dataset: LoadedDataset, question: str, sql: str) -> set[str]:
    context = QueryContextBuilder().build_from_dataset(dataset)
    audit = audit_sql(
        question=question,
        sql=sql,
        result=None,
        dataset=dataset,
        categories=context.review_categories,
    )
    return {finding.code for finding in audit.findings}


@pytest.mark.parametrize(
    ("question", "sql", "code", "found"),
    [
        (
            "How many different products are there?",
            "SELECT COUNT(product) FROM orders",
            "distinct_not_counted",
            True,
        ),
        (
            "How many unique products are there?",
            "SELECT COUNT(DISTINCT product) FROM orders",
            "distinct_not_counted",
            False,
        ),
        (
            "How many orders have no recorded note?",
            "SELECT COUNT(*) FROM orders WHERE note IS NOT NULL",
            "missing_values_ignored",
            True,
        ),
        (
            "How many orders have no recorded note?",
            "SELECT COUNT(*) FROM orders WHERE note IS NULL",
            "missing_values_ignored",
            False,
        ),
        (
            "What is the mean price from 2023 to 2024?",
            "SELECT AVG(price) FROM orders WHERE year > 2023",
            "range_end_left_out",
            True,
        ),
        (
            "What is the mean price from 2023 to 2024?",
            "SELECT AVG(price) FROM orders WHERE year < 2024",
            "range_end_left_out",
            True,
        ),
        (
            "What is the mean price from 2023 to 2024?",
            "SELECT AVG(price) FROM orders WHERE year BETWEEN 2023 AND 2024",
            "range_end_left_out",
            False,
        ),
        (
            "How many Comedy orders are there?",
            "SELECT COUNT(*) FROM orders WHERE genre LIKE '%Comedy%'",
            "filter_too_broad",
            True,
        ),
        (
            "How many Comedy orders are there?",
            "SELECT COUNT(*) FROM orders WHERE genre = 'Comedy'",
            "filter_too_broad",
            False,
        ),
        (
            "How many orders include Comedy?",
            "SELECT COUNT(*) FROM orders WHERE genre LIKE '%Comedy%'",
            "filter_too_broad",
            False,
        ),
        (
            "How many Drama orders are there?",
            "SELECT COUNT(*) FROM orders WHERE genre LIKE 'Dra%'",
            "filter_too_broad",
            False,
        ),
        (
            "How many Comedy orders are there?",
            "SELECT COUNT(*) FROM orders WHERE product LIKE '%o%' AND genre = 'Comedy'",
            "filter_too_broad",
            False,
        ),
    ],
)
def test_the_audit_names_the_mistake(
    shop: LoadedDataset, question: str, sql: str, code: str, found: bool
) -> None:
    assert (code in _codes(shop, question, sql)) is found


@pytest.mark.parametrize(
    ("question", "first", "second"),
    [
        ("Give East minus West in total price.", "region = 'East'", "region = 'West'"),
        ("Give the 2023 value minus the 2024 value.", "year = 2023", "year = 2024"),
        (
            "Give April 30 minus May 1.",
            "sold_on = DATE '2024-04-30'",
            "sold_on = DATE '2024-05-01'",
        ),
    ],
)
def test_a_stated_subtraction_must_keep_its_order(
    shop: LoadedDataset, question: str, first: str, second: str
) -> None:
    right = f"({_sub(first)}) - ({_sub(second)})"
    wrong = f"({_sub(second)}) - ({_sub(first)})"

    assert "reversed_subtraction" not in _codes(shop, question, f"SELECT {right}")
    assert "reversed_subtraction" in _codes(shop, question, f"SELECT {wrong}")


def _sub(condition: str) -> str:
    return f"SELECT SUM(price) FROM orders WHERE {condition}"


def test_columns_can_identify_each_side_of_a_subtraction(shop: LoadedDataset) -> None:
    question = "Give price minus alt price."

    right = "SELECT price - alt_price FROM orders"
    wrong = "SELECT alt_price - price FROM orders"

    assert "reversed_subtraction" not in _codes(shop, question, right)
    assert "reversed_subtraction" in _codes(shop, question, wrong)


def test_a_label_held_by_two_columns_still_identifies_a_side(tmp_path: Path) -> None:
    path = tmp_path / "strikes.csv"
    path.write_text(
        "damage,size,n\nMedium,Small,1\nHigh,Medium,2\nLow,Large,3\n", encoding="utf-8"
    )
    dataset = DatasetLoader(SETTINGS).load([path])
    medium = "SUM(n) FILTER (WHERE damage = 'Medium')"
    low = "SUM(n) FILTER (WHERE damage = 'Low')"

    codes = _codes(
        dataset, "Give Medium minus Low.", f"SELECT {low} - {medium} FROM strikes"
    )

    assert "reversed_subtraction" in codes


def test_a_subtraction_with_nothing_to_compare_is_not_flagged(
    shop: LoadedDataset,
) -> None:
    sql = "WITH t AS (SELECT 1 AS a, 2 AS b) SELECT b - a FROM t"

    assert "reversed_subtraction" not in _codes(shop, "Give East minus West.", sql)


def test_a_than_question_still_checks_the_order(shop: LoadedDataset) -> None:
    question = "How much more did East sell than West?"
    east = "SELECT SUM(price) FROM orders WHERE region = 'East'"
    west = "SELECT SUM(price) FROM orders WHERE region = 'West'"

    assert "reversed_subtraction" in _codes(
        shop, question, f"SELECT ({west}) - ({east})"
    )
    assert "reversed_subtraction" not in _codes(
        shop, question, f"SELECT ({east}) - ({west})"
    )


def test_the_whole_set_is_not_a_kind_of_row() -> None:
    assert not _question_mentions_category("How many of the deaths were late?", "Death")
    assert _question_mentions_category("How many deaths were late?", "Death")


def _ask(dataset: LoadedDataset, question: str) -> object:
    return DirectAnswerer(dataset, DuckDBExecutor(max_result_rows=100)).answer(question)


@pytest.mark.parametrize(
    ("question", "value"),
    [
        ("What is the median price?", 25.0),
        ("How many different product?", 3),
        ("How many different products?", 3),
        ("How many unique products in West?", 2),
    ],
)
def test_more_questions_are_answered_without_a_model(
    shop: LoadedDataset, question: str, value: float
) -> None:
    answer = _ask(shop, question)

    assert isinstance(answer, DirectAnswer)
    assert answer.observation.result.rows[0][0] == value


@pytest.mark.parametrize(
    "question",
    [
        "How many different colours are there?",
        "How many different products in Nowhere?",
        "What is the average price in East in Nowhere?",
        "What is the average price in East in West?",
        "What is the average price in 2024-01?",
        "What is the average price in 2024?",
    ],
)
def test_unresolved_questions_go_to_the_model(
    shop: LoadedDataset, question: str
) -> None:
    assert _ask(shop, question) is None


def test_a_value_in_two_columns_is_not_guessed_in_a_multi_part_question(
    tmp_path: Path,
) -> None:
    path = tmp_path / "t.csv"
    path.write_text("a,b,c,n\nx,x,East,1\ny,y,West,2\n", encoding="utf-8")
    dataset = DatasetLoader(SETTINGS).load([path])

    assert _ask(dataset, "What is the average n in x in East?") is None
    assert isinstance(_ask(dataset, "What is the average n in x?"), Clarification)


def test_two_conditions_can_use_a_year_column(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    path.write_text("region,year,n\nEast,2023,1\nEast,2024,3\nWest,2024,9\n", "utf-8")
    dataset = DatasetLoader(SETTINGS).load([path])

    answer = _ask(dataset, "What is the average n in East in 2024?")

    assert isinstance(answer, DirectAnswer)
    assert answer.observation.result.rows[0][0] == 3.0
    assert _ask(dataset, "What is the average n in 20245?") is None
    assert _ask(dataset, "What is the average n in 2024-01?") is None


def test_a_year_needs_a_year_column(tmp_path: Path) -> None:
    path = tmp_path / "t.csv"
    path.write_text("a,n\nx,1\ny,2\n", encoding="utf-8")

    dataset = DatasetLoader(SETTINGS).load([path])

    assert _ask(dataset, "What is the average n in 2024?") is None


def test_the_website_turns_on_secret_redaction() -> None:
    create_app(settings=Settings(gemini_api_key=None))

    handlers = logging.getLogger(LOGGER_NAME).handlers
    assert isinstance(handlers[0].formatter, SecretRedactingFormatter)


def _clock(values: list[float]) -> Callable[[], float]:
    pending = iter(values)
    return lambda: next(pending)


def test_a_returning_client_keeps_only_events_from_the_last_hour() -> None:
    limiter = RateLimiter(5, clock=_clock([10.0, 3000.0, 3700.0]))

    limiter.allow("a")
    limiter.allow("a")
    limiter.allow("a")

    assert list(limiter._events["a"]) == [3000.0, 3700.0]


def test_clients_that_stop_asking_are_forgotten() -> None:
    limiter = RateLimiter(5, clock=_clock([10.0, 20.0, 5000.0]))

    limiter.allow("a")
    limiter.allow("b")
    limiter.allow("c")

    assert set(limiter._events) == {"c"}


CODED = (
    "yr,day,amount,score\n"
    "0,2011-01-05,10,\n"
    "0,2011-02-05,20,0\n"
    "1,2012-01-05,30,5\n"
    "1,2012-02-05,40,0\n"
)


@pytest.fixture
def coded(tmp_path: Path) -> LoadedDataset:
    path = tmp_path / "rentals.csv"
    path.write_text(CODED, encoding="utf-8")
    return DatasetLoader(SETTINGS).load([path])


@pytest.mark.parametrize(
    ("year", "sql", "found"),
    [
        (2012, "SELECT SUM(amount) FROM rentals WHERE yr = 1", False),
        (2012, "SELECT SUM(amount) FROM rentals WHERE 1 = yr", False),
        (2011, "SELECT SUM(amount) FROM rentals WHERE yr = 1", True),
        (2012, "SELECT SUM(amount) FROM rentals", True),
        (2012, "SELECT SUM(amount) FROM rentals WHERE yr = 9", True),
        (2012, "SELECT SUM(amount) FROM rentals WHERE region = 1", True),
        (2012, "SELECT SUM(amount) FROM rentals WHERE yr = amount", True),
    ],
    ids=[
        "right",
        "reversed",
        "wrong-year",
        "no-filter",
        "no-rows",
        "no-column",
        "no-number",
    ],
)
def test_a_coded_year_is_read_from_the_date_column(
    coded: LoadedDataset, year: int, sql: str, found: bool
) -> None:
    question = f"What was the total amount in {year}?"

    assert ("period_not_selected" in _codes(coded, question, sql)) is found


def test_a_coded_year_without_a_date_column_stays_unproven(tmp_path: Path) -> None:
    path = tmp_path / "rentals.csv"
    path.write_text("yr,amount\n0,10\n1,20\n", encoding="utf-8")
    dataset = DatasetLoader(SETTINGS).load([path])
    sql = "SELECT SUM(amount) FROM rentals WHERE yr = 1"

    codes = _codes(dataset, "What was the total amount in 2012?", sql)

    assert "period_not_selected" in codes


@pytest.mark.parametrize(
    ("question", "sql", "found"),
    [
        (
            "How many rows have a recorded score of exactly zero?",
            "SELECT COUNT(*) FROM rentals WHERE score = 0",
            False,
        ),
        (
            "How many rows have a recorded score?",
            "SELECT COUNT(*) FROM rentals WHERE amount > 0",
            True,
        ),
    ],
    ids=["compares-that-column", "compares-another-column"],
)
def test_a_known_value_filter_must_cover_the_named_column(
    coded: LoadedDataset, question: str, sql: str, found: bool
) -> None:
    assert ("unknown_values_counted" in _codes(coded, question, sql)) is found
