"""The comparison must score, resume and refuse exactly as it says."""

import importlib.util
import json
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from verisight import VeriSight
from verisight.config import Settings
from verisight.execution.gemini import GeminiGenerationError
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.generative_investigator import GenerativeInvestigator
from verisight.execution.structured_synthesis import StructuredInvestigationSynthesizer


def _load() -> ModuleType:
    path = Path(__file__).parent.parent / "evaluation/baseline/run_baseline_eval.py"
    spec = importlib.util.spec_from_file_location("run_baseline_eval", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_baseline_eval"] = module
    spec.loader.exec_module(module)
    return module


runner = _load()
HEADER = "id,files,type,question,expected,tolerance\n"
SETTINGS = Settings(gemini_api_key=None, allow_llm_data_disclosure=False)
SECRET = "a private question"


def _root(tmp_path: Path, rows: str) -> Path:
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "orders.csv").write_text(
        "region,amount\nEast,100\nEast,200\nWest,50\n", "utf-8"
    )
    (tmp_path / "questions.csv").write_text(HEADER + rows, "utf-8")
    return tmp_path


def _question(expected: str = "300", tolerance: str = "0", kind: str = "number") -> Any:
    label = expected if expected in runner.NO_ANSWER_LABELS else "number"
    value = None if label != "number" else Decimal(expected)
    return runner.Question(
        "q1", ("orders.csv",), kind, "How much?", value, label, Decimal(tolerance)
    )


def test_good_questions_load(tmp_path: Path) -> None:
    root = _root(
        tmp_path,
        'q1,orders.csv,number,Total?,"1,200.5",0.01\n'
        "q2,orders.csv;orders.csv,difference,Gap?,5,\n"
        "q3,orders.csv,number,Best?,ambiguous,\n"
        "q4,orders.csv,number,In 2030?,UNANSWERABLE,\n",
    )

    questions = runner.load_questions(root)

    assert questions[0].expected == Decimal("1200.5")
    assert questions[1].files == ("orders.csv", "orders.csv")
    assert questions[1].tolerance == 0
    assert [q.label for q in questions[2:]] == ["AMBIGUOUS", "UNANSWERABLE"]


@pytest.mark.parametrize(
    ("row", "message"),
    [
        (f",orders.csv,number,{SECRET},1,0\n", "required"),
        (f"q1,nope.csv,number,{SECRET},1,0\n", "not found"),
        (f"q1,orders.csv,chart,{SECRET},1,0\n", "type must"),
        (f"q1,orders.csv,number,{SECRET},many,0\n", "not a number"),
        (f"q1,orders.csv,number,{SECRET},NaN,0\n", "not a valid"),
        (f"q1,orders.csv,number,{SECRET},1,-1\n", "not a valid"),
        (
            f"q1,orders.csv,number,{SECRET},1,0\nq1,orders.csv,number,b,1,0\n",
            "repeated",
        ),
    ],
)
def test_bad_rows_are_refused_without_showing_the_question(
    tmp_path: Path, row: str, message: str
) -> None:
    with pytest.raises(SystemExit) as stopped:
        runner.load_questions(_root(tmp_path, row))

    assert message in str(stopped.value)
    assert SECRET not in str(stopped.value)


def test_missing_columns_are_named(tmp_path: Path) -> None:
    root = _root(tmp_path, "")
    (root / "questions.csv").write_text("id,files\n", "utf-8")

    with pytest.raises(SystemExit, match="type, question, expected, tolerance"):
        runner.load_questions(root)


@pytest.mark.parametrize(
    ("expected", "tolerance", "number", "visibility", "outcome"),
    [
        ("300", "0", "300", "prominent", "correct_prominent"),
        ("300", "0.5", "300.4", "warned", "correct_warned"),
        ("300", "0", "301", "prominent", "wrong_prominent"),
        ("300", "0", "301", "warned", "wrong_warned"),
        ("300", "0", None, "none", "missed"),
        ("AMBIGUOUS", "0", None, "none", "correct_refusal"),
        ("UNANSWERABLE", "0", "5", "prominent", "unsafe_prominent"),
        ("UNANSWERABLE", "0", "5", "warned", "unsafe_warned"),
    ],
)
def test_each_result_is_named(
    expected: str,
    tolerance: str,
    number: str | None,
    visibility: str,
    outcome: str,
) -> None:
    answer = runner.Answer(
        None if number is None else Decimal(number), visibility=visibility
    )

    assert runner.score(_question(expected, tolerance), answer) == outcome


