"""Offline tests for the opt-in live evaluation runner; no provider calls."""

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts.live_evaluation import (
    CASES,
    failure_report,
    main,
    run_case,
    score_result,
    summarize_number_audits,
)

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
@pytest.mark.parametrize(
    "selected,count",
    [("all", 5), ("finance", 1), ("healthcare", 1), ("logistics", 1)],
)
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
    report = json.loads(output)
    assert report["case_count"] == count
    expected_names = set(CASES) if selected == "all" else {selected}
    assert set(report["results"]) == expected_names


@pytest.mark.parametrize(
    ("conclusion", "detected", "unlinked"),
    [
        ("The total is 30.", 1, 0),
        ("The total is 9999, repeated as 9999, rather than 30.", 3, 2),
        ("No numerical conclusion is available.", 0, 0),
    ],
)
def test_score_reports_token_occurrences_without_certifying_narrative(
    result: InvestigationResult, conclusion: str, detected: int, unlinked: int
) -> None:
    report = score_result(replace(result, conclusion=conclusion), "30")

    assert report["outcome"] == "correct_numeric"
    assert report["narrative_number_count"] == detected
    assert report["unlinked_number_count"] == unlinked
    assert report["narrative_number_audit_scope"] == "ascii_numeric_tokens_only"
    assert report["narrative_verified"] is False
    assert "conclusion" not in report
    assert "9999" not in json.dumps(report)


def test_no_claims_and_incomplete_results_still_have_number_audits(
    result: InvestigationResult,
) -> None:
    no_claims = replace(result, generated_claims=())
    for item, outcome in (
        (no_claims, "no_claims"),
        (replace(no_claims, status=InvestigationStatus.INCOMPLETE), "incomplete"),
    ):
        report = score_result(item, "30")
        assert report["outcome"] == outcome
        assert report["narrative_number_count"] == 1
        assert report["unlinked_number_count"] == 1


def test_number_audit_summary_separates_missing_audits_from_zero_tokens(
    result: InvestigationResult,
) -> None:
    reports = {
        "linked": score_result(result, "30"),
        "unlinked": score_result(
            replace(result, conclusion="9999 and 9999; the claim says 30."), "30"
        ),
        "zero_tokens": score_result(
            replace(result, conclusion="No numerical finding."), "30"
        ),
        "provider_failure": failure_report(GeminiGenerationError("private-secret")),
        "application_failure": failure_report(InvestigationError("private-secret")),
    }

    assert summarize_number_audits(reports) == {
        "audited_case_count": 3,
        "unaudited_case_count": 2,
        "detected_token_count": 4,
        "unlinked_token_count": 2,
        "cases_with_unlinked_tokens": 1,
    }
    assert summarize_number_audits({}) == {
        "audited_case_count": 0,
        "unaudited_case_count": 0,
        "detected_token_count": 0,
        "unlinked_token_count": 0,
        "cases_with_unlinked_tokens": 0,
    }


@pytest.mark.parametrize(
    ("detected", "unlinked"),
    [(None, 0), (1, None), (True, 0), (1, False), (-1, 0), (1, -1), (1, 2)],
)
def test_number_audit_summary_rejects_invalid_counts(
    detected: object, unlinked: object
) -> None:
    summary = summarize_number_audits(
        {
            "case": {
                "narrative_number_count": detected,
                "unlinked_number_count": unlinked,
            }
        }
    )

    assert summary["audited_case_count"] == 0
    assert summary["unaudited_case_count"] == 1
    assert summary["detected_token_count"] == 0
    assert summary["unlinked_token_count"] == 0


def test_main_includes_audit_summary_without_changing_numeric_exit_status(
    result: InvestigationResult, capsys: pytest.CaptureFixture[str]
) -> None:
    reports = [
        score_result(replace(result, conclusion="The total is 9999."), "30"),
        score_result(result, "30"),
        score_result(replace(result, conclusion="No numerical finding."), "30"),
        score_result(replace(result, conclusion="No numerical finding."), "30"),
        score_result(replace(result, conclusion="No numerical finding."), "30"),
    ]
    with (
        patch("sys.argv", ["live_evaluation", "--live", "--case", "all"]),
        patch(
            "scripts.live_evaluation.Settings",
            return_value=Settings(gemini_api_key="private-secret"),
        ),
        patch("scripts.live_evaluation.run_case", side_effect=reports),
    ):
        assert main() == 0

    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["outcome_counts"] == {"correct_numeric": 5}
    assert report["number_audit_summary"] == {
        "audited_case_count": 5,
        "unaudited_case_count": 0,
        "detected_token_count": 2,
        "unlinked_token_count": 1,
        "cases_with_unlinked_tokens": 1,
    }
    assert "9999" not in output
    assert "private-secret" not in output


@pytest.mark.parametrize(
    ("case_name", "sql", "expected"),
    [
        pytest.param(
            "finance",
            "SELECT SUM(cents) AS metric FROM ledger WHERE state = 'posted'",
            "10050",
            id="finance-posted-only",
        ),
        pytest.param(
            "retail",
            "SELECT SUM(lines.quantity * prices.unit_price) AS metric "
            "FROM lines JOIN prices ON lines.sku = prices.sku",
            "90",
            id="retail-joined-prices",
        ),
        pytest.param(
            "manufacturing",
            "SELECT 100.0 * SUM(defective) / COUNT(defective) AS metric "
            "FROM inspections",
            "25",
            id="manufacturing-known-outcomes",
        ),
        pytest.param(
            "healthcare",
            "SELECT AVG(minutes) AS metric FROM visits WHERE state = 'completed'",
            "20",
            id="healthcare-recorded-completed-waits",
        ),
        pytest.param(
            "logistics",
            "SELECT 100.0 * SUM(late) / COUNT(late) AS metric "
            "FROM deliveries WHERE state = 'delivered'",
            "50",
            id="logistics-known-delivered-outcomes",
        ),
    ],
)
def test_live_fixtures_match_independent_known_answers(
    tmp_path: Path, case_name: str, sql: str, expected: str
) -> None:
    """Exercise real ingestion and SQL with no model or provider dependency."""
    case = CASES[case_name]
    paths = []
    for filename, content in case.files:
        path = tmp_path / filename
        path.write_text(content, encoding="utf-8")
        paths.append(path)

    app = VeriSight(settings=Settings(allow_llm_data_disclosure=False))
    query_result = app.execute(paths, sql)

    assert case.answer == expected
    assert query_result.columns == ("metric",)
    assert query_result.row_count == 1
    assert Decimal(str(query_result.rows[0][0])) == Decimal(expected)
