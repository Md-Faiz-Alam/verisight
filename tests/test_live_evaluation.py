"""Offline tests for the opt-in live evaluation runner; no provider calls."""

from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts.live_evaluation import CASES, failure_report, main, run_case, score_result

from verisight import VeriSight
from verisight.config import Settings
from verisight.execution.claim_verification import (
    ClaimOperation,
    EvidenceReference,
    NumericalClaim,
)
from verisight.execution.exceptions import InvestigationError
from verisight.execution.gemini import GeminiGenerationError
from verisight.execution.investigation_result import (
    InvestigationResult,
    InvestigationStatus,
)
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation


@pytest.fixture
def result(tmp_path: Path) -> InvestigationResult:
    path = tmp_path / "data.csv"
    path.write_text("value\n10\n20\n", encoding="utf-8")
    analysis = VeriSight(settings=Settings(allow_llm_data_disclosure=False)).analyze(
        path
    )
    observation = QueryObservation(
        question="What is the total?",
        sql="SELECT SUM(value) AS total FROM data",
        result=QueryResult(columns=("total",), rows=((30,),)),
    )
    claim = NumericalClaim(
        ClaimOperation.VALUE, Decimal("30"), EvidenceReference(0, 0, "total")
    )
    return InvestigationResult(
        question="What is the total?",
        conclusion="The total is 30.",
        analysis=analysis,
        observations=(observation,),
        generated_claims=(claim,),
    )


@pytest.mark.parametrize(
    "answer,outcome", [("30", "correct_numeric"), ("31", "incorrect_numeric")]
)
def test_score_uses_independent_answer(
    result: InvestigationResult, answer: str, outcome: str
) -> None:
    assert score_result(result, answer)["outcome"] == outcome


def test_score_does_not_cherry_pick_claims(result: InvestigationResult) -> None:
    assert (
        score_result(
            replace(result, generated_claims=result.generated_claims * 2), "30"
        )["outcome"]
        == "ambiguous_claims"
    )
    assert (
        score_result(replace(result, generated_claims=()), "30")["outcome"]
        == "no_claims"
    )
    assert (
        score_result(replace(result, status=InvestigationStatus.INCOMPLETE), "30")[
            "outcome"
        ]
        == "incomplete"
    )


def test_score_rejects_contradicted_or_derived_answers(
    result: InvestigationResult,
) -> None:
    claim = result.generated_claims[0]
    wrong = replace(claim, expected=31)
    assert (
        score_result(replace(result, generated_claims=(wrong,)), "30")["outcome"]
        == "unverified_answer"
    )
    derived = NumericalClaim(ClaimOperation.DIFFERENCE, 0, claim.left, claim.left)
    assert (
        score_result(replace(result, generated_claims=(derived,)), "0")["outcome"]
        == "unsupported_answer_format"
    )


def test_failure_reports_hide_secrets_and_follow_provider_causes() -> None:
    error = InvestigationError("private-secret")
    assert failure_report(error) == {
        "outcome": "application_error",
        "code": "investigation_error",
    }
    error.__cause__ = GeminiGenerationError("private-secret")
    assert failure_report(error) == {"outcome": "provider_error"}
    error.__cause__ = error
    assert "private-secret" not in str(failure_report(error))


def test_run_case_cleans_files_and_bounds_steps(result: InvestigationResult) -> None:
    with patch("scripts.live_evaluation.VeriSight") as app:
        app.return_value.investigate.return_value = result
        report = run_case(CASES["finance"], Settings(allow_llm_data_disclosure=False))
    assert report["outcome"] == "incorrect_numeric"
    call = app.return_value.investigate.call_args
    assert call.kwargs == {"max_steps": 1}
    assert all(not path.exists() for path in call.args[0])


def test_run_case_classifies_failure() -> None:
    with patch(
        "scripts.live_evaluation.VeriSight", side_effect=GeminiGenerationError("secret")
    ):
        assert run_case(CASES["finance"], Settings()) == {"outcome": "provider_error"}


def test_main_requires_explicit_live_flag() -> None:
    with patch("sys.argv", ["live_evaluation"]), pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


def test_main_handles_missing_key(capsys: pytest.CaptureFixture[str]) -> None:
    with (
        patch("sys.argv", ["live_evaluation", "--live"]),
        patch(
            "scripts.live_evaluation.Settings",
            return_value=Settings(gemini_api_key=None),
        ),
    ):
        assert main() == 2
    assert "configuration_error" in capsys.readouterr().out


@pytest.mark.parametrize(
    "outcome,exit_code", [("correct_numeric", 0), ("provider_error", 1)]
)
@pytest.mark.parametrize("selected,count", [("all", 3), ("finance", 1)])
def test_main_reports_all_cases_without_secrets(
    outcome: str,
    exit_code: int,
    selected: str,
    count: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch("sys.argv", ["live_evaluation", "--live", "--case", selected]),
        patch(
            "scripts.live_evaluation.Settings",
            return_value=Settings(gemini_api_key="private-secret"),
        ),
        patch(
            "scripts.live_evaluation.run_case", return_value={"outcome": outcome}
        ) as run,
    ):
        assert main() == exit_code
    assert run.call_count == count
    output = capsys.readouterr().out
    assert "private-secret" not in output
    assert f'"case_count": {count}' in output
