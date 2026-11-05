"""Evaluation scorers count an answer as correct only if users were shown it."""

import json
import runpy
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1] / "evaluation"


def _runner(name: str) -> dict[str, Any]:
    return runpy.run_path(str(ROOT / name), run_name="scoring_test")


def _claim(operation: str, actual: str, *, right: bool = False) -> dict[str, Any]:
    cell = {"observation_index": 0, "row_index": 0, "column": "v"}
    return {
        "claim": {
            "operation": operation,
            "expected": actual,
            "left": cell,
            "right": cell if right else None,
        },
        "verification": {"status": "supported", "actual": actual},
    }


def _response(
    claims: list[dict[str, Any]], *, verified: bool, accepted: bool
) -> dict[str, Any]:
    return {
        "outcome": "verified" if verified else "unverified",
        "status": "complete",
        "claims": claims,
        "steps": [{"sql": "SELECT 675 AS v"}],
        "assessment": {"accepted": accepted},
        "review_required": False,
        "failure": None,
        "recovery": None,
    }


@pytest.fixture(scope="module")
def heldout() -> dict[str, Any]:
    return _runner("heldout/run_heldout_eval.py")


def _case(module: dict[str, Any], case_id: str) -> Any:
    return next(case for case in module["CASES"] if case.case_id == case_id)


def test_rejected_answer_with_correct_cell_is_not_counted_correct(
    heldout: dict[str, Any],
) -> None:
    # The reviewer's reproduction: a correct value claim plus an extra
    # difference claim, so the website rejected the answer.
    case = _case(heldout, "movies_comedy_count")
    body = _response(
        [_claim("value", "675"), _claim("difference", "0", right=True)],
        verified=False,
        accepted=False,
    )

    scored = heldout["classify"](200, body, case)

    assert scored["outcome"] == "not_accepted"
    assert scored["numeric_match"] is True
    assert scored["accepted"] is False


@pytest.mark.parametrize(
    ("actual", "outcome", "match"),
    [("675", "correct", True), ("848", "incorrect", False)],
)
def test_accepted_answers_are_scored_on_the_cell(
    heldout: dict[str, Any], actual: str, outcome: str, match: bool
) -> None:
    case = _case(heldout, "movies_comedy_count")
    body = _response([_claim("value", actual)], verified=True, accepted=True)

    scored = heldout["classify"](200, body, case)

    assert (scored["outcome"], scored["numeric_match"]) == (outcome, match)


def test_verified_label_alone_is_not_acceptance(heldout: dict[str, Any]) -> None:
    case = _case(heldout, "movies_comedy_count")
    body = _response([_claim("value", "675")], verified=True, accepted=False)

    assert heldout["classify"](200, body, case)["outcome"] == "not_accepted"


@pytest.mark.parametrize(
    "runner",
    [
        "v2/run_v2_eval.py",
        "bank/run_bank_eval.py",
        "multidomain/run_multidomain_eval.py",
    ],
)
@pytest.mark.parametrize(
    ("accepted", "outcome"), [(True, "correct"), (False, "not_accepted")]
)
def test_cli_scorers_require_contract_acceptance(
    runner: str, accepted: bool, outcome: str
) -> None:
    module = _runner(runner)
    case = module["CASES"][0]
    claim = _claim(case.operation, "1", right=case.operation == "difference")
    report = {
        "workflow_status": "complete",
        "claim_output_assessment": {"accepted": accepted},
        "advisory_reviews": {"review_required": False},
        "investigation": {"observations": [], "verified_claims": [claim]},
    }

    scored = module["classify"](report, case, Decimal("1"))

    assert scored["outcome"] == outcome
    assert scored["numeric_match"] is True


def test_rescore_reads_a_saved_run_and_reports_changes(tmp_path: Path) -> None:
    rescore = _runner("rescore.py")["rescore"]
    run = tmp_path / "run"
    attempt = run / "attempts" / "round-01-movies_comedy_count"
    attempt.mkdir(parents=True)
    body = _response(
        [_claim("value", "675"), _claim("difference", "0", right=True)],
        verified=False,
        accepted=False,
    )
    (attempt / "response.json").write_text(json.dumps(body), "utf-8")
    (run / "results.jsonl").write_text(
        json.dumps(
            {
                "round": 1,
                "case_id": "movies_comedy_count",
                "expected": "675",
                "outcome": "correct",
            }
        )
        + "\n",
        "utf-8",
    )

    lines, summary = rescore(ROOT / "heldout" / "run_heldout_eval.py", run)

    assert lines[0]["new_outcome"] == "not_accepted"
    assert summary["old_totals"] == {"correct": 1}
    assert summary["new_totals"] == {"not_accepted": 1}
    assert len(summary["changed"]) == 1
    assert (run / "results.jsonl").read_text("utf-8").count("\n") == 1
