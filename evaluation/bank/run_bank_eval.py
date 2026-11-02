"""Repeated VeriSight evaluation on the UCI Bank Marketing dataset.

Each case has a question, an expected answer computed here with the csv
module and Decimal (independent of pandas, DuckDB and VeriSight), a correct
control SQL and a plausible trap SQL. Offline preflight proves that the
control reproduces the answer and the trap does not, before any model call.

Every attempt is kept, including failures. Nothing is overwritten.

Usage (PowerShell, from the VeriSight repository root, venv active):
    python evaluation\\bank\\run_bank_eval.py `
        --dataset datasets\\bank_marketing\\bank-additional-full.csv `
        --out F:\\verisight-validation-artifacts\\bank-eval-v1\\run-1 `
        --preflight-only
Keep --out outside the repository so results are never committed by accident.
"""

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from importlib import metadata
from pathlib import Path

DATASET_SHA256 = "74adfc578bf77a7ff4bb1ba4a9f8709d9e3c6907342959c2c8416847e0afb4d8"
RELATION = "bank_additional_full"
TOLERANCE = Decimal("0.005")
Row = dict[str, str]


def _pct(
    rows: list[Row],
    numerator: Callable[[Row], bool],
    denominator: Callable[[Row], bool],
) -> Decimal:
    eligible = [row for row in rows if denominator(row)]
    return Decimal(100) * sum(1 for row in eligible if numerator(row)) / len(eligible)


def _mean(values: list[int]) -> Decimal:
    return Decimal(sum(values)) / len(values)