def test_a_provider_error_counts_for_no_one() -> None:
    assert (
        runner.score(_question(), runner.Answer(provider_error=True))
        == "provider_error"
    )


@pytest.mark.parametrize(
    ("rows", "value"),
    [
        ([(1, 2, 3)], Decimal(3)),
        ([("East", 7.5)], Decimal("7.5")),
        ([(7, "East")], Decimal(7)),
        ([(1,), (2,)], None),
        ([], None),
        ([(None,)], None),
        ([(True,)], None),
        ([(float("nan"),)], None),
    ],
)
def test_only_one_row_gives_a_single_answer(
    rows: list[tuple[object, ...]], value: Decimal | None
) -> None:
    assert runner.final_cell(rows) == value


def _reply(**extra: Any) -> dict[str, Any]:
    return {
        "outcome": "verified",
        "status": "complete",
        "claims": [
            {
                "claim": {"operation": "value"},
                "verification": {"status": "supported", "actual": "300"},
            }
        ],
        "assessment": {"accepted": True},
        "trust": {"level": "verified", "checks": []},
        "model_calls": [{}, {}],
        "cross_check": {"status": "agreed", "identical_sql": False},
        "steps": [{"sql": "SELECT 1"}],
        **extra,
    }


def test_a_verified_website_answer_is_prominent() -> None:
    answer = runner.read_website_answer(200, _reply(), _question())

    assert (answer.number, answer.visibility) == (Decimal(300), "prominent")
    assert answer.calls == 2


def test_an_unverified_website_answer_is_only_warned() -> None:
    answer = runner.read_website_answer(200, _reply(outcome="unverified"), _question())

    assert answer.visibility == "warned"


@pytest.mark.parametrize(
    "extra",
    [
        {"status": "incomplete"},
        {"claims": []},
        {"outcome": "unverified", "assessment": {"accepted": False}},
        {"outcome": "unverified", "assessment": None},
        {
            "claims": [
                {
                    "claim": {"operation": "value"},
                    "verification": {"status": "unsupported", "actual": None},
                }
            ]
        },
        {"outcome": "clarify", "status": "needs_clarification", "claims": []},
    ],
    ids=["incomplete", "no-claim", "rejected", "no-assessment", "unsupported", "ask"],
)
def test_website_replies_with_no_accepted_number(extra: dict[str, Any]) -> None:
    answer = runner.read_website_answer(200, _reply(**extra), _question())

    assert (answer.number, answer.visibility, answer.provider_error) == (
        None,
        "none",
        False,
    )


@pytest.mark.parametrize(
    ("status", "body", "provider"),
    [
        (503, {"code": "busy"}, True),
        (429, {"code": "rate_limited"}, True),
        (422, {"code": "invalid_question"}, False),
        (200, {"failure": {"kind": "provider_unavailable"}}, True),
    ],
)
def test_website_failures_are_told_apart(
    status: int, body: dict[str, Any], provider: bool
) -> None:
    answer = runner.read_website_answer(status, body, _question())

    assert answer.provider_error is provider


def _asker(outcomes: list[runner.Answer]) -> Any:  # type: ignore[name-defined]
    pending = iter(outcomes)
    asked: list[str] = []

    def ask(question: Any) -> Any:
        asked.append(question.question_id)
        return next(pending)

    ask.asked = asked  # type: ignore[attr-defined]
    return ask


def _questions(count: int) -> list[Any]:
    return [
        runner.Question(
            f"q{n}", ("o.csv",), "number", "?", Decimal(1), "number", Decimal(0)
        )
        for n in range(count)
    ]


def test_a_run_stops_after_repeated_provider_errors(tmp_path: Path) -> None:
    results = tmp_path / "runs" / "plain.jsonl"
    failed = runner.Answer(provider_error=True)
    ask = _asker([failed, failed, failed])

    counts = runner.run_setup(_questions(5), ask, results)

    assert counts == {"provider_error": 3}
    assert ask.asked == ["q0", "q1", "q2"]


def test_a_later_run_only_asks_what_is_unanswered(tmp_path: Path) -> None:
    results = tmp_path / "plain.jsonl"
    good = runner.Answer(Decimal(1), "prominent")
    runner.run_setup(
        _questions(2), _asker([good, runner.Answer(provider_error=True)]), results
    )
    ask = _asker([good, good])

    runner.run_setup(_questions(3), ask, results)

    assert ask.asked == ["q1", "q2"]
    assert len(results.read_text("utf-8").splitlines()) == 4


