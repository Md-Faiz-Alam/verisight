"""Correct queries the SQL audit must not flag: codes, percentiles and names."""

from pathlib import Path

import pytest

from verisight.config import Settings
from verisight.execution.context import QueryContextBuilder
from verisight.execution.sql_audit import audit_sql
from verisight.ingestion.models import LoadedDataset
from verisight.ingestion.service import DatasetLoader

SETTINGS = Settings(allow_llm_data_disclosure=False, gemini_api_key=None)
TEAMS = (
    "year,team,franchise,league,wins,attendance\n"
    "2020,BOS,BOS,AL,80,\n"
    "2021,BOS,BOS,AL,92,2000\n"
    "2020,NYA,NYY,AL,90,3000\n"
    "2021,NYA,NYY,AL,95,4000\n"
    "2021,ATL,ATL,NL,88,2500\n"
)
FRANCHISES = (
    "franchise,franchise_name,league\n"
    "BOS,Boston Red Sox,AL\n"
    "NYY,New York Yankees,AL\n"
    "ATL,Atlanta Braves,NL\n"
    "CRS,Cleveland Red Sox,AL\n"
)


@pytest.fixture
def baseball(tmp_path: Path) -> LoadedDataset:
    (tmp_path / "teams.csv").write_text(TEAMS, encoding="utf-8")
    (tmp_path / "franchises.csv").write_text(FRANCHISES, encoding="utf-8")
    return DatasetLoader(SETTINGS).load(
        [tmp_path / "teams.csv", tmp_path / "franchises.csv"]
    )


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
    ("sql", "flagged"),
    [
        # The franchise code stands for exactly one franchise name.
        ("SELECT SUM(wins) FROM teams WHERE franchise = 'BOS'", False),
        (
            "SELECT SUM(wins) FROM teams WHERE franchise IN "
            "(SELECT franchise FROM franchises WHERE franchise = 'BOS')",
            False,
        ),
        # A code that belongs to another franchise does not select it.
        ("SELECT SUM(wins) FROM teams WHERE franchise = 'NYY'", True),
        # A league holds several franchises, so it is not the franchise's code.
        ("SELECT SUM(wins) FROM teams WHERE league = 'AL'", True),
    ],
)
def test_a_code_that_stands_for_the_named_value_selects_it(
    baseball: LoadedDataset, sql: str, flagged: bool
) -> None:
    question = "How many wins did the Boston Red Sox franchise record?"
    found = "named_value_not_selected" in _codes(baseball, question, sql)
    assert found is flagged


@pytest.mark.parametrize(
    ("sql", "flagged"),
    [
        (
            "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY attendance) "
            "FROM teams WHERE year = 2021",
            False,
        ),
        ("SELECT quantile_cont(attendance, 0.5) FROM teams WHERE year = 2021", False),
        ("SELECT median(attendance) FROM teams WHERE year = 2021", False),
        ("SELECT COUNT(*) FROM teams WHERE year = 2021", True),
    ],
)
def test_a_percentile_leaves_out_missing_values(
    baseball: LoadedDataset, sql: str, flagged: bool
) -> None:
    question = "What is the median recorded attendance per team in 2021?"
    found = "unknown_values_counted" in _codes(baseball, question, sql)
    assert found is flagged


def test_a_vague_word_inside_a_name_is_not_vague(baseball: LoadedDataset) -> None:
    question = "What is the average attendance for the new york yankees franchise?"
    sql = "SELECT AVG(attendance) FROM teams WHERE franchise = 'NYY'"
    assert "assumed_definition" not in _codes(baseball, question, sql)


def test_a_vague_word_outside_a_name_is_still_vague(baseball: LoadedDataset) -> None:
    question = "What is the average attendance for new franchises?"
    sql = "SELECT AVG(attendance) FROM teams WHERE franchise = 'NYY'"
    assert "assumed_definition" in _codes(baseball, question, sql)
