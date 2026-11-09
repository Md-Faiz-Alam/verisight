"""The website and the command line must reach the same trust decision."""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from verisight import VeriSight
from verisight.cli import main
from verisight.config import Settings
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.generative_investigator import GenerativeInvestigator
from verisight.execution.structured_synthesis import StructuredInvestigationSynthesizer
from verisight.web import create_app
from verisight.web.config import WebSettings

CSV = "region,amount\nEast,100\nEast,200\nWest,50\n"
QUESTION = "How much came in altogether?"
FIRST = "SELECT SUM(amount) AS total FROM orders"
ANOTHER_ROUTE = (
    "SELECT SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) "
    "AS cross_check_answer FROM orders"
)
OTHER_NUMBER = "SELECT SUM(amount) AS cross_check_answer FROM orders WHERE amount > 100"
SYNTHESIS = json.dumps(
    {
        "conclusion": "The total is 350.",
        "claims": [
            {
                "operation": "value",
                "expected": "350",
                "left": {"observation_index": 0, "row_index": 0, "column": "total"},
                "right": None,
            }
        ],
    }
)


class _Script:
    def __init__(self, items: list[str]) -> None:
        self.items = list(items)

    def generate(self, prompt: str) -> str:
        return self.items.pop(0)


def _decision(question: str | None) -> str:
    action = "finish" if question is None else "investigate"
    return json.dumps({"action": action, "reasoning": "r", "question": question})


def _engine(settings: Settings, second: str, csv_options: object = None) -> VeriSight:
    return VeriSight(
        settings=settings.model_copy(update={"gemini_cross_check_model": None}),
        csv_options=csv_options,  # type: ignore[arg-type]
        planner=GenerativeQueryPlanner(_Script([FIRST, second])),
        investigator=GenerativeInvestigator(
            _Script([_decision("Add up the amounts"), _decision(None)])
        ),
        synthesizer=StructuredInvestigationSynthesizer(_Script([SYNTHESIS] * 4)),
    )


def _orders(tmp_path: Path, text: str = CSV) -> Path:
    path = tmp_path / "orders.csv"
    path.write_text(text, encoding="utf-8")
    return path


def _command(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    arguments: list[str],
    second: str = FIRST,
) -> tuple[int, dict[str, object]]:
    monkeypatch.setenv("VERISIGHT_GEMINI_API_KEY", "offline-key")
    monkeypatch.setattr(
        "verisight.cli.VeriSight",
        lambda settings, csv_options: _engine(settings, second, csv_options),
    )
    code = main(arguments)
    return code, json.loads(capsys.readouterr().out)


def _website_trust(tmp_path: Path, second: str) -> dict[str, object]:
    app = create_app(
        settings=Settings(gemini_api_key=None),
        web=WebSettings(),
        factory=lambda settings: _engine(settings, second),
    )
    with TestClient(app) as client:
        upload = client.post(
            "/api/datasets",
            files=[("files", ("orders.csv", CSV.encode("utf-8")))],
        )
        answer = client.post(
            f"/api/datasets/{upload.json()['dataset_id']}/ask",
            json={"question": QUESTION, "consent": True, "api_key": "k"},
        )
    trust: dict[str, object] = answer.json()["trust"]
    return trust


@pytest.mark.parametrize(
    ("second", "level", "exit_code"),
    [
        (ANOTHER_ROUTE, "verified", 0),
        (FIRST, "number_matched", 0),
        (OTHER_NUMBER, "needs_review", 1),
    ],
    ids=["another-route", "repeated-query", "different-number"],
)
def test_website_and_command_line_agree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    second: str,
    level: str,
    exit_code: int,
) -> None:
    arguments = [
        "investigate",
        str(_orders(tmp_path)),
        "--question",
        QUESTION,
        "--require-claim",
        "value",
        "--allow-llm-data-disclosure",
        "--cross-check",
    ]

    code, report = _command(monkeypatch, capsys, arguments, second)
    website = _website_trust(tmp_path, second)

    assert report["trust"] == website
    assert website["level"] == level
    assert code == exit_code


def test_a_skipped_check_is_never_silent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = [
        "investigate",
        str(_orders(tmp_path)),
        "--question",
        QUESTION,
        "--allow-llm-data-disclosure",
    ]

    code, report = _command(monkeypatch, capsys, arguments)

    assert code == 0
    assert report["trust"] == {
        "level": "not_run",
        "reason": "The SQL audit and second query run only with --cross-check.",
    }


def test_an_exact_question_needs_no_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = [
        "investigate",
        str(_orders(tmp_path)),
        "--question",
        "What is the total amount for East?",
        "--allow-llm-data-disclosure",
        "--cross-check",
    ]

    code, report = _command(monkeypatch, capsys, arguments)

    assert code == 0
    assert report["kind"] == "direct_answer"
    assert report["result"]["rows"] == [[300]]  # type: ignore[index]
    assert report["trust"]["level"] == "computed"  # type: ignore[index]


def test_a_value_in_two_columns_asks_which_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = _orders(tmp_path, "a,b,n\nx,x,1\ny,y,2\n")

    code, report = _command(
        monkeypatch,
        capsys,
        [
            "investigate",
            str(source),
            "--question",
            "What is the average n in x?",
            "--allow-llm-data-disclosure",
            "--cross-check",
        ],
    )

    assert code == 1
    assert report["kind"] == "clarification_needed"
    assert len(report["options"]) == 2  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "extra",
    [
        ["--require-claim", "difference"],
        ["--metric-description", "Total", "orders", "dollars"],
        ["--population", "POPULATION"],
    ],
    ids=["other-contract", "metric-wording", "population"],
)
def test_requests_the_fixed_rules_cannot_honour_go_to_the_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra: list[str],
) -> None:
    population = tmp_path / "population.json"
    population.write_text(
        '[{"relation": "orders", "column": "region", "values": ["East"]}]',
        encoding="utf-8",
    )
    arguments = [
        "investigate",
        str(_orders(tmp_path)),
        "--question",
        "What is the total amount for East?",
        "--allow-llm-data-disclosure",
        "--cross-check",
        *[str(population) if item == "POPULATION" else item for item in extra],
    ]

    _, report = _command(monkeypatch, capsys, arguments)

    assert report["kind"] == "investigation"


def test_the_preview_records_the_choice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    arguments = [
        "investigate",
        str(_orders(tmp_path)),
        "--question",
        QUESTION,
        "--preview",
        "--cross-check",
    ]

    code, report = _command(monkeypatch, capsys, arguments)

    assert code == 0
    assert report["request"]["cross_check"] is True  # type: ignore[index]
