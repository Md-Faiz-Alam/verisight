"""Questions the data cannot answer, and years stored as codes."""

from pathlib import Path

import pytest

from verisight.config import Settings
from verisight.execution.context import (
    ObservedCodedYears,
    QueryContext,
    QueryContextBuilder,
)
from verisight.execution.formatting import QueryContextFormatter, format_coded_years
from verisight.execution.sql_audit import audit_sql
from verisight.ingestion.models import LoadedDataset
from verisight.ingestion.service import DatasetLoader

SETTINGS = Settings(allow_llm_data_disclosure=False, gemini_api_key=None)


def _load(tmp_path: Path, text: str, name: str = "data.csv") -> LoadedDataset:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return DatasetLoader(SETTINGS).load([path])


def _codes(dataset: LoadedDataset, question: str, sql: str) -> set[str]:
    audit = audit_sql(question=question, sql=sql, result=None, dataset=dataset)
    return {finding.code for finding in audit.findings}


SAMPLES = (
    "sample_id,acidity,score,price,customer_id,visits,cost\n"
    "1,7.4,7,$12.00,c1,3,$5.00\n"
    "2,7.8,5,$9.50,c2,1,$4.00\n"
    "3,6.1,7,$15.25,c1,2,$6.00\n"
)
AMOUNTS = "sample_id,amt,score\n1,$12.00,7\n2,$9.50,5\n"


@pytest.mark.parametrize(
    ("question", "sql", "found"),
    [
        (
            "What is the average selling price in euros for scores of at least 7?",
            "SELECT AVG(acidity) FROM data WHERE score >= 7",
            True,
        ),
        (
            "What was the average production cost?",
            "SELECT AVG(acidity + score) FROM data",
            True,
        ),
        (
            "What is the average price for scores of at least 7?",
            "SELECT AVG(price) FROM data WHERE score >= 7",
            False,
        ),
        (
            "What is the total cost?",
            "SELECT SUM(cost) FROM data",
            False,
        ),
        (
            "How many samples have a price above $10?",
            "SELECT COUNT(*) FROM data WHERE price > 10",
            False,
        ),
        (
            "What is the average acidity?",
            "SELECT AVG(acidity) FROM data",
            False,
        ),
        (
            "How many different individual people visited, counting each person once?",
            "SELECT SUM(visits) FROM data",
            True,
        ),
        (
            "How many unique customers visited?",
            "SELECT COUNT(customer_id) FROM data",
            True,
        ),
        (
            "How many unique customers visited?",
            "SELECT COUNT(DISTINCT customer_id) FROM data",
            False,
        ),
        (
            "How many unique customers visited?",
            "SELECT COUNT(*) FROM (SELECT customer_id FROM data GROUP BY customer_id)",
            False,
        ),
    ],
    ids=[
        "price-from-another-column",
        "cost-from-a-sum-of-other-columns",
        "price-column",
        "cost-column",
        "count-with-a-price-filter",
        "not-about-money",
        "people-from-a-sum-of-visits",
        "people-counted-as-rows",
        "people-counted-once",
        "people-grouped",
    ],
)
def test_a_measure_the_data_does_not_hold_is_named(
    tmp_path: Path, question: str, sql: str, found: bool
) -> None:
    dataset = _load(tmp_path, SAMPLES)

    assert ("measure_not_in_data" in _codes(dataset, question, sql)) is found


def test_a_column_that_carried_currency_marks_holds_money(tmp_path: Path) -> None:
    dataset = _load(tmp_path, AMOUNTS)
    sql = "SELECT AVG(amt) FROM data"

    assert "measure_not_in_data" not in _codes(
        dataset, "What is the average price?", sql
    )


RENTALS = (
    "day,yr,mnth,year,cnt\n"
    "2011-01-05,0,1,2011,10\n"
    "2011-02-05,0,2,2011,20\n"
    "2012-01-05,1,1,2012,30\n"
    "2012-02-05,1,2,2012,40\n"
)