def _median(values: list[int]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return Decimal(ordered[middle])
    return (Decimal(ordered[middle - 1]) + Decimal(ordered[middle])) / 2


def _subscribed(row: Row) -> bool:
    return row["y"] == "yes"


def _job_rate(rows: list[Row], job: str) -> Decimal:
    return _pct(rows, _subscribed, lambda row: row["job"] == job)


def _max_job_rate(rows: list[Row], minimum: int) -> Decimal:
    jobs = {row["job"] for row in rows}
    sizes = {job: sum(1 for row in rows if row["job"] == job) for job in jobs}
    return max(_job_rate(rows, job) for job in jobs if sizes[job] >= minimum)


@dataclass(frozen=True)
class Case:
    case_id: str
    skill: str
    question: str
    operation: str
    oracle: Callable[[list[Row]], Decimal]
    control_sql: str
    trap_sql: str
    trap_description: str
    integer: bool = False


R = f'"{RELATION}"'
RATE = "100.0 * SUM(CASE WHEN y = 'yes' THEN 1 ELSE 0 END) / COUNT(*)"
UNI = "100.0 * SUM(CASE WHEN education = 'university.degree' THEN 1 ELSE 0 END)"
WIN = "100.0 * SUM(CASE WHEN poutcome = 'success' THEN 1 ELSE 0 END)"
CASES = (
    Case(
        "housing_loan_subscription_rate",
        "population: three-valued category",
        "Among clients who have a housing loan (housing is yes), what percentage "
        "subscribed to a term deposit (y is yes)? Report the percentage as a single "
        "number.",
        "value",
        lambda rows: _pct(rows, _subscribed, lambda row: row["housing"] == "yes"),
        f"SELECT {RATE} AS v FROM {R} WHERE housing = 'yes'",
        f"SELECT {RATE} AS v FROM {R} WHERE housing <> 'no'",
        "housing <> 'no' also includes housing = 'unknown'",
    ),
    Case(
        "no_default_subscription_rate",
        "population: three-valued category",
        "Among clients whose credit default status is no, what percentage subscribed "
        "to a term deposit? Report the percentage as a single number.",
        "value",
        lambda rows: _pct(rows, _subscribed, lambda row: row["default"] == "no"),
        f"SELECT {RATE} AS v FROM {R} WHERE \"default\" = 'no'",
        f"SELECT {RATE} AS v FROM {R} WHERE \"default\" <> 'yes'",
        "default <> 'yes' also includes default = 'unknown'",
    ),
    Case(
        "married_with_personal_loan_count",
        "population: three-valued category, count",
        "How many clients are married and have a personal loan (loan is yes)? "
        "Report the count as a single number.",
        "value",
        lambda rows: Decimal(
            sum(
                1
                for row in rows
                if row["marital"] == "married" and row["loan"] == "yes"
            )
        ),
        f"SELECT COUNT(*) AS v FROM {R} WHERE marital = 'married' AND loan = 'yes'",
        f"SELECT COUNT(*) AS v FROM {R} WHERE marital = 'married' AND loan <> 'no'",
        "loan <> 'no' also includes loan = 'unknown'",
        integer=True,
    ),
    Case(
        "university_share_known_education",
        "denominator: deliberate exclusion",
        "Among clients whose education level is known (exclude education values of "
        "unknown), what percentage have a university degree? Report the percentage "
        "as a single number.",
        "value",
        lambda rows: _pct(
            rows,
            lambda row: row["education"] == "university.degree",
            lambda row: row["education"] != "unknown",
        ),
        f"SELECT {UNI} / COUNT(*) AS v FROM {R} WHERE education <> 'unknown'",
        f"SELECT {UNI} / COUNT(*) AS v FROM {R}",
        "denominator keeps clients with unknown education",
    ),
    Case(
        "mean_days_since_previous_contact",
        "sentinel value",
        "The pdays column records days since the client was last contacted in a "
        "previous campaign, and the value 999 means the client was never previously "
        "contacted. Among previously contacted clients, what is the mean of pdays? "
        "Report it as a single number.",
        "value",
        lambda rows: _mean(
            [int(row["pdays"]) for row in rows if row["pdays"] != "999"]
        ),
        f"SELECT AVG(pdays) AS v FROM {R} WHERE pdays <> 999",
        f"SELECT AVG(pdays) AS v FROM {R}",
        "averages the 999 sentinel as if it were 999 days",
    ),
    Case(
        "previous_success_rate_known_outcome",
        "denominator: eligible subset",
        "Among clients whose previous campaign outcome is known (poutcome is success "
        "or failure), what percentage had a successful previous outcome? Report the "
        "percentage as a single number.",
        "value",
        lambda rows: _pct(
            rows,
            lambda row: row["poutcome"] == "success",
            lambda row: row["poutcome"] in ("success", "failure"),
        ),
        f"SELECT {WIN} / COUNT(*) AS v FROM {R} "
        "WHERE poutcome IN ('success', 'failure')",
        f"SELECT {WIN} / COUNT(*) AS v FROM {R}",
        "divides by all clients, including nonexistent previous outcomes",
    ),
    Case(
        "median_age_of_subscribers",
        "statistic choice",
        "What is the median age of clients who subscribed to a term deposit? Report it "
        "as a single number.",
        "value",
        lambda rows: _median([int(row["age"]) for row in rows if _subscribed(row)]),
        f"SELECT MEDIAN(age) AS v FROM {R} WHERE y = 'yes'",
        f"SELECT AVG(age) AS v FROM {R} WHERE y = 'yes'",
        "mean instead of median",
    ),
    Case(
        "highest_job_rate_min_1000_clients",
        "grouping with a size threshold",
        "Considering only job categories with at least 1000 clients, what is the "
        "highest subscription percentage of any job category? Report the percentage "
        "as a single number.",
        "value",
        lambda rows: _max_job_rate(rows, 1000),
        f"SELECT MAX(r) AS v FROM (SELECT job, {RATE} AS r FROM {R} "
        "GROUP BY job HAVING COUNT(*) >= 1000) AS g",
        f"SELECT MAX(r) AS v FROM (SELECT job, {RATE} AS r FROM {R} GROUP BY job) AS g",
        "ignores the 1000-client threshold (small categories win)",
    ),
    Case(
        "retired_minus_blue_collar_rate",
        "multi-step difference",
        "Measure the subscription percentage for retired clients and for blue-collar "
        "clients separately, then report the retired percentage minus the blue-collar "
        "percentage as one DIFFERENCE claim.",
        "difference",
        lambda rows: _job_rate(rows, "retired") - _job_rate(rows, "blue-collar"),
        f"SELECT (SELECT {RATE} FROM {R} WHERE job = 'retired') "
        f"- (SELECT {RATE} FROM {R} WHERE job = 'blue-collar') AS v",
        f"SELECT (SELECT {RATE} FROM {R} WHERE job = 'blue-collar') "
        f"- (SELECT {RATE} FROM {R} WHERE job = 'retired') AS v",
        "reversed subtraction order",
    ),
    Case(
        "may_subscriber_mean_contacts",
        "combined filters",
        "Among clients last contacted in May who subscribed to a term deposit, what is "
        "the mean number of contacts during this campaign (campaign)? Report it as a "
        "single number.",
        "value",
        lambda rows: _mean(
            [
                int(row["campaign"])
                for row in rows
                if row["month"] == "may" and _subscribed(row)
            ]
        ),
        f"SELECT AVG(campaign) AS v FROM {R} WHERE month = 'may' AND y = 'yes'",
        f"SELECT AVG(campaign) AS v FROM {R} WHERE month = 'may'",
        "drops the subscriber filter",
    ),
)


def _close(actual: Decimal, expected: Decimal, integer: bool) -> bool:
    return actual == expected if integer else abs(actual - expected) <= TOLERANCE


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _rows(path: Path) -> list[Row]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle, delimiter=";"))


