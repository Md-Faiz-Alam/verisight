"""Answers built on an assumption the question never made."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from verisight import VeriSight
from verisight.config import Settings
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.generative_investigator import GenerativeInvestigator
from verisight.execution.sql_audit import audit_sql
from verisight.execution.structured_synthesis import StructuredInvestigationSynthesizer
from verisight.ingestion.models import LoadedDataset
from verisight.ingestion.service import DatasetLoader
from verisight.web import create_app
from verisight.web.config import WebSettings

SETTINGS = Settings(allow_llm_data_disclosure=False, gemini_api_key=None)
ROWS = (
    "class,area,body_style,horsepower,city_mpg,fuel,orderDate,shippedDate,cnt,freight,country\n"
    "Besni,90000,sedan,110,24,gas,2024-01-01,2024-01-03,5,120,Germany\n"
    "Kecimen,60000,hatchback,90,31,diesel,2024-01-02,2024-01-09,7,40,France\n"
    "Besni,95000,sedan,150,20,gas,2024-01-05,2024-01-06,3,80,Germany\n"
)


@pytest.fixture(scope="module")
def data(tmp_path_factory: pytest.TempPathFactory) -> LoadedDataset:
    path: Path = tmp_path_factory.mktemp("assume") / "data.csv"
    path.write_text(ROWS, encoding="utf-8")
    return DatasetLoader(SETTINGS).load([path])


def _codes(data: LoadedDataset, question: str, sql: str) -> set[str]:
    audit = audit_sql(question=question, sql=sql, result=None, dataset=data)
    return {finding.code for finding in audit.findings}


@pytest.mark.parametrize(
    ("question", "sql", "code", "found"),
    [
        (
            "How many raisins are large?",
            "SELECT COUNT(*) FROM data WHERE class = 'Besni'",
            "assumed_definition",
            True,
        ),
        (
            "How many cars are economical?",
            "SELECT COUNT(*) FROM data WHERE city_mpg > 25",
            "assumed_definition",
            True,
        ),
        (
            "How many large orders had freight over 100?",
            "SELECT COUNT(*) FROM data WHERE freight > 100",
            "assumed_definition",
            False,
        ),
        (
            "How many large orders went to Germany?",
            "SELECT COUNT(*) FROM data WHERE country = 'Germany' AND freight > 0",
            "assumed_definition",
            False,
        ),
        (
            "How many orders went to Germany?",
            "SELECT COUNT(*) FROM data WHERE freight > 50",
            "assumed_definition",
            False,
        ),
        (
            "How much higher is the average horsepower for sedans?",
            "SELECT AVG(horsepower) FROM data WHERE body_style = 'sedan'",
            "missing_comparison",
            True,
        ),
        (
            "How much higher is the average horsepower for sedans than hatchbacks?",
            "SELECT AVG(horsepower) FROM data",
            "missing_comparison",
            False,
        ),
        (
            "What is the average carbon dioxide emission in grams per kilometre?",
            "SELECT AVG(2640.0 / city_mpg) FROM data",
            "invented_constant",
            True,
        ),
        (
            "What percentage of cars use gas?",
            "SELECT 100.0 * COUNT(*) FILTER (WHERE fuel = 'gas') / COUNT(*) FROM data",
            "invented_constant",
            False,
        ),
        (
            "Convert the average city mpg to km per litre using 0.425.",
            "SELECT AVG(city_mpg * 0.425) FROM data",
            "invented_constant",
            False,
        ),
        (
            "What is the average sugar content of the Besni raisins?",
            "SELECT AVG(area) AS average_sugar_content FROM data WHERE class = 'Besni'",
            "measure_not_named",
            True,
        ),
        (
            "What is the average area of the Besni raisins?",
            "SELECT AVG(area) FROM data WHERE class = 'Besni'",
            "measure_not_named",
            False,
        ),
        (
            "What was the highest daily total of rentals?",
            "SELECT MAX(cnt) FROM data",
            "measure_not_named",
            False,
        ),
        (
            "On average, how many days passed between ordering and shipping?",
            "SELECT AVG(shippedDate - orderDate) FROM data",
            "measure_not_named",
            False,
        ),
        (
            "How many raisins are there?",
            "SELECT COUNT(*) FROM data",
            "measure_not_named",
            False,
        ),
    ],
    ids=[
        "large-as-a-category",
        "economical-as-a-threshold",
        "threshold-given",
        "given-value-and-zero",
        "no-vague-word",
        "higher-than-nothing",
        "higher-than-something",
        "made-up-conversion",
        "percentage",
        "conversion-given",
        "area-called-sugar",
        "area-asked",
        "abbreviated-column",
        "camel-case-column",
        "no-measure-asked",
    ],
)
def test_an_assumption_the_question_never_made_is_named(
    data: LoadedDataset, question: str, sql: str, code: str, found: bool
) -> None:
    assert (code in _codes(data, question, sql)) is found


class _Script:
    def __init__(self, items: list[str]) -> None:
        self.items = list(items)

    def generate(self, prompt: str) -> str:
        return self.items.pop(0)


def test_the_website_shows_no_number_for_an_undefined_word(tmp_path: Path) -> None:
    decide = [
        json.dumps({"action": "investigate", "reasoning": "r", "question": "Count"}),
        json.dumps({"action": "finish", "reasoning": "r", "question": None}),
    ]
    sql = "SELECT COUNT(*) AS large_count FROM data WHERE class = 'Besni'"
    written = json.dumps(
        {
            "conclusion": "There are 2 large raisins.",
            "claims": [
                {
                    "operation": "value",
                    "expected": "2",
                    "left": {
                        "observation_index": 0,
                        "row_index": 0,
                        "column": "large_count",
                    },
                    "right": None,
                }
            ],
        }
    )

    def factory(settings: Settings) -> VeriSight:
        return VeriSight(
            settings=settings.model_copy(update={"gemini_cross_check_model": None}),
            planner=GenerativeQueryPlanner(_Script([sql, sql])),
            investigator=GenerativeInvestigator(_Script(decide)),
            synthesizer=StructuredInvestigationSynthesizer(_Script([written] * 2)),
        )

    app = create_app(
        settings=Settings(gemini_api_key=None), web=WebSettings(), factory=factory
    )
    with TestClient(app) as client:
        upload = client.post(
            "/api/datasets", files=[("files", ("data.csv", ROWS.encode("utf-8")))]
        )
        reply = client.post(
            f"/api/datasets/{upload.json()['dataset_id']}/ask",
            json={
                "question": "How many raisins are large?",
                "consent": True,
                "api_key": "k",
            },
        ).json()

    assert reply["trust"]["level"] == "not_verified"
    assert reply["failure"] == {"kind": "undefined_in_question"}
    assert reply["answer"].startswith("No number is shown. The question does not say")
    assert "There are 2" not in reply["answer"]


TRACKS = (
    "name,milliseconds,absence_hours,price\n"
    "A,200000,2,0.99\nB,400000,9,0.99\nC,310000,4,1.99\n"
)


@pytest.fixture(scope="module")
def tracks(tmp_path_factory: pytest.TempPathFactory) -> LoadedDataset:
    path: Path = tmp_path_factory.mktemp("units") / "tracks.csv"
    path.write_text(TRACKS, encoding="utf-8")
    return DatasetLoader(SETTINGS).load([path])


@pytest.mark.parametrize(
    ("question", "sql", "code", "found"),
    [
        # A column named for a unit measures that unit's quantity.
        (
            "What is the average track duration in seconds?",
            "SELECT AVG(milliseconds) / 1000.0 FROM tracks",
            "measure_not_named",
            False,
        ),
        (
            "What is the average track length in minutes?",
            "SELECT AVG(milliseconds) / 60000.0 FROM tracks",
            "measure_not_named",
            False,
        ),
        # A factor between time units, with a time unit named.
        (
            "How long are all tracks in minutes?",
            "SELECT SUM(milliseconds) / 60000.0 FROM tracks",
            "invented_constant",
            False,
        ),
        # "Five" in words counts as a number the question gave.
        (
            "How many tracks are longer than five minutes?",
            "SELECT SUM(CASE WHEN milliseconds > 5 * 60 * 1000 THEN 1 ELSE 0 END) "
            "FROM tracks",
            "invented_constant",
            False,
        ),
        # A factor that belongs to no named quantity is still invented.
        (
            "How many tracks exceeded our absence limit?",
            "SELECT COUNT(*) FROM tracks WHERE absence_hours > "
            "(SELECT AVG(absence_hours) * 10 FROM tracks)",
            "invented_constant",
            True,
        ),
        # Without any unit named, a conversion factor is not assumed.
        (
            "What is the average price per track?",
            "SELECT AVG(price) * 60 FROM tracks",
            "invented_constant",
            True,
        ),
        # A unit column does not answer a question about another quantity.
        (
            "What is the average weight of the tracks?",
            "SELECT AVG(milliseconds) FROM tracks",
            "measure_not_named",
            True,
        ),
    ],
    ids=[
        "ms-for-seconds",
        "ms-for-minutes",
        "minutes-factor",
        "number-word",
        "invented-rate",
        "no-unit-named",
        "other-quantity",
    ],
)
def test_unit_conversions_are_not_invented(
    tracks: LoadedDataset, question: str, sql: str, code: str, found: bool
) -> None:
    audit = audit_sql(question=question, sql=sql, result=None, dataset=tracks)

    assert (code in {finding.code for finding in audit.findings}) is found