def test_the_summary_reports_every_number_the_targets_need() -> None:
    questions = [
        runner.Question("a", ("o",), "number", "?", Decimal(1), "number", Decimal(0)),
        runner.Question("b", ("o",), "number", "?", Decimal(1), "number", Decimal(0)),
        runner.Question("c", ("o",), "number", "?", Decimal(1), "number", Decimal(0)),
        runner.Question("d", ("o",), "number", "?", Decimal(1), "number", Decimal(0)),
        runner.Question("e", ("o",), "number", "?", None, "UNANSWERABLE", Decimal(0)),
    ]
    records = [
        {"id": "a", "outcome": "correct_prominent", "calls": 5, "seconds": 2.0},
        {"id": "b", "outcome": "correct_warned", "calls": 5, "seconds": 4.0},
        {"id": "c", "outcome": "wrong_warned", "calls": 1, "seconds": 6.0},
        {"id": "d", "outcome": "provider_error", "calls": 0, "seconds": 0.0},
        {"id": "e", "outcome": "unsafe_prominent", "calls": 1, "seconds": 8.0},
    ]

    summary = runner.summarize(questions, records)

    assert summary["correct_delivered_share"] == round(2 / 3, 4)
    assert summary["correct_among_shown_share"] == 0.5
    assert summary["wrong_shown_prominently"] == 1
    assert summary["wrong_visible_anywhere"] == 2
    assert summary["false_warning_share"] == 0.5
    assert summary["model_calls"] == 12
    assert summary["median_seconds"] == 5.0


def test_the_second_query_is_measured_against_the_written_answers() -> None:
    questions = _questions(6)
    questions[5] = runner.Question(
        "q5", ("o",), "number", "?", None, "AMBIGUOUS", Decimal(0)
    )
    rows = [
        ("q0", "wrong_warned", "disagreed", False),
        ("q1", "correct_warned", "disagreed", False),
        ("q2", "correct_prominent", "agreed", False),
        ("q3", "wrong_prominent", "agreed", False),
        ("q4", "correct_warned", "agreed", True),
        ("q5", "unsafe_warned", "agreed", False),
    ]
    records: list[dict[str, Any]] = [
        {
            "id": name,
            "outcome": outcome,
            "number": "1",
            "details": {"second_query": status, "repeated_query": repeated},
        }
        for name, outcome, status, repeated in rows
    ] + [{"id": "q0", "outcome": "missed", "number": None, "details": {}}]

    assert runner.second_query_value(questions, records) == {
        "caught_a_wrong_answer": 1,
        "doubted_a_right_answer": 1,
        "confirmed_right": 1,
        "shared_the_mistake": 1,
        "added_no_evidence": 1,
    }


def test_a_changed_question_file_blocks_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path, "q1,orders.csv,number,Total?,350,0\n")
    monkeypatch.setattr(runner, "_git", lambda *args: "")
    runner.freeze(root)
    runner.check_frozen(root)

    (root / "questions.csv").write_text(HEADER + "q1,orders.csv,number,Total?,9,0\n")

    with pytest.raises(SystemExit, match="questions_sha256"):
        runner.check_frozen(root)


def test_uncommitted_code_cannot_be_frozen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path, "q1,orders.csv,number,Total?,350,0\n")
    monkeypatch.setattr(runner, "_git", lambda *args: " M src/x.py")

    with pytest.raises(SystemExit, match="Commit every tracked change"):
        runner.freeze(root)


class _Script:
    def __init__(self, items: list[Any]) -> None:
        self.items = list(items)

    def generate(self, prompt: str) -> str:
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return str(item)


def _engine(plan: list[Any], synthesis: str = "") -> VeriSight:
    decisions = [
        json.dumps({"action": "investigate", "reasoning": "r", "question": "Add up"}),
        json.dumps({"action": "finish", "reasoning": "r", "question": None}),
    ]
    return VeriSight(
        settings=SETTINGS,
        planner=GenerativeQueryPlanner(_Script(plan)),
        investigator=GenerativeInvestigator(_Script(decisions)),
        synthesizer=StructuredInvestigationSynthesizer(_Script([synthesis] * 4)),
    )