def _write_new(path: Path, payload: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, default=str)
        handle.write("\n")


def preflight(dataset: Path) -> dict[str, dict[str, str]]:
    """Prove each case discriminates, using VeriSight's executor without a model."""
    from verisight import VeriSight
    from verisight.config import Settings

    rows = _rows(dataset)
    if len(rows) != 41188:
        raise SystemExit(f"Unexpected row count {len(rows)}; preflight stopped.")
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False, gemini_api_key=None)
    )
    oracles: dict[str, dict[str, str]] = {}
    for case in CASES:
        expected = case.oracle(rows)
        control = Decimal(str(app.execute(dataset, case.control_sql).rows[0][0]))
        trap = Decimal(str(app.execute(dataset, case.trap_sql).rows[0][0]))
        if not _close(control, expected, case.integer):
            raise SystemExit(
                f"{case.case_id}: control {control} != expected {expected}"
            )
        if _close(trap, expected, case.integer):
            raise SystemExit(f"{case.case_id}: trap {trap} is not distinguishable")
        oracles[case.case_id] = {
            "expected": str(expected),
            "control": str(control),
            "trap": str(trap),
        }
        print(
            f"preflight ok  {case.case_id:36s} "
            f"expected={float(expected):.6f}  trap={float(trap):.6f}"
        )
    return oracles


