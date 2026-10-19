"""Offline tests for the opt-in live evaluation runner; no provider calls."""

import json
import subprocess
from collections.abc import Iterator
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from scripts.live_evaluation import (
    CASES,
    failure_report,
    main,
    repository_metadata,
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


@pytest.fixture(autouse=True)
def isolate_repository_metadata() -> Iterator[None]:
    with patch(
        "scripts.live_evaluation.repository_metadata",
        return_value={
            "commit": "a" * 40,
            "tracked_changes": False,
            "status_scope": "tracked_files_only",
        },
    ):
        yield


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


@pytest.mark.parametrize("status,dirty", [("", False), (" M private-file.py", True)])
def test_repository_metadata_reports_revision_without_file_names(
    status: str, dirty: bool
) -> None:
    with patch(
        "scripts.live_evaluation.subprocess.run",
        side_effect=[
            subprocess.CompletedProcess([], 0, stdout="b" * 40 + "\n"),
            subprocess.CompletedProcess([], 0, stdout=status),
        ],
    ) as run:
        metadata = repository_metadata()

    assert metadata == {
        "commit": "b" * 40,
        "tracked_changes": dirty,
        "status_scope": "tracked_files_only",
    }
    assert "private-file" not in json.dumps(metadata)
    assert run.call_count == 2
    assert run.call_args.args[0] == [
        "git",
        "status",
        "--porcelain",
        "--untracked-files=no",
    ]
    assert run.call_args.kwargs["timeout"] == 2


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("private-path"),
        subprocess.CalledProcessError(128, "git", stderr="private-error"),
        subprocess.TimeoutExpired("git", 2),
    ],
    ids=["git-missing", "not-a-repository", "git-timeout"],
)
def test_repository_metadata_is_unknown_when_git_is_unavailable(
    error: Exception,
) -> None:
    with patch("scripts.live_evaluation.subprocess.run", side_effect=error):
        assert repository_metadata() == {
            "commit": None,
            "tracked_changes": None,
            "status_scope": "tracked_files_only",
        }


def test_saved_report_retains_failures_settings_revision_and_timings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "evaluation.json"
    settings = Settings(
        gemini_api_key="private-secret",
        allow_llm_data_disclosure=True,
        gemini_request_timeout_seconds=17,
        gemini_max_retries=1,
        max_query_result_rows=12,
    )
    with (
        patch(
            "sys.argv",
            ["live_evaluation", "--live", "--case", "all", "--output", str(path)],
        ),
        patch("scripts.live_evaluation.Settings", return_value=settings),
        patch(
            "scripts.live_evaluation.run_case",
            side_effect=[
                {"outcome": "correct_numeric"},
                {"outcome": "provider_error"},
                {"outcome": "incorrect_numeric"},
                {"outcome": "incomplete"},
                {"outcome": "no_claims"},
            ],
        ),
        patch("scripts.live_evaluation.perf_counter", side_effect=range(12)),
        patch("scripts.live_evaluation.platform.python_version", return_value="3.11.9"),
    ):
        assert main() == 1

    output = capsys.readouterr()
    assert output.err == ""
    serialized = path.read_text(encoding="utf-8")
    assert serialized == output.out
    assert "private-secret" not in serialized
    report = json.loads(serialized)
    assert report["schema_version"] == 2
    assert report["revision"]["commit"] == "a" * 40
    assert report["revision"]["tracked_changes"] is False
    assert report["python_version"] == "3.11.9"
    assert report["elapsed_seconds"] == 11
    assert report["provider_retries"] == 1
    assert report["run_settings"]["request_timeout_seconds"] == 17
    assert report["run_settings"]["max_query_result_rows"] == 12
    assert "gemini_api_key" not in report["run_settings"]
    assert report["outcome_counts"] == {
        "correct_numeric": 1,
        "provider_error": 1,
        "incorrect_numeric": 1,
        "incomplete": 1,
        "no_claims": 1,
    }
    assert set(report["results"]) == set(CASES)
    assert all(item["elapsed_seconds"] == 1 for item in report["results"].values())


@pytest.mark.parametrize(
    "existing", [False, True], ids=["missing-parent", "existing-file"]
)
def test_report_save_failure_preserves_stdout_and_existing_files(
    tmp_path: Path, existing: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    path = (
        tmp_path / "existing.json" if existing else tmp_path / "missing" / "report.json"
    )
    if existing:
        path.write_text("original", encoding="utf-8")
    with (
        patch("sys.argv", ["live_evaluation", "--live", "--output", str(path)]),
        patch(
            "scripts.live_evaluation.Settings",
            return_value=Settings(gemini_api_key="private-secret"),
        ),
        patch(
            "scripts.live_evaluation.run_case",
            return_value={"outcome": "provider_error"},
        ),
    ):
        assert main() == 2

    output = capsys.readouterr()
    assert json.loads(output.out)["results"]["finance"]["outcome"] == "provider_error"
    assert output.err == "Could not save evaluation report to a new file.\n"
    assert str(path) not in output.err
    if existing:
        assert path.read_text(encoding="utf-8") == "original"
    else:
        assert not path.exists()


@pytest.mark.parametrize(
    ("arguments", "timeout", "retries"),
    [
        pytest.param([], 20.0, 0, id="defaults"),
        pytest.param(
            ["--request-timeout-seconds", "60", "--provider-retries", "1"],
            60.0,
            1,
            id="explicit-values",
        ),
        pytest.param(
            ["--request-timeout-seconds", "0.5", "--provider-retries", "5"],
            0.5,
            5,
            id="fractional-timeout-max-retries",
        ),
    ],
)
def test_cli_provider_controls_reach_settings_cases_and_report(
    arguments: list[str],
    timeout: float,
    retries: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def configured_settings(**kwargs: Any) -> Settings:
        return Settings(gemini_api_key="private-secret", **kwargs)

    with (
        patch("sys.argv", ["live_evaluation", "--live", *arguments]),
        patch(
            "scripts.live_evaluation.Settings", side_effect=configured_settings
        ) as factory,
        patch(
            "scripts.live_evaluation.run_case",
            return_value={"outcome": "provider_error"},
        ) as run,
    ):
        assert main() == 1

    assert factory.call_args.kwargs["gemini_request_timeout_seconds"] == timeout
    assert factory.call_args.kwargs["gemini_max_retries"] == retries
    settings = run.call_args.args[1]
    assert settings.gemini_request_timeout_seconds == timeout
    assert settings.gemini_max_retries == retries
    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["run_settings"]["request_timeout_seconds"] == timeout
    assert report["provider_retries"] == retries
    assert "private-secret" not in output


@pytest.mark.parametrize(
    "argument",
    [
        "--request-timeout-seconds=0",
        "--request-timeout-seconds=-1",
        "--request-timeout-seconds=nan",
        "--request-timeout-seconds=inf",
        "--request-timeout-seconds=-inf",
        "--request-timeout-seconds=not-a-number",
        "--provider-retries=-1",
        "--provider-retries=6",
        "--provider-retries=1.5",
    ],
)
def test_cli_rejects_invalid_provider_controls_before_any_run(
    argument: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with (
        patch("sys.argv", ["live_evaluation", "--live", argument]),
        patch("scripts.live_evaluation.Settings") as settings,
        patch("scripts.live_evaluation.run_case") as run,
        pytest.raises(SystemExit) as caught,
    ):
        main()

    assert caught.value.code == 2
    settings.assert_not_called()
    run.assert_not_called()
    assert "error:" in capsys.readouterr().err
