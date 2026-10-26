"""Opt-in live evaluation on synthetic data, with independent numerical answers."""

import argparse
import json
import platform
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter

from verisight import VeriSight
from verisight.config import Settings
from verisight.error_reporting import to_public_error
from verisight.exceptions import ConfigurationError
from verisight.execution.claim_verification import ClaimOperation, VerificationStatus
from verisight.execution.gemini import GeminiGenerationError
from verisight.execution.generation_telemetry import capture_generation_calls
from verisight.execution.investigation_result import (
    InvestigationResult,
    InvestigationStatus,
)
from verisight.serialization import to_jsonable


@dataclass(frozen=True)
class Case:
    files: tuple[tuple[str, str], ...]
    question: str
    answer: str
    control_sql: str | None = None


CASES = {
    "finance": Case(
        files=(
            (
                "ledger.csv",
                "cents,state\n12500,posted\n-2500,posted\n50,posted\n999,pending\n",
            ),
        ),
        question=(
            "What is the net posted amount in cents? Exclude pending transactions."
        ),
        answer="10050",
    ),
    "retail": Case(
        files=(
            ("lines.csv", "sku,quantity\nA,2\nB,3\nA,1\n"),
            ("prices.csv", "sku,unit_price\nA,10\nB,20\n"),
        ),
        question=(
            "What is the total line value? Match each line to its SKU's unit price."
        ),
        answer="90",
    ),
    "manufacturing": Case(
        files=(("inspections.csv", "id,defective\n1,1\n2,0\n3,0\n4,0\n5,\n"),),
        question=(
            "What percentage of known inspection outcomes are defective? "
            "Defective is 1 for defective and 0 otherwise. Exclude unknown outcomes."
        ),
        answer="25",
    ),
    "healthcare": Case(
        files=(
            (
                "visits.csv",
                "minutes,state\n10,completed\n,completed\n30,completed\n100,cancelled\n",
            ),
        ),
        question=(
            "What is the mean recorded wait in minutes for completed visits? "
            "Exclude missing waits and cancelled visits."
        ),
        answer="20",
    ),
    "logistics": Case(
        files=(
            (
                "deliveries.csv",
                "id,late,state\n1,1,delivered\n2,0,delivered\n3,,delivered\n4,1,cancelled\n",
            ),
        ),
        question=(
            "What percentage of delivered shipments with a known late indicator "
            "were late? Late is 1 for late and 0 otherwise. "
            "Exclude missing indicators and cancelled shipments."
        ),
        answer="50",
    ),
}