def classify(
    report: dict[str, object] | None, case: Case, expected: Decimal
) -> dict[str, object]:
    """Score one CLI report. Only the SQL evidence cell is compared, never prose."""
    if report is None:
        return {"outcome": "no_report"}
    if report.get("kind") == "operation_error":
        error = report.get("error") or {}
        code = error.get("code") if isinstance(error, dict) else None
        if (
            report.get("provider_diagnostics") is not None
            or code == "provider_unavailable"
        ):
            return {"outcome": "provider_error", "error_code": code}
        return {"outcome": "application_error", "error_code": code}
    investigation = report.get("investigation") or {}
    assert isinstance(investigation, dict)
    sql = [item.get("sql") for item in investigation.get("observations", [])]
    reviews = report.get("advisory_reviews")
    assessment = report.get("claim_output_assessment")
    base: dict[str, object] = {
        "sql": sql,
        "review_required": reviews.get("review_required")
        if isinstance(reviews, dict)
        else None,
        "contract_accepted": (assessment if isinstance(assessment, dict) else {}).get(
            "accepted"
        ),
    }
    for key in ("synthesis_failure", "investigation_failure"):
        failure = investigation.get(key)
        if isinstance(failure, dict) and str(failure.get("kind", "")).startswith(
            "provider"
        ):
            return {**base, "outcome": "provider_error", "failure": failure}
    if report.get("workflow_status") != "complete":
        failure = investigation.get("synthesis_failure") or investigation.get(
            "investigation_failure"
        )
        return {**base, "outcome": "incomplete", "failure": failure}
    claims = [
        item
        for item in investigation.get("verified_claims", [])
        if item["claim"]["operation"] == case.operation
    ]
    if len(claims) != 1:
        return {**base, "outcome": "claim_shape_mismatch"}
    verification = claims[0]["verification"]
    if verification["status"] != "supported" or verification["actual"] is None:
        return {
            **base,
            "outcome": "unsupported_claim",
            "status": verification["status"],
        }
    actual = Decimal(str(verification["actual"]))
    outcome = "correct" if _close(actual, expected, case.integer) else "incorrect"
    return {**base, "outcome": outcome, "actual": str(actual)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument(
        "--out", type=Path, required=True, help="New directory; must not exist."
    )
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--max-steps", type=int, default=3)
    parser.add_argument(
        "--max-seconds",
        type=float,
        default=300.0,
        help="Shared investigation time budget passed to the CLI.",
    )
    parser.add_argument("--pause-seconds", type=float, default=15.0)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()

    if _sha256(args.dataset) != DATASET_SHA256:
        raise SystemExit("Dataset SHA-256 differs from the frozen value; stopped.")
    oracles = preflight(args.dataset)
    if args.preflight_only:
        print("Preflight passed. No model calls were made.")
        return 0

    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "attempts").mkdir()
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=no"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    packages = {}
    for name in ("verisight", "google-genai", "duckdb", "sqlglot", "pandas"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    _write_new(
        args.out / "manifest.json",
        {
            "started_utc": datetime.now(UTC).isoformat(),
            "revision": revision,
            "tracked_changes": bool(dirty),
            "python": sys.version.split()[0],
            "packages": packages,
            "runner_sha256": _sha256(Path(__file__)),
            "dataset_sha256": DATASET_SHA256,
            "repeats": args.repeats,
            "max_steps": args.max_steps,
            "max_seconds": args.max_seconds,
            "pause_seconds": args.pause_seconds,
            "tolerance": str(TOLERANCE),
            "cases": [
                {
                    "case_id": c.case_id,
                    "skill": c.skill,
                    "question": c.question,
                    "operation": c.operation,
                    "trap": c.trap_description,
                    **oracles[c.case_id],
                }
                for c in CASES
            ],
        },
    )

    results = []
    with (args.out / "results.jsonl").open("x", encoding="utf-8", newline="\n") as log:
        for round_number in range(1, args.repeats + 1):
            for case in CASES:
                attempt = (
                    args.out / "attempts" / f"round-{round_number:02d}-{case.case_id}"
                )
                attempt.mkdir()
                report_path = attempt / "report.json"
                command = [
                    sys.executable,
                    "-m",
                    "verisight.cli",
                    "investigate",
                    str(args.dataset),
                    "--question",
                    case.question,
                    "--require-claim",
                    case.operation,
                    "--max-steps",
                    str(args.max_steps),
                    "--max-seconds",
                    str(args.max_seconds),
                    "--allow-llm-data-disclosure",
                    "--output",
                    str(report_path),
                ]
                started = time.perf_counter()
                try:
                    done = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=args.timeout_seconds,
                    )
                    exit_code: int | None = done.returncode
                    (attempt / "stderr.txt").write_text(
                        done.stderr[-20000:], encoding="utf-8"
                    )
                except subprocess.TimeoutExpired:
                    exit_code = None
                elapsed = round(time.perf_counter() - started, 3)
                report = (
                    json.loads(report_path.read_text(encoding="utf-8"))
                    if report_path.exists()
                    else None
                )
                scored = classify(
                    report, case, Decimal(oracles[case.case_id]["expected"])
                )
                record = {
                    "round": round_number,
                    "case_id": case.case_id,
                    "exit_code": exit_code,
                    "elapsed_seconds": elapsed,
                    "expected": oracles[case.case_id]["expected"],
                    **scored,
                    "generation_calls": (
                        report.get("generation_calls") if report else None
                    ),
                }
                if scored.get("actual") is not None and _close(
                    Decimal(str(scored["actual"])),
                    Decimal(oracles[case.case_id]["trap"]),
                    case.integer,
                ):
                    record["matched_trap"] = True
                results.append(record)
                log.write(json.dumps(record) + "\n")
                log.flush()
                print(
                    f"round {round_number} {case.case_id:36s} "
                    f"{record['outcome']:20s} {elapsed:7.1f}s"
                )
                time.sleep(args.pause_seconds)

    summary: dict[str, dict[str, int]] = {}
    for record in results:
        counts = summary.setdefault(record["case_id"], {})
        counts[record["outcome"]] = counts.get(record["outcome"], 0) + 1
        if record.get("matched_trap"):
            counts["matched_trap"] = counts.get("matched_trap", 0) + 1
        if record.get("outcome") == "incorrect" and record.get("review_required"):
            counts["incorrect_flagged_by_review"] = (
                counts.get("incorrect_flagged_by_review", 0) + 1
            )
    totals: dict[str, int] = {}
    for counts in summary.values():
        for key, value in counts.items():
            totals[key] = totals.get(key, 0) + value
    _write_new(
        args.out / "summary.json",
        {
            "finished_utc": datetime.now(UTC).isoformat(),
            "attempts": len(results),
            "totals": totals,
            "by_case": summary,
        },
    )
    print(json.dumps({"attempts": len(results), "totals": totals}, indent=2))
    print("Keep every attempt, including failures. Do not rerun to replace any.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