GOOD = json.dumps(
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
SQL = "SELECT SUM(amount) AS total FROM orders"


def test_plain_gemini_runs_one_query(tmp_path: Path) -> None:
    root = _root(tmp_path, "")

    answer = runner.answer_plain(_engine([SQL]), _question(), root / "data")

    assert (answer.number, answer.visibility) == (Decimal(350), "prominent")
    assert answer.details["sql"] == [SQL]


def test_plain_gemini_with_several_rows_gives_no_number(tmp_path: Path) -> None:
    root = _root(tmp_path, "")
    sql = "SELECT region, SUM(amount) FROM orders GROUP BY region"

    answer = runner.answer_plain(_engine([sql]), _question(), root / "data")

    assert (answer.number, answer.visibility) == (None, "none")


def test_plain_gemini_query_failure_is_a_missing_answer(tmp_path: Path) -> None:
    root = _root(tmp_path, "")

    answer = runner.answer_plain(
        _engine(["SELECT nope FROM orders"]), _question(), root / "data"
    )

    assert (answer.number, answer.provider_error) == (None, False)
    assert "error" in answer.details


def test_plain_gemini_provider_failure_is_recorded(tmp_path: Path) -> None:
    root = _root(tmp_path, "")

    answer = runner.answer_plain(
        _engine([GeminiGenerationError("no")]), _question(), root / "data"
    )

    assert answer.provider_error is True


def test_numbers_setup_accepts_a_matched_number(tmp_path: Path) -> None:
    root = _root(tmp_path, "")

    answer = runner.answer_numbers(_engine([SQL], GOOD), _question(), root / "data")

    assert (answer.number, answer.visibility) == (Decimal(350), "prominent")


def test_numbers_setup_rejects_the_wrong_claim_shape(tmp_path: Path) -> None:
    root = _root(tmp_path, "")

    answer = runner.answer_numbers(
        _engine([SQL], GOOD), _question(kind="difference"), root / "data"
    )

    assert answer.number is None


def test_numbers_setup_records_a_provider_failure(tmp_path: Path) -> None:
    root = _root(tmp_path, "")

    answer = runner.answer_numbers(
        _engine([GeminiGenerationError("no")], GOOD), _question(), root / "data"
    )

    assert answer.provider_error is True


@pytest.mark.parametrize(
    ("columns", "row", "kind", "value"),
    [
        (("difference", "a", "b"), (5, 9, 4), "difference", Decimal(5)),
        (("a", "b", "a_minus_b"), (9, 4, 5), "difference", Decimal(5)),
        (("a", "b"), (9, 4), "difference", Decimal(4)),
        (("difference", "a"), (5, 9), "number", Decimal(9)),
        (("difference", "a"), ("n/a", 9), "difference", Decimal(9)),
    ],
    ids=["named-first", "named-last", "no-name", "only-for-differences", "text-name"],
)
def test_a_difference_column_is_read_by_name(
    columns: tuple[str, ...], row: tuple[object, ...], kind: str, value: Decimal
) -> None:
    assert runner.final_cell([row], columns, kind) == value


def test_rescoring_keeps_the_original_and_writes_a_copy(tmp_path: Path) -> None:
    root = _root(
        tmp_path,
        "q1,orders.csv,difference,Gap?,250,0\nq2,orders.csv,number,Total?,350,0\n",
    )
    (root / "runs").mkdir()
    sql = "SELECT 300 - 50 AS difference, 300 AS a, 50 AS b"
    lines = [
        {
            "id": "q1",
            "outcome": "wrong_prominent",
            "number": "50",
            "details": {"sql": [sql]},
        },
        {"id": "q2", "outcome": "provider_error", "number": None, "details": {}},
    ]
    original = "".join(json.dumps(line) + "\n" for line in lines)
    (root / "runs" / "plain.jsonl").write_text(original, "utf-8")

    runner.rescore_plain(root)

    rescored = (root / "runs" / "plain-rescored.jsonl").read_text("utf-8").splitlines()
    assert json.loads(rescored[0])["outcome"] == "correct_prominent"
    assert json.loads(rescored[1])["outcome"] == "provider_error"
    assert (root / "runs" / "plain.jsonl").read_text("utf-8") == original
    assert runner._results_path(root, "plain").name == "plain-rescored.jsonl"
    assert runner._results_path(root, "full").name == "full.jsonl"


def test_a_rejected_answer_records_why() -> None:
    reply = _reply(
        status="incomplete",
        failure={
            "kind": "synthesis_error",
            "validation_reason": "unlinked_narrative_number",
        },
        assessment={"accepted": False, "violations": ["english_cardinal_words"]},
    )

    answer = runner.read_website_answer(200, reply, _question())

    assert answer.details["rejected_as"] == "unlinked_narrative_number"
    assert answer.details["violations"] == ["english_cardinal_words"]


def test_a_hidden_number_is_not_counted_as_shown() -> None:
    reply = _reply(outcome="unverified", trust={"level": "not_verified", "checks": []})

    answer = runner.read_website_answer(200, reply, _question())

    assert (answer.number, answer.visibility) == (None, "none")
