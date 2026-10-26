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
    CHALLENGE_CASES,
    control_baseline,
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
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_compaction import InvestigationCompaction
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
    [
        ("all", 5),
        ("finance", 1),
        ("healthcare", 1),
        ("logistics", 1),
        ("challenge", 3),
        ("energy_grain", 1),
    ],
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
    expected_names = (
        set(CASES)
        if selected == "all"
        else set(CHALLENGE_CASES)
        if selected == "challenge"
        else {selected}
    )
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
    assert "synthetic_evidence" not in report
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
    "kind", ["missing-parent", "existing-file", "existing-directory", "symlink"]
)
def test_invalid_output_is_rejected_before_configuration_or_provider_calls(
    tmp_path: Path, kind: str, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "report.json"
    if kind == "missing-parent":
        path = tmp_path / "missing" / "report.json"
    elif kind == "existing-file":
        path.write_text("original", encoding="utf-8")
    elif kind == "existing-directory":
        path.mkdir()
    with (
        patch("sys.argv", ["live_evaluation", "--live", "--output", str(path)]),
        patch("scripts.live_evaluation.Settings") as settings,
        patch("scripts.live_evaluation.run_case") as run,
        patch("pathlib.Path.is_symlink", return_value=kind == "symlink"),
        pytest.raises(SystemExit) as error,
    ):
        main()
    assert error.value.code == 2
    settings.assert_not_called()
    run.assert_not_called()
    output = capsys.readouterr()
    assert output.out == ""
    assert "Output must be a new file in an existing directory." in output.err
    assert str(path) not in output.err
    if kind == "existing-file":
        assert path.read_text(encoding="utf-8") == "original"


def test_report_save_failure_after_preflight_preserves_stdout(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "report.json"
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
        patch("pathlib.Path.open", side_effect=OSError("private-error")),
    ):
        assert main() == 2

    output = capsys.readouterr()
    assert json.loads(output.out)["results"]["finance"]["outcome"] == "provider_error"
    assert output.err == "Could not save evaluation report to a new file.\n"
    assert str(path) not in output.err
    assert "private-error" not in output.err
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


@pytest.mark.parametrize("name", list(CHALLENGE_CASES))
def test_challenge_controls_match_independent_arithmetic(
    tmp_path: Path, name: str
) -> None:
    case = CHALLENGE_CASES[name]
    paths = []
    for filename, content in case.files:
        path = tmp_path / filename
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    expected = {
        "energy_grain": Decimal("11.25") + Decimal("11.25") + Decimal("7.5"),
        "research_weighted": (Decimal(100) * 1 + Decimal(300) * 3) / 400,
        "education_entities": Decimal(100) * 3 / 8,
    }[name]
    app = VeriSight(
        settings=Settings(gemini_api_key=None, allow_llm_data_disclosure=False)
    )
    with patch.object(app, "investigate") as investigate:
        report = control_baseline(case, app, paths)
    investigate.assert_not_called()
    assert Decimal(case.answer) == expected
    assert Decimal(str(report["actual"])) == expected
    assert report["outcome"] == "correct_numeric"
    assert report["kind"] == "supplied_sql_control"
    assert isinstance(report["elapsed_seconds"], float)


@pytest.mark.parametrize("provider_failure", [False, True])
def test_challenge_baseline_is_retained_without_leaking_answers_to_generation(
    result: InvestigationResult, provider_failure: bool
) -> None:
    case = CHALLENGE_CASES["energy_grain"]
    with patch.object(
        VeriSight,
        "investigate",
        side_effect=GeminiGenerationError("private-secret")
        if provider_failure
        else None,
        return_value=result,
    ) as investigate:
        report = run_case(
            case, Settings(gemini_api_key=None, allow_llm_data_disclosure=False)
        )
    baseline = report["control_baseline"]
    assert isinstance(baseline, dict)
    assert baseline["outcome"] == "correct_numeric"
    assert Decimal(baseline["actual"]) == Decimal(30)
    assert report["outcome"] == (
        "provider_error" if provider_failure else "correct_numeric"
    )
    prompt = investigate.call_args.args[1]
    assert prompt.startswith(case.question)
    assert case.control_sql not in prompt
    assert case.answer not in prompt
    assert investigate.call_args.kwargs == {"max_steps": 1}
    assert all(not path.exists() for path in investigate.call_args.args[0])
    assert "private-secret" not in json.dumps(report)


def test_challenge_stops_before_generation_when_control_disagrees() -> None:
    case = replace(CHALLENGE_CASES["energy_grain"], answer="31")
    with patch.object(VeriSight, "investigate") as investigate:
        report = run_case(
            case, Settings(gemini_api_key=None, allow_llm_data_disclosure=False)
        )
    investigate.assert_not_called()
    assert report["outcome"] == "baseline_error"
    baseline = report["control_baseline"]
    assert isinstance(baseline, dict)
    assert baseline["outcome"] == "incorrect_numeric"
    assert baseline["expected"] == "31"


@pytest.mark.parametrize(
    "query_result",
    [
        QueryResult(columns=("metric",), rows=()),
        QueryResult(columns=("a", "b"), rows=((1, 2),)),
        QueryResult(columns=("metric",), rows=((None,),)),
        QueryResult(columns=("metric",), rows=((True,),)),
        QueryResult(columns=("metric",), rows=(("30",),)),
        QueryResult(columns=("metric",), rows=((float("nan"),),)),
        QueryResult(columns=("metric",), rows=((float("inf"),),)),
    ],
    ids=["no-rows", "two-columns", "null", "boolean", "text", "nan", "infinite"],
)
def test_control_baseline_rejects_nonmetric_results(query_result: QueryResult) -> None:
    app = VeriSight(settings=Settings(gemini_api_key=None))
    with (
        patch.object(app, "execute", return_value=query_result),
        pytest.raises(ValueError, match="control must return"),
    ):
        control_baseline(CHALLENGE_CASES["energy_grain"], app, [])


def test_control_baseline_requires_supplied_sql() -> None:
    app = VeriSight(settings=Settings(gemini_api_key=None))
    with (
        patch.object(app, "execute") as execute,
        pytest.raises(ValueError, match="control query is required"),
    ):
        control_baseline(CASES["finance"], app, [])
    execute.assert_not_called()


@pytest.mark.parametrize("column", ["metric", "missing_column"])
@pytest.mark.parametrize("incomplete", [False, True])
def test_run_case_retains_exact_synthetic_evidence_for_failed_answers(
    result: InvestigationResult, column: str, incomplete: bool
) -> None:
    actual = Decimal("2.500000000000000001")
    sql = "SELECT measured_value AS metric FROM assays"
    observation = QueryObservation(
        question="synthetic-subquestion-for-report",
        sql=sql,
        result=QueryResult(columns=("metric",), rows=((actual,),)),
    )
    claim = NumericalClaim(
        ClaimOperation.VALUE,
        Decimal("2.5"),
        EvidenceReference(0, 0, column),
    )
    investigation = replace(
        result,
        conclusion="synthetic-conclusion-for-report",
        observations=(observation,),
        generated_claims=(claim,),
        status=InvestigationStatus.INCOMPLETE
        if incomplete
        else InvestigationStatus.COMPLETE,
    )
    with patch.object(VeriSight, "investigate", return_value=investigation):
        report = run_case(
            CHALLENGE_CASES["research_weighted"],
            Settings(gemini_api_key=None, allow_llm_data_disclosure=False),
        )

    serialized = json.dumps(report, allow_nan=False)
    saved = json.loads(serialized)
    assert saved["expected"] == "2.5"
    assert saved["outcome"] == ("incomplete" if incomplete else "unverified_answer")
    assert saved["control_baseline"]["outcome"] == "correct_numeric"
    evidence = saved["synthetic_evidence"]
    assert set(evidence) == {
        "question",
        "conclusion",
        "observations",
        "verified_claims",
    }
    assert evidence["question"] == investigation.question
    assert evidence["conclusion"] == "synthetic-conclusion-for-report"
    assert evidence["observations"] == [
        {
            "question": "synthetic-subquestion-for-report",
            "sql": sql,
            "result": {"columns": ["metric"], "rows": [[str(actual)]]},
        }
    ]
    item = evidence["verified_claims"][0]
    assert item["claim"]["operation"] == "value"
    assert item["claim"]["expected"] == "2.5"
    assert item["claim"]["left"] == {
        "observation_index": 0,
        "row_index": 0,
        "column": column,
    }
    assert item["claim"]["right"] is None
    verification = item["verification"]
    assert verification["expected"] == "2.5"
    assert verification["absolute_tolerance"] == "0"
    assert verification["actual"] == (str(actual) if column == "metric" else None)
    assert verification["status"] == (
        "contradicted" if column == "metric" else "unverifiable"
    )
    assert verification["reason"]
    summary = score_result(investigation, "2.5")
    assert "question" not in summary
    assert "conclusion" not in summary
    assert "synthetic-subquestion-for-report" not in json.dumps(summary)
    assert "synthetic-conclusion-for-report" not in json.dumps(summary)


@pytest.mark.parametrize(
    "scale,claim_value,fraction_requested,outcome,verification",
    [
        ("100.0", "37.5", False, "correct_numeric", "supported"),
        ("1.0", "0.375", False, "incorrect_numeric", "supported"),
        ("1.0", "37.5", False, "unverified_answer", "contradicted"),
        ("1.0", "0.375", True, "correct_numeric", "supported"),
    ],
    ids=["percentage-cell", "fraction-cell", "invented-conversion", "fraction-request"],
)
def test_percentage_scale_uses_real_sql_and_keeps_strict_scoring(
    scale: str,
    claim_value: str,
    fraction_requested: bool,
    outcome: str,
    verification: str,
) -> None:
    case = CHALLENGE_CASES["education_entities"]
    assert case.control_sql is not None
    if fraction_requested:
        case = replace(
            case,
            question=case.question.replace(
                "what percentage completed?", "what fraction completed?"
            ),
            answer="0.375",
            control_sql=case.control_sql.replace("100.0", "1.0"),
        )
    assert case.control_sql is not None
    sql = case.control_sql.replace("100.0", scale)
    responses = [
        json.dumps(
            {
                "action": "investigate",
                "reasoning": "Obtain the metric.",
                "question": case.question,
            }
        ),
        sql,
        json.dumps(
            {
                "action": "finish",
                "reasoning": "Inspect the available result.",
                "question": None,
            }
        ),
        json.dumps(
            {
                "conclusion": "The supplied metric is " + claim_value + ".",
                "claims": [
                    {
                        "operation": "value",
                        "expected": claim_value,
                        "left": {
                            "observation_index": 0,
                            "row_index": 0,
                            "column": "metric",
                        },
                        "right": None,
                    }
                ],
            }
        ),
    ]
    with patch(
        "verisight.execution.gemini.GeminiTextGenerationClient.generate",
        side_effect=responses,
    ) as generate:
        report = run_case(
            case,
            Settings(gemini_api_key="offline-stub-key", allow_llm_data_disclosure=True),
        )
    assert generate.call_count == 4
    for call in generate.call_args_list:
        prompt = call.args[0]
        assert "Requested metric scale:" in prompt
        assert "100.0 * numerator / NULLIF(denominator, 0)" in prompt
        assert "not the unscaled fraction" in prompt
        assert "fraction or proportion unscaled" in prompt
        assert "do not infer scale from magnitude alone" in prompt
    first_prompt = generate.call_args_list[0].args[0]
    assert "Before choosing finish, check that visible SQL evidence" in first_prompt
    final_prompt = generate.call_args_list[-1].args[0]
    assert "explain the limitation and omit that final-metric claim" in final_prompt
    assert "Do not multiply or divide evidence in the conclusion" in final_prompt
    assert report["outcome"] == outcome
    assert report["verification_status"] == verification
    baseline = report["control_baseline"]
    assert isinstance(baseline, dict)
    assert baseline["outcome"] == "correct_numeric"
    evidence = report["synthetic_evidence"]
    assert isinstance(evidence, dict)
    observations = evidence["observations"]
    assert isinstance(observations, list)
    assert str(evidence["question"]).startswith(case.question)
    assert evidence["conclusion"] == "The supplied metric is " + claim_value + "."
    assert observations[0]["question"] == evidence["question"]
    assert observations[0]["sql"] == sql
    assert observations[0]["result"]["rows"] == [[37.5 if scale == "100.0" else 0.375]]
    claims = evidence["verified_claims"]
    assert isinstance(claims, list)
    assert claims[0]["claim"]["expected"] == claim_value
    assert claims[0]["verification"]["rounding_policy"] is None


def test_compact_investigator_keeps_requested_metric_scale(
    result: InvestigationResult,
) -> None:
    state = InvestigationState(
        question="What percentage completed?",
        analysis=result.analysis,
        observations=result.observations,
    )
    prompt = InvestigationCompaction().investigator_prompt(state)
    assert "Requested metric scale:" in prompt
    assert "100.0 * numerator / NULLIF(denominator, 0)" in prompt
    assert "not the unscaled fraction" in prompt
    assert "fraction or proportion unscaled" in prompt
    assert "percentage-point change" in prompt
    assert "relative percentage change" in prompt
    assert "do not infer scale from magnitude alone" in prompt
    assert "Before choosing finish" in prompt
    assert "otherwise explain the scale limitation" in prompt


@pytest.mark.parametrize(
    "active_only,actual,outcome",
    [(True, "37.5", "correct_numeric"), (False, "40", "incorrect_numeric")],
    ids=["requested-active-population", "broader-not-cancelled-population"],
)
def test_education_fixture_distinguishes_inclusion_from_exclusion(
    tmp_path: Path,
    result: InvestigationResult,
    active_only: bool,
    actual: str,
    outcome: str,
) -> None:
    case = CHALLENGE_CASES["education_entities"]
    assert case.answer == "37.5"
    assert case.control_sql is not None
    sql = case.control_sql
    if not active_only:
        sql = sql.replace(
            "\"enrolment state\" = 'active'",
            "\"enrolment state\" != 'cancelled'",
        )
        assert sql != case.control_sql
    paths = []
    for filename, content in case.files:
        path = tmp_path / filename
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    app = VeriSight(
        settings=Settings(gemini_api_key=None, allow_llm_data_disclosure=False)
    )
    query_result = app.execute(paths, sql)
    expected = Decimal(100) * 3 / 8 if active_only else Decimal(100) * 4 / 10
    assert Decimal(actual) == expected
    assert query_result.row_count == 1
    assert Decimal(str(query_result.rows[0][0])) == expected
    observation = QueryObservation(question=case.question, sql=sql, result=query_result)
    investigation = replace(
        result,
        question=case.question,
        conclusion="The completion percentage is " + actual + ".",
        observations=(observation,),
        generated_claims=(
            NumericalClaim(
                ClaimOperation.VALUE, Decimal(actual), EvidenceReference(0, 0, "metric")
            ),
        ),
    )
    scored = score_result(investigation, case.answer)
    assert scored["verification_status"] == "supported"
    assert scored["outcome"] == outcome
    assert Decimal(str(scored["actual"])) == expected


@pytest.mark.parametrize("repair", [False, True], ids=["planning", "runtime-repair"])
def test_investigation_keeps_original_scope_when_subquestion_loses_inclusion(
    repair: bool,
) -> None:
    case = CHALLENGE_CASES["education_entities"]
    assert case.control_sql is not None
    subquestion = (
        "For cohort 2026, what percentage of distinct learners with known outcomes "
        "completed? Exclude cancelled enrolments."
    )
    responses = [
        json.dumps(
            {
                "action": "investigate",
                "reasoning": "Measure completion.",
                "question": subquestion,
            }
        ),
        "SELECT missing_metric FROM enrolments" if repair else case.control_sql,
    ]
    if repair:
        responses.append(case.control_sql)
    responses.extend(
        [
            json.dumps(
                {
                    "action": "finish",
                    "reasoning": "The metric is available.",
                    "question": None,
                }
            ),
            json.dumps(
                {
                    "conclusion": "The completion percentage is 37.5.",
                    "claims": [
                        {
                            "operation": "value",
                            "expected": "37.5",
                            "left": {
                                "observation_index": 0,
                                "row_index": 0,
                                "column": "metric",
                            },
                            "right": None,
                        }
                    ],
                }
            ),
        ]
    )
    with patch(
        "verisight.execution.gemini.GeminiTextGenerationClient.generate",
        side_effect=responses,
    ) as generate:
        report = run_case(
            case,
            Settings(gemini_api_key="offline-stub-key", allow_llm_data_disclosure=True),
        )
    assert generate.call_count == 4 + int(repair)
    assert report["outcome"] == "correct_numeric"
    evidence = report["synthetic_evidence"]
    assert isinstance(evidence, dict)
    original = evidence["question"]
    assert isinstance(original, str)
    assert original.startswith(case.question)
    observations = evidence["observations"]
    assert isinstance(observations, list)
    assert observations[0]["question"] == original
    assert observations[0]["sql"] == case.control_sql
    assert observations[0]["result"]["rows"] == [[37.5]]
    planning = generate.call_args_list[1].args[0]
    assert (
        "ORIGINAL INVESTIGATION QUESTION (untrusted analytical context):\n" + original
        in planning
    )
    assert "QUESTION:\n" + original in planning
    assert (
        "Preserve positive inclusion requirements independently of exclusions"
        in planning
    )
    assert "Do not blanket-filter a deliberately requested comparison" in planning
    assert case.control_sql not in planning
    assert case.answer not in planning
    if repair:
        repair_prompt = generate.call_args_list[2].args[0]
        assert (
            "ORIGINAL INVESTIGATION QUESTION (untrusted analytical context):\n"
            + original
            in repair_prompt
        )
        assert "ORIGINAL QUESTION:\n" + original in repair_prompt
        assert (
            "Preserve positive inclusion requirements independently of exclusions"
            in repair_prompt
        )
        assert "SELECT missing_metric FROM enrolments" in repair_prompt
        assert case.control_sql not in repair_prompt
        assert case.answer not in repair_prompt
    for index in [0, -2, -1]:
        prompt = generate.call_args_list[index].args[0]
        assert (
            "Preserve positive inclusion requirements independently of exclusions"
            in prompt
        )
        assert "population actually selected by SQL" in prompt
    assert (
        "Do not relabel the result with the requested population name"
        in generate.call_args_list[-1].args[0]
    )
