"""The same rows give the same types and answers from every supported format."""

import json
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

from verisight import VeriSight
from verisight.config import Settings

# Above 2**53, where a float would round most integers, yet exact as a double,
# because Excel stores every number as one.
WIDE = 2**60
ROWS: list[dict[str, object]] = [
    {
        "id": 1,
        "units": WIDE,
        "price": 19.95,
        "region": "East",
        "day": "2024-01-31",
        "paid": True,
        "discount": 5,
    },
    {
        "id": 2,
        "units": 2,
        "price": 0.1,
        "region": "West",
        "day": "2024-02-29",
        "paid": False,
        "discount": None,
    },
    {
        "id": 3,
        "units": 3,
        "price": 100.0,
        "region": "East",
        "day": "2024-03-01",
        "paid": True,
        "discount": 10,
    },
]
COLUMNS = list(ROWS[0])


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _delimited(path: Path, separator: str) -> None:
    lines = [separator.join(COLUMNS)]
    lines += [separator.join(_cell(row[name]) for name in COLUMNS) for row in ROWS]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _excel(path: Path) -> None:
    pd.DataFrame(ROWS, columns=COLUMNS).astype(object).to_excel(
        path, index=False, sheet_name="sales"
    )


WRITERS: dict[str, Callable[[Path], object]] = {
    "sales.csv": lambda path: _delimited(path, ","),
    "sales.tsv": lambda path: _delimited(path, "\t"),
    "sales.json": lambda path: path.write_text(json.dumps(ROWS), encoding="utf-8"),
    "sales.jsonl": lambda path: path.write_text(
        "".join(json.dumps(row) + "\n" for row in ROWS), encoding="utf-8"
    ),
    "sales.xlsx": _excel,
}

QUERY = (
    "SELECT SUM(units) AS units, COUNT(*) AS n, COUNT(discount) AS discounts, "
    "SUM(discount) AS discount, ROUND(SUM(price), 2) AS price, "
    "MIN(day) AS first_day, typeof(MIN(day)) AS day_type, "
    "SUM(CASE WHEN paid THEN 1 ELSE 0 END) AS paid, "
    "COUNT(*) FILTER (WHERE region = 'East') AS east "
    "FROM sales"
)


@pytest.fixture(scope="module")
def answers(tmp_path_factory: pytest.TempPathFactory) -> dict[str, tuple[object, ...]]:
    app = VeriSight(settings=Settings(_env_file=None, allow_llm_data_disclosure=False))  # type: ignore[call-arg]
    found: dict[str, tuple[object, ...]] = {}
    for name, write in WRITERS.items():
        path = tmp_path_factory.mktemp(name.replace(".", "_")) / name
        write(path)
        found[name] = app.execute([path], QUERY).rows[0]
    return found


@pytest.mark.parametrize("name", list(WRITERS))
def test_every_format_gives_the_same_answers(
    answers: dict[str, tuple[object, ...]], name: str
) -> None:
    units, n, discounts, discount, price, first_day, day_type, paid, east = answers[
        name
    ]

    assert int(str(units)) == WIDE + 5
    assert (n, discounts, int(str(discount))) == (3, 2, 15)
    assert float(str(price)) == 120.05
    assert str(first_day).startswith("2024-01-31")
    assert str(day_type).startswith("TIMESTAMP")
    assert (paid, east) == (2, 2)


def test_every_format_agrees_with_the_csv_file(
    answers: dict[str, tuple[object, ...]],
) -> None:
    expected = answers["sales.csv"]

    assert {name: row for name, row in answers.items() if row != expected} == {}