CHALLENGE_CASES = {
    "energy_grain": Case(
        files=(
            (
                "generation.csv",
                "reading id,output kWh,record type\n"
                "R1,11.25,production\nR2,11.25,production\n"
                "R3,7.5,production\nR4,100,production\nR5,999,test\n",
            ),
            (
                "reviews.csv",
                "reading id,decision\nR1,approved\nR1,approved\n"
                "R2,approved\nR3,approved\nR3,rejected\n"
                "R4,rejected\nR5,approved\n",
            ),
        ),
        question=(
            "What is the total production output in kWh for readings with at least "
            "one approved review? Count each reading id once, even if it has "
            "multiple approved reviews. Distinct readings with equal output "
            "both count. Exclude test records."
        ),
        answer="30",
        control_sql=(
            'SELECT SUM(g."output kWh") AS metric FROM generation g '
            "WHERE g.\"record type\" = 'production' AND EXISTS ("
            'SELECT 1 FROM reviews r WHERE r."reading id" = g."reading id" '
            "AND r.decision = 'approved')"
        ),
    ),
    "research_weighted": Case(
        files=(
            (
                "assays.csv",
                "sample code,mass g,assay pct,review state\n"
                "A,100,1,accepted\nB,300,3,accepted\n"
                "C,200,,accepted\nD,,90,accepted\n"
                "E,50,99,rejected\nF,0,100,accepted\n",
            ),
        ),
        question=(
            "What is the mass-weighted mean assay percentage for accepted samples? "
            "Include only rows with a recorded assay percentage and recorded "
            "positive mass. Return the result in percentage units, not a fraction."
        ),
        answer="2.5",
        control_sql=(
            'SELECT SUM("mass g" * "assay pct") / SUM("mass g") AS metric '
            "FROM assays WHERE \"review state\" = 'accepted' "
            'AND "mass g" > 0 AND "assay pct" IS NOT NULL'
        ),
    ),
    "education_entities": Case(
        files=(
            (
                "enrolments.csv",
                "learner id,cohort,enrolment state,outcome\n"
                "A,2026,active,complete\nA,2026,active,complete\n"
                "A,2026,active,complete\nB,2026,active,complete\n"
                "C,2026,active,complete\nD,2026,active,incomplete\n"
                "E,2026,active,incomplete\nF,2026,active,incomplete\n"
                "G,2026,active,incomplete\nH,2026,active,incomplete\n"
                "I,2026,cancelled,complete\nJ,2026,active,\n"
                "K,2025,active,complete\n"
                "L,2026,waitlisted,complete\nM,2026,waitlisted,incomplete\n",
            ),
        ),
        question=(
            "Among distinct active learners in cohort 2026 with a known outcome, "
            "what percentage completed? Outcomes are complete or incomplete. "
            "Count learner identities, not enrolment rows. Exclude cancelled "
            "enrolments, missing outcomes, and other cohorts."
        ),
        answer="37.5",
        control_sql=(
            "SELECT 100.0 * COUNT(DISTINCT CASE WHEN outcome = 'complete' "
            'THEN "learner id" END) / COUNT(DISTINCT "learner id") AS metric '
            "FROM enrolments WHERE cohort = 2026 AND \"enrolment state\" = 'active' "
            "AND outcome IN ('complete', 'incomplete')"
        ),
    ),
}

REQUEST = (
    " Answer only this metric. Use one analytical query and then finish. "
    "Return exactly one numerical VALUE claim referring to the final metric cell. "
    "Do not add numerical claims for intermediate values. "
    "If the evidence is insufficient, explain that and return no claims."
)


def score_result(result: InvestigationResult, answer: str) -> dict[str, object]:
    """Score the single submitted metric, never certify its prose or SQL semantics."""
    report: dict[str, object] = {
        "expected": answer,
        "observation_count": result.observation_count,
        "claim_count": len(result.verified_claims),
        "narrative_verified": result.narrative_verified,
        "narrative_number_audit_scope": result.narrative_number_audit_scope,
        "narrative_number_count": len(result.narrative_numbers),
        "unlinked_number_count": len(result.unlinked_numbers),
        "narrative_digit_coverage": asdict(result.narrative_digit_coverage),
    }
    if result.status is InvestigationStatus.INCOMPLETE:
        report["outcome"] = "incomplete"
        if result.synthesis_failure is not None:
            report["synthesis_failure"] = asdict(result.synthesis_failure)
        if result.investigation_failure is not None:
            report["investigation_failure"] = asdict(result.investigation_failure)
    elif not result.verified_claims:
        report["outcome"] = "no_claims"
    elif len(result.verified_claims) != 1:
        report["outcome"] = "ambiguous_claims"
    else:
        item = result.verified_claims[0]
        report["verification_status"] = item.verification.status.value
        if item.claim.operation is not ClaimOperation.VALUE:
            report["outcome"] = "unsupported_answer_format"
        elif item.verification.status is not VerificationStatus.SUPPORTED:
            report["outcome"] = "unverified_answer"
        else:
            report["actual"] = str(item.verification.actual)
            report["outcome"] = (
                "correct_numeric"
                if item.verification.actual == Decimal(answer)
                else "incorrect_numeric"
            )
    return report


