"""The committed benchmark is reproducible and its answers check out two ways."""

import csv
import importlib.util
import sys
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd
import pytest

from verisight import VeriSight
from verisight.config import Settings

ROOT = Path(__file__).resolve().parents[1] / "evaluation" / "benchmark"
TEXT_FILES = (
    "questions.csv",
    "data/visits.json",
    "data/orders.csv",
    "data/customers.csv",
    "data/scores.tsv",
    "data/readings.jsonl",
)
NO_ANSWER = ("AMBIGUOUS", "UNANSWERABLE")


def _module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


benchmark = _module("make_benchmark", ROOT / "make_benchmark.py")
runner = _module(
    "run_baseline_eval_for_benchmark",
    ROOT.parent / "baseline" / "run_baseline_eval.py",
)


def _committed_ids() -> list[str]:
    with (ROOT / "questions.csv").open(encoding="utf-8", newline="") as handle:
        return [
            row["id"]
            for row in csv.DictReader(handle)
            if row["expected"] not in NO_ANSWER
        ]


@pytest.fixture(scope="module")
def rebuilt(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, dict[str, Any]]:
    root = tmp_path_factory.mktemp("benchmark")
    questions = benchmark.build(root)
    return root, {question.question_id: question for question in questions}


@pytest.mark.parametrize("name", TEXT_FILES)
def test_the_committed_files_are_what_the_generator_writes(
    rebuilt: tuple[Path, dict[str, Any]], name: str
) -> None:
    root, _ = rebuilt

    assert (root / name).read_bytes() == (ROOT / name).read_bytes()


def test_the_committed_workbook_holds_what_the_generator_writes(
    rebuilt: tuple[Path, dict[str, Any]],
) -> None:
    root, _ = rebuilt

    pd.testing.assert_frame_equal(
        pd.read_excel(root / "data" / "production.xlsx", sheet_name="runs"),
        pd.read_excel(ROOT / "data" / "production.xlsx", sheet_name="runs"),
    )


def test_the_runner_accepts_the_questions() -> None:
    questions = runner.load_questions(ROOT)
    labels = [question.label for question in questions]

    assert len(questions) == 30
    assert (labels.count("AMBIGUOUS"), labels.count("UNANSWERABLE")) == (5, 5)
    assert {question.question_id[0] for question in questions} == set("hrmec")


@pytest.mark.parametrize("question_id", _committed_ids())
def test_hand_written_sql_reaches_each_expected_answer(
    rebuilt: tuple[Path, dict[str, Any]], question_id: str
) -> None:
    question = rebuilt[1][question_id]
    app = VeriSight(
        settings=Settings(_env_file=None, allow_llm_data_disclosure=False)  # type: ignore[call-arg]
    )

    result = app.execute(
        [ROOT / "data" / name for name in question.files], question.control_sql
    )

    assert len(result.rows) == 1 and len(result.rows[0]) == 1
    actual = Decimal(str(result.rows[0][0]))
    # Expected answers carry six places; a tolerance of zero means exact.
    margin = max(question.tolerance, Decimal("0.0000005"))
    assert abs(actual - question.expected) <= margin


def test_only_answerable_questions_have_control_sql(
    rebuilt: tuple[Path, dict[str, Any]],
) -> None:
    for question in rebuilt[1].values():
        has_answer = isinstance(question.expected, Decimal)
        assert (question.control_sql is not None) is has_answer