def test_years_stored_as_codes_are_described(tmp_path: Path) -> None:
    context = QueryContextBuilder().build_from_dataset(_load(tmp_path, RENTALS))

    assert context.coded_years == (
        ObservedCodedYears("data", "yr", "day", ((0, 2011), (1, 2012))),
    )
    formatted = QueryContextFormatter().format(context)
    assert "YEARS STORED AS CODES" in formatted
    assert '"years": [[0, 2011], [1, 2012]]' in formatted


@pytest.mark.parametrize(
    "text",
    [
        "yr,cnt\n0,10\n1,20\n",
        "day,yr,cnt\n2011-01-05,0,10\n2011-02-05,0,20\n",
        "day,yr,cnt\n2011-01-05,0,10\n2012-01-05,0,20\n2013-01-05,1,30\n"
        "2013-02-05,1,40\n",
        "day,yr,cnt\n2011-01-05,0,10\n2011-02-05,1,20\n2012-01-05,1,30\n",
    ],
    ids=["no-date", "one-code", "code-spans-years", "year-spans-codes"],
)
def test_other_integer_columns_are_not_read_as_year_codes(
    tmp_path: Path, text: str
) -> None:
    context = QueryContextBuilder().build_from_dataset(_load(tmp_path, text))

    assert context.coded_years == ()


def test_no_codes_add_nothing_to_the_description() -> None:
    assert format_coded_years(QueryContext(relations=())) == ""


def test_the_website_hides_a_number_the_data_cannot_hold(tmp_path: Path) -> None:
    import json

    from fastapi.testclient import TestClient

    from verisight import VeriSight
    from verisight.execution.generative import GenerativeQueryPlanner
    from verisight.execution.generative_investigator import GenerativeInvestigator
    from verisight.execution.structured_synthesis import (
        StructuredInvestigationSynthesizer,
    )
    from verisight.web import create_app
    from verisight.web.config import WebSettings

    class Script:
        def __init__(self, items: list[str]) -> None:
            self.items = list(items)

        def generate(self, prompt: str) -> str:
            return self.items.pop(0)

    decide = [
        json.dumps({"action": "investigate", "reasoning": "r", "question": "Price"}),
        json.dumps({"action": "finish", "reasoning": "r", "question": None}),
    ]
    sql = "SELECT AVG(acidity) AS average_price FROM data"
    written = json.dumps(
        {
            "conclusion": "The average price is 7.1 euros.",
            "claims": [
                {
                    "operation": "value",
                    "expected": "7.1",
                    "left": {
                        "observation_index": 0,
                        "row_index": 0,
                        "column": "average_price",
                    },
                    "right": None,
                }
            ],
        }
    )

    def factory(settings: Settings) -> VeriSight:
        return VeriSight(
            settings=settings.model_copy(update={"gemini_cross_check_model": None}),
            planner=GenerativeQueryPlanner(Script([sql, sql])),
            investigator=GenerativeInvestigator(Script(decide)),
            synthesizer=StructuredInvestigationSynthesizer(Script([written] * 2)),
        )

    app = create_app(
        settings=Settings(gemini_api_key=None), web=WebSettings(), factory=factory
    )
    with TestClient(app) as client:
        upload = client.post(
            "/api/datasets",
            files=[("files", ("data.csv", b"acidity,score\n7.4,7\n6.8,5\n"))],
        )
        reply = client.post(
            f"/api/datasets/{upload.json()['dataset_id']}/ask",
            json={
                "question": "What is the average price in euros?",
                "consent": True,
                "api_key": "k",
            },
        ).json()

    assert reply["trust"]["level"] == "not_verified"
    assert reply["outcome"] == "unverified"
    assert "7.1" not in reply["answer"]
    assert reply["answer"].startswith("No number is shown.")
    assert reply["failure"] == {"kind": "measure_not_in_data"}