def summarize_number_audits(
    results: dict[str, dict[str, object]],
) -> dict[str, int]:
    """Count token occurrences; missing audits are not zero-token conclusions."""
    audited = 0
    detected = 0
    unlinked = 0
    cases_with_unlinked = 0
    for report in results.values():
        token_count = report.get("narrative_number_count")
        unmatched_count = report.get("unlinked_number_count")
        if type(token_count) is not int or type(unmatched_count) is not int:
            continue
        if not 0 <= unmatched_count <= token_count:
            continue
        audited += 1
        detected += token_count
        unlinked += unmatched_count
        cases_with_unlinked += int(unmatched_count > 0)
    return {
        "audited_case_count": audited,
        "unaudited_case_count": len(results) - audited,
        "detected_token_count": detected,
        "unlinked_token_count": unlinked,
        "cases_with_unlinked_tokens": cases_with_unlinked,
    }


def failure_report(error: Exception) -> dict[str, object]:
    """Classify provider causes without exposing exception text or credentials."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, GeminiGenerationError):
            report: dict[str, object] = {"outcome": "provider_error"}
            if current.diagnostics is not None:
                report["diagnostics"] = asdict(current.diagnostics)
            return report
        current = current.__cause__
    return {"outcome": "application_error", "code": to_public_error(error).code.value}


def control_baseline(
    case: Case, app: VeriSight, paths: list[Path]
) -> dict[str, object]:
    """Check supplied control SQL against a separately specified expected answer."""
    if case.control_sql is None:
        raise ValueError("A control query is required.")
    started = perf_counter()
    result = app.execute(paths, case.control_sql)
    if result.row_count != 1 or result.column_count != 1:
        raise ValueError("The control must return one numerical cell.")
    value = result.rows[0][0]
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("The control must return a numerical value.")
    actual = Decimal(str(value))
    if not actual.is_finite():
        raise ValueError("The control must return a finite value.")
    return {
        "kind": "supplied_sql_control",
        "expected": case.answer,
        "actual": str(actual),
        "outcome": (
            "correct_numeric" if actual == Decimal(case.answer) else "incorrect_numeric"
        ),
        "elapsed_seconds": round(perf_counter() - started, 3),
    }


def run_case(case: Case, settings: Settings) -> dict[str, object]:
    """Use temporary synthetic files and the real default investigation path."""
    baseline: dict[str, object] | None = None
    with capture_generation_calls() as calls:
        try:
            with TemporaryDirectory(prefix="verisight-evaluation-") as directory:
                paths = []
                for filename, content in case.files:
                    path = Path(directory) / filename
                    path.write_text(content, encoding="utf-8")
                    paths.append(path)
                app = VeriSight(settings=settings)
                if case.control_sql is not None:
                    baseline = control_baseline(case, app, paths)
                    if baseline["outcome"] != "correct_numeric":
                        return {
                            "outcome": "baseline_error",
                            "control_baseline": baseline,
                        }
                result = app.investigate(paths, case.question + REQUEST, max_steps=1)
                report = score_result(result, case.answer)
                report["synthetic_evidence"] = to_jsonable(
                    {
                        "question": result.question,
                        "conclusion": result.conclusion,
                        "observations": [
                            {
                                "question": item.question,
                                "sql": item.sql,
                                "result": item.result,
                            }
                            for item in result.observations
                        ],
                        "verified_claims": result.verified_claims,
                    }
                )
        except Exception as error:
            report = failure_report(error)
    if baseline is not None:
        report["control_baseline"] = baseline
    if calls:
        report["generation_calls"] = [asdict(call) for call in calls]
    return report


def repository_metadata() -> dict[str, object]:
    """Read local revision metadata without returning paths or Git error text."""
    metadata: dict[str, object] = {
        "commit": None,
        "tracked_changes": None,
        "status_scope": "tracked_files_only",
    }
    root = Path(__file__).resolve().parents[1]
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return metadata
    metadata["commit"] = commit
    metadata["tracked_changes"] = bool(status)
    return metadata


def _positive_timeout(value: str) -> float:
    """Reject invalid deadlines before constructing settings or calling a provider."""
    try:
        timeout = float(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError(
            "Timeout must be finite and positive."
        ) from error
    if not 0 < timeout < float("inf"):
        raise argparse.ArgumentTypeError("Timeout must be finite and positive.")
    return timeout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Allow Gemini calls using synthetic data."
    )
    parser.add_argument(
        "--case",
        choices=[*CASES, *CHALLENGE_CASES, "all", "challenge"],
        default="finance",
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=_positive_timeout,
        default=20.0,
        help="Deadline per provider request in seconds (default: 20).",
    )
    parser.add_argument(
        "--provider-retries",
        type=int,
        choices=range(6),
        default=0,
        help="Additional transient-error retries per generation call (default: 0).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Save JSON to a new file; parent directory must exist.",
    )
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to authorize provider calls; API charges may apply.")
    if args.output is not None and (
        args.output.exists()
        or args.output.is_symlink()
        or not args.output.parent.is_dir()
    ):
        parser.error("Output must be a new file in an existing directory.")

    try:
        settings = Settings(
            allow_llm_data_disclosure=True,
            gemini_max_retries=args.provider_retries,
            gemini_request_timeout_seconds=args.request_timeout_seconds,
            max_query_execution_seconds=5.0,
            max_query_result_rows=20,
        )
        if settings.gemini_api_key is None or not settings.gemini_api_key.strip():
            raise ConfigurationError("An API key is required.")
    except Exception as error:
        print(json.dumps(failure_report(error), indent=2))
        return 2

    if args.case == "all":
        selected = CASES
    elif args.case == "challenge":
        selected = CHALLENGE_CASES
    else:
        available = {**CASES, **CHALLENGE_CASES}
        selected = {args.case: available[args.case]}
    revision = repository_metadata()
    started_at = datetime.now(UTC).isoformat()
    started = perf_counter()
    results = {}
    for name, case in selected.items():
        case_started = perf_counter()
        case_report = run_case(case, settings)
        case_report["elapsed_seconds"] = round(perf_counter() - case_started, 3)
        results[name] = case_report
    elapsed = round(perf_counter() - started, 3)
    counts = Counter(str(result["outcome"]) for result in results.values())
    report = {
        "schema_version": 2,
        "timestamp_utc": started_at,
        "elapsed_seconds": elapsed,
        "revision": revision,
        "python_version": platform.python_version(),
        "model": settings.gemini_model,
        "max_steps_per_case": 1,
        "provider_retries": settings.gemini_max_retries,
        "run_settings": {
            "allow_llm_data_disclosure": settings.allow_llm_data_disclosure,
            "request_timeout_seconds": settings.gemini_request_timeout_seconds,
            "max_investigation_seconds": settings.max_investigation_seconds,
            "retry_base_delay_seconds": settings.gemini_retry_base_delay_seconds,
            "max_upload_size_mb": settings.max_upload_size_mb,
            "max_query_execution_seconds": settings.max_query_execution_seconds,
            "max_query_result_rows": settings.max_query_result_rows,
            "max_query_result_bytes": settings.max_query_result_bytes,
            "max_query_memory_mb": settings.max_query_memory_mb,
            "max_query_temp_storage_mb": settings.max_query_temp_storage_mb,
        },
        "generation_telemetry_scope": "client_calls_observed_during_case",
        "scoring_scope": "single_claim_numeric_answer_only",
        "limitations": (
            "No narrative or general semantic certification. No-claims responses "
            "are not automatically proven abstentions. These are known development "
            "fixtures, not a held-out generalization benchmark."
        ),
        "case_count": len(results),
        "outcome_counts": dict(counts),
        "number_audit_summary": summarize_number_audits(results),
        "results": results,
    }
    serialized = json.dumps(report, indent=2)
    print(serialized)
    if args.output is not None:
        try:
            with args.output.open("x", encoding="utf-8", newline="\n") as output:
                output.write(serialized + "\n")
        except OSError:
            print("Could not save evaluation report to a new file.", file=sys.stderr)
            return 2
    return 0 if counts.get("correct_numeric", 0) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
