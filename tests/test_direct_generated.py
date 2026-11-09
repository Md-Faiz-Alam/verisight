"""Generated plain questions, checked against answers calculated separately."""

import random
import statistics
from collections.abc import Callable
from pathlib import Path

import pytest

from verisight.config import Settings
from verisight.execution.direct import DirectAnswer, DirectAnswerer
from verisight.execution.engine import DuckDBExecutor
from verisight.ingestion.models import LoadedDataset
from verisight.ingestion.service import DatasetLoader

SETTINGS = Settings(allow_llm_data_disclosure=False, gemini_api_key=None)
REGIONS = ("East", "West", "North")
YEARS = (2022, 2023, 2024)
PRODUCTS = ("pen", "ink", "cap", "bag", "mug")
Row = tuple[str, int, str, int]


def _rows() -> list[Row]:
    rng = random.Random(11)
    return [
        (
            rng.choice(REGIONS),
            rng.choice(YEARS),
            rng.choice(PRODUCTS),
            rng.randint(1, 500),
        )
        for _ in range(240)
    ]


ROWS = _rows()
CALCULATIONS: dict[str, Callable[[list[int]], float]] = {
    "total": sum,
    "average": statistics.mean,
    "median": statistics.median,
    "highest": max,
    "lowest": min,
}


def _prices(region: str | None = None, year: int | None = None) -> list[int]:
    return [
        row[3]
        for row in ROWS
        if (region is None or row[0] == region) and (year is None or row[1] == year)
    ]


def _measures() -> list[tuple[str, float]]:
    cases = []
    for word, calculate in CALCULATIONS.items():
        cases.append((f"What is the {word} price?", calculate(_prices())))
        for region in REGIONS:
            value = calculate(_prices(region))
            cases.append((f"What is the {word} price for {region}?", value))
            cases.append((f"What is the {word} price where region is {region}?", value))
            for year in YEARS:
                cases.append(
                    (
                        f"What is the {word} price in {region} in {year}?",
                        calculate(_prices(region, year)),
                    )
                )
    return cases


def _counts() -> list[tuple[str, float]]:
    cases: list[tuple[str, float]] = [
        ("How many rows are in sales?", len(ROWS)),
        ("How many different products?", len({row[2] for row in ROWS})),
    ]
    for region in REGIONS:
        cases.append(
            (
                f"How many rows have region equal to {region}?",
                sum(row[0] == region for row in ROWS),
            )
        )
        cases.append(
            (
                f"How many different products in {region}?",
                len({row[2] for row in ROWS if row[0] == region}),
            )
        )
    return cases


@pytest.fixture(scope="module")
def sales(tmp_path_factory: pytest.TempPathFactory) -> LoadedDataset:
    path: Path = tmp_path_factory.mktemp("sales") / "sales.csv"
    lines = "".join(f"{a},{b},{c},{d}\n" for a, b, c, d in ROWS)
    path.write_text("region,year,product,price\n" + lines, encoding="utf-8")
    return DatasetLoader(SETTINGS).load([path])


@pytest.mark.parametrize(("question", "expected"), [*_measures(), *_counts()])
def test_plain_questions_match_the_separate_calculation(
    sales: LoadedDataset, question: str, expected: float
) -> None:
    answer = DirectAnswerer(sales, DuckDBExecutor(max_result_rows=10)).answer(question)

    assert isinstance(answer, DirectAnswer)
    assert float(str(answer.observation.result.rows[0][0])) == pytest.approx(expected)
