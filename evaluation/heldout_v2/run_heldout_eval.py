"""VeriSight held-out evaluation v2: 15 frozen questions on 5 more unseen datasets.

Held-out v1 found bugs that were then fixed, so its questions are no longer
unseen. This set measures the fixed engine on five other public datasets that
played no part in development. Questions and expected answers were committed
before any live run.

    domain          file               format  source
    labour history  jobs.json          JSON    vega-datasets v3.2.0
    economics       income.xlsx        Excel   vega-datasets v3.2.0 (JSON
                                               converted to one worksheet)
    labour market   unemployment.json  JSON    vega-datasets v3.2.0
    weather         weather.csv        CSV     vega-datasets v3.2.0
    medicine        burtin.xlsx        Excel   vega-datasets v3.2.0 (JSON
                                               converted to one worksheet)

Downloads are pinned to an exact commit and checked by SHA-256; each workbook
is checked cell by cell against its JSON source. Expected answers were computed
with Decimal from the source text, independently of pandas, DuckDB and
VeriSight. Each case has a correct control SQL and a plausible trap SQL, and an
offline preflight proves the control reproduces the answer and the trap does
not. Four questions ask for a difference. Two are counting-grain traps:
income.json repeats each state's total on all ten income-group rows, so
counting or summing rows instead of states multiplies the answer by ten.

Questions go through the website's REST API, the path a visitor uses, with the
Gemini key sent per question and never written to output. --base-url runs the
same cases against a deployed server. The manifest records the model.
Every attempt is kept, including failures. Nothing is overwritten.

Usage (PowerShell, from the VeriSight repository root, venv active):
    python evaluation\\heldout_v2\\run_heldout_eval.py --prepare `
        --data-dir F:\\verisight-validation-artifacts\\heldout-v2\\data
    python evaluation\\heldout_v2\\run_heldout_eval.py `
        --data-dir F:\\verisight-validation-artifacts\\heldout-v2\\data `
        --out F:\\verisight-validation-artifacts\\heldout-v2\\run-1-flash-lite
Keep --data-dir and --out outside the repository.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from importlib import metadata
from pathlib import Path
from typing import Any

VEGA = (
    "https://raw.githubusercontent.com/vega/vega-datasets/"
    "7d6cc99bc018ca0fd826b636aea48428f5f237ca/data/"
)


@dataclass(frozen=True)
class Source:
    url: str
    sha256: str
    saved_as: str


SOURCES = (
    Source(
        VEGA + "jobs.json",
        "bc9a798eba79dd166939d040c92641943a0b031955eb6fd897223a9cdab8a7e6",
        "jobs.json",
    ),
    Source(
        VEGA + "income.json",
        "c04ac5db8f263ccfe43250fce2c4e808e362d5ccf6c5b904f029bc2b1ae5d260",
        "income_source.json",
    ),
    Source(
        VEGA + "unemployment-across-industries.json",
        "c12e32b5b8bf66d5ce40081a22b5557b2a8649dbdcbe03028b3df65cd66257a1",
        "unemployment.json",
    ),
    Source(
        VEGA + "weather.csv",
        "27219f1ca8dbd94c9b6f4b9f4f52ab2f1eb33dfdcf719cd9fc6481ed50b74549",
        "weather.csv",
    ),
    Source(
        VEGA + "burtin.json",
        "443a3c2dc37f86dc26259e5ab1b4719180ccc811260f390b15518f05bbbbaf24",
        "burtin_source.json",
    ),
)
# Workbooks built from JSON sources: name -> (source, columns in order).
WORKBOOKS = {
    "income": (
        "income_source.json",
        ("name", "region", "id", "pct", "total", "group"),
    ),
    "burtin": (
        "burtin_source.json",
        (
            "Bacteria",
            "Penicillin",
            "Streptomycin",
            "Neomycin",
            "Gram_Staining",
            "Genus",
        ),
    ),
}
DATASETS = (
    "jobs.json",
    "income.xlsx",
    "unemployment.json",
    "weather.csv",
    "burtin.xlsx",
)


@dataclass(frozen=True)
class Case:
    case_id: str
    file: str
    question: str
    answer_type: str  # "number" (one value claim) or "difference"
    expected: Decimal
    tolerance: Decimal
    control_sql: str
    trap_sql: str
    trap: str

    @property
    def operation(self) -> str:
        return "value" if self.answer_type == "number" else "difference"


EXACT = Decimal("0")
TWO_PLACES = Decimal("0.005")
FINE = Decimal("0.0005")

CASES = (
    Case(
        "jobs_women_accountants_1950",
        "jobs.json",
        "How many women worked as Accountant / Auditor in 1950?",
        "number",
        Decimal("56117"),
        EXACT,
        """SELECT count FROM jobs
        WHERE job = 'Accountant / Auditor' AND sex = 'women' AND year = 1950""",
        """SELECT SUM(count) FROM jobs
        WHERE job = 'Accountant / Auditor' AND year = 1950""",
        "adds men and women",
    ),
    Case(
        "jobs_nurse_women_minus_men_2000",
        "jobs.json",
        "In 2000, how many more women than men worked as a Nurse? Give women "
        "minus men.",
        "difference",
        Decimal("3101819"),
        EXACT,
        """SELECT SUM(count) FILTER (WHERE sex = 'women')
             - SUM(count) FILTER (WHERE sex = 'men')
        FROM jobs WHERE job = 'Nurse' AND year = 2000""",
        """SELECT SUM(count) FILTER (WHERE sex = 'men')
             - SUM(count) FILTER (WHERE sex = 'women')
        FROM jobs WHERE job = 'Nurse' AND year = 2000""",
        "subtracts in the wrong order",
    ),
    Case(
        "jobs_distinct_jobs",
        "jobs.json",
        "How many different jobs are listed in the data?",
        "number",
        Decimal("255"),
        EXACT,
        "SELECT COUNT(DISTINCT job) FROM jobs",
        "SELECT COUNT(job) FROM jobs",
        "counts rows instead of jobs",
    ),
    Case(
        "income_midwest_states",
        "income.xlsx",
        "How many states are in the midwest region?",
        "number",
        Decimal("12"),
        EXACT,
        "SELECT COUNT(DISTINCT name) FROM income WHERE region = 'midwest'",
        "SELECT COUNT(*) FROM income WHERE region = 'midwest'",
        "counts the ten income-group rows of each state",
    ),
    Case(
        "income_northeast_total",
        "income.xlsx",
        "What is the combined total of the states in the northeast region, "
        "counting each state's total once?",
        "number",
        Decimal("20954909"),
        EXACT,
        """SELECT SUM(total) FROM (
            SELECT DISTINCT name, total FROM income WHERE region = 'northeast'
        )""",
        "SELECT SUM(total) FROM income WHERE region = 'northeast'",
        "sums the total repeated on every income-group row",
    ),
    Case(
        "income_texas_top_group",
        "income.xlsx",
        "For Texas, what is the pct value of the 200000+ income group?",
        "number",
        Decimal("0.048"),
        FINE,
        """SELECT pct FROM income WHERE name = 'Texas' AND "group" = '200000+'""",
        "SELECT AVG(pct) FROM income WHERE name = 'Texas'",
        "averages every income group",
    ),
    Case(
        "unemployment_construction_rate_2009",
        "unemployment.json",
        "What was the average unemployment rate in Construction in 2009?",
        "number",
        Decimal("19.05"),
        TWO_PLACES,
        """SELECT AVG(rate) FROM unemployment
        WHERE series = 'Construction' AND year = 2009""",
        "SELECT AVG(rate) FROM unemployment WHERE year = 2009",
        "averages every industry",
    ),
    Case(
        "unemployment_construction_2010_minus_2000",
        "unemployment.json",
        "How much higher was the Construction unemployment count in January "
        "2010 than in January 2000? Give 2010 minus 2000.",
        "difference",
        Decimal("1449"),
        EXACT,
        """SELECT SUM(count) FILTER (WHERE year = 2010)
             - SUM(count) FILTER (WHERE year = 2000)
        FROM unemployment WHERE series = 'Construction' AND month = 1""",
        """SELECT SUM(count) FILTER (WHERE year = 2000)
             - SUM(count) FILTER (WHERE year = 2010)
        FROM unemployment WHERE series = 'Construction' AND month = 1""",
        "subtracts in the wrong order",
    ),
    Case(
        "unemployment_finance_max_count",
        "unemployment.json",
        "What was the highest monthly unemployment count for the Finance series?",
        "number",
        Decimal("708"),
        EXACT,
        "SELECT MAX(count) FROM unemployment WHERE series = 'Finance'",
        "SELECT MAX(count) FROM unemployment",
        "takes the maximum over every industry",
    ),
    Case(
        "weather_seattle_rain_days_2014",
        "weather.csv",
        "On how many days in 2014 was the weather recorded as rain in Seattle?",
        "number",
        Decimal("148"),
        EXACT,
        """SELECT COUNT(*) FROM weather
        WHERE location = 'Seattle' AND weather = 'rain' AND YEAR("date") = 2014""",
        """SELECT COUNT(*) FROM weather
        WHERE weather = 'rain' AND YEAR("date") = 2014""",
        "counts both cities",
    ),
    Case(
        "weather_ny_minus_seattle_precip_2013",
        "weather.csv",
        "In 2013, how much more total precipitation did New York get than "
        "Seattle? Give New York minus Seattle.",
        "difference",
        Decimal("74.7"),
        TWO_PLACES,
        """SELECT SUM(precipitation) FILTER (WHERE location = 'New York')
             - SUM(precipitation) FILTER (WHERE location = 'Seattle')
        FROM weather WHERE YEAR("date") = 2013""",
        """SELECT SUM(precipitation) FILTER (WHERE location = 'Seattle')
             - SUM(precipitation) FILTER (WHERE location = 'New York')
        FROM weather WHERE YEAR("date") = 2013""",
        "subtracts in the wrong order",
    ),
    Case(
        "weather_ny_july_2015_temp_max",
        "weather.csv",
        "What was the average daily temp_max in New York in July 2015?",
        "number",
        Decimal("29.57741935483870967741935484"),
        TWO_PLACES,
        """SELECT AVG(temp_max) FROM weather
        WHERE location = 'New York' AND YEAR("date") = 2015
          AND MONTH("date") = 7""",
        """SELECT AVG(temp_max) FROM weather
        WHERE YEAR("date") = 2015 AND MONTH("date") = 7""",
        "averages both cities",
    ),
    Case(
        "burtin_gram_negative_count",
        "burtin.xlsx",
        "How many bacteria in the table are gram-negative?",
        "number",
        Decimal("9"),
        EXACT,
        "SELECT COUNT(*) FROM burtin WHERE Gram_Staining = 'negative'",
        "SELECT COUNT(*) FROM burtin",
        "counts every bacterium",
    ),
    Case(
        "burtin_positive_penicillin_mean",
        "burtin.xlsx",
        "What is the average Penicillin value of the gram-positive bacteria?",
        "number",
        Decimal("0.1498571428571428571428571429"),
        FINE,
        "SELECT AVG(Penicillin) FROM burtin WHERE Gram_Staining = 'positive'",
        "SELECT AVG(Penicillin) FROM burtin",
        "averages every bacterium",
    ),
    Case(
        "burtin_ecoli_penicillin_minus_streptomycin",
        "burtin.xlsx",
        "For Escherichia coli, how much larger is the Penicillin value than the "
        "Streptomycin value? Give Penicillin minus Streptomycin.",
        "difference",
        Decimal("99.6"),
        TWO_PLACES,
        """SELECT Penicillin - Streptomycin FROM burtin
        WHERE Bacteria = 'Escherichia coli'""",
        """SELECT Streptomycin - Penicillin FROM burtin
        WHERE Bacteria = 'Escherichia coli'""",
        "subtracts in the wrong order",
    ),
)


# ---- data ---------------------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _workbook_rows(data_dir: Path, name: str) -> list[list[Any]]:
    """Rows of one workbook, in source order, header first."""
    source, columns = WORKBOOKS[name]
    records = json.loads((data_dir / source).read_text("utf-8"))
    return [list(columns)] + [[record[c] for c in columns] for record in records]


def prepare(data_dir: Path) -> None:
    """Download each pinned file, check its hash, and build the workbooks."""
    from openpyxl import Workbook

    data_dir.mkdir(parents=True, exist_ok=True)
    for source in SOURCES:
        target = data_dir / source.saved_as
        if not target.exists():
            with urllib.request.urlopen(source.url, timeout=60) as response:
                target.write_bytes(response.read())
            print(f"downloaded    {source.saved_as}")
    check_sources(data_dir)
    for name in WORKBOOKS:
        workbook = Workbook()
        sheet = workbook.active
        assert sheet is not None
        sheet.title = name
        for row in _workbook_rows(data_dir, name):
            sheet.append(row)
        workbook.save(data_dir / f"{name}.xlsx")
        print(f"built         {name}.xlsx")


def check_sources(data_dir: Path) -> None:
    for source in SOURCES:
        path = data_dir / source.saved_as
        if not path.exists() or _sha256(path) != source.sha256:
            raise SystemExit(
                f"{source.saved_as} is missing or differs from the pinned file. "
                "Delete it and run --prepare again."
            )
        print(f"sha256 ok     {source.saved_as}")


def check_workbook(data_dir: Path) -> None:
    """Workbooks carry timestamps, so compare their cells with the sources."""
    from openpyxl import load_workbook

    for name in WORKBOOKS:
        workbook = load_workbook(data_dir / f"{name}.xlsx", read_only=True)
        try:
            cells = [list(row) for row in workbook[name].iter_rows(values_only=True)]
        finally:
            workbook.close()
        if cells != _workbook_rows(data_dir, name):
            raise SystemExit(f"{name}.xlsx does not match its JSON source.")
        print(f"fidelity ok   {name}.xlsx")


def _close(actual: Decimal, case: Case) -> bool:
    return abs(actual - case.expected) <= case.tolerance


def preflight(data_dir: Path) -> dict[str, dict[str, str]]:
    """Prove the files load correctly and every case discriminates, offline."""
    from verisight import VeriSight
    from verisight.config import Settings

    check_sources(data_dir)
    check_workbook(data_dir)
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False, gemini_api_key=None)
    )
    oracles: dict[str, dict[str, str]] = {}
    for case in CASES:
        path = data_dir / case.file
        control = Decimal(str(app.execute(path, case.control_sql).rows[0][0]))
        trap = Decimal(str(app.execute(path, case.trap_sql).rows[0][0]))
        if not _close(control, case):
            raise SystemExit(
                f"{case.case_id}: control {control} != expected {case.expected}"
            )
        if _close(trap, case):
            raise SystemExit(f"{case.case_id}: trap {trap} is not distinguishable")
        oracles[case.case_id] = {
            "expected": str(case.expected),
            "control": str(control),
            "trap": str(trap),
        }
        print(
            f"preflight ok  {case.case_id:30s} "
            f"expected={float(case.expected):,.4f}  trap={float(trap):,.4f}"
        )
    return oracles


# ---- live run and scoring --------------------------------------------------------


def classify(status: int, body: dict[str, Any], case: Case) -> dict[str, Any]:
    """Score one API answer. Only the SQL evidence cell is compared, never prose.

    Correct and incorrect require an answer the website showed as verified and
    accepted; a matching cell in a rejected answer is reported as not_accepted.
    """
    if status != 200:
        code = body.get("code") if isinstance(body, dict) else None
        if code in {"provider_unavailable", "busy", "rate_limited"}:
            return {"outcome": "provider_error", "http_status": status, "code": code}
        return {"outcome": "application_error", "http_status": status, "code": code}
    assessment = body.get("assessment")
    base: dict[str, Any] = {
        "web_outcome": body.get("outcome"),
        "accepted": body.get("outcome") == "verified"
        and isinstance(assessment, dict)
        and assessment.get("accepted") is True,
        "sql": [step.get("sql") for step in body.get("steps", [])],
        "review_required": body.get("review_required"),
        "recovery_used": bool(body.get("recovery")),
    }
    failure = body.get("failure")
    if isinstance(failure, dict) and str(failure.get("kind", "")).startswith(
        "provider"
    ):
        return {**base, "outcome": "provider_error", "failure": failure}
    if body.get("status") != "complete":
        return {**base, "outcome": "incomplete", "failure": failure}
    claims = [
        item
        for item in body.get("claims", [])
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
    matches = _close(actual, case)
    scored = {**base, "numeric_match": matches, "actual": str(actual)}
    if not base["accepted"]:
        # A matching cell inside a rejected answer is not an answer users get.
        return {**scored, "outcome": "not_accepted"}
    return {**scored, "outcome": "correct" if matches else "incorrect"}


def _client(base_url: str | None) -> Any:
    if base_url:
        import httpx

        return httpx.Client(base_url=base_url.rstrip("/"), timeout=900.0)
    from fastapi.testclient import TestClient

    from verisight.config import Settings
    from verisight.web import create_app
    from verisight.web.config import WebSettings

    # No server key: the key travels with each question, as on the website.
    app = create_app(
        settings=Settings(gemini_api_key=None),
        web=WebSettings(questions_per_hour=10_000, uploads_per_hour=10_000),
    )
    return TestClient(app)


def _api_key() -> str:
    from verisight.config import Settings

    key = (Settings().gemini_api_key or "").strip()
    if not key:
        raise SystemExit(
            "Set VERISIGHT_GEMINI_API_KEY (or add it to .env) before a live run."
        )
    return key


def _model() -> str:
    from verisight.config import Settings

    return Settings().gemini_model


def _write_new(path: Path, payload: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, default=str)
        handle.write("\n")


def _git(*args: str) -> str:
    done = subprocess.run(["git", *args], capture_output=True, text=True)
    return done.stdout.strip()


def ask_once(
    client: Any, data_dir: Path, case: Case, key: str
) -> tuple[int, dict[str, Any], float]:
    """Upload the file, ask the question, then delete the upload."""
    path = data_dir / case.file
    with path.open("rb") as handle:
        upload = client.post(
            "/api/datasets", files=[("files", (case.file, handle.read()))]
        )
    if upload.status_code != 201:
        return upload.status_code, {"upload_error": upload.json()}, 0.0
    dataset_id = upload.json()["dataset_id"]
    started = time.perf_counter()
    try:
        answer = client.post(
            f"/api/datasets/{dataset_id}/ask",
            json={
                "question": case.question,
                "answer_type": case.answer_type,
                "consent": True,
                "api_key": key,
            },
        )
    finally:
        elapsed = round(time.perf_counter() - started, 3)
        client.delete(f"/api/datasets/{dataset_id}")
    return answer.status_code, answer.json(), elapsed


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--out", type=Path, help="New directory; must not exist.")
    parser.add_argument("--base-url", help="Test a running server instead.")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--pause-seconds", type=float, default=30.0)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    if args.prepare:
        prepare(args.data_dir)
    oracles = preflight(args.data_dir)
    if args.preflight_only or args.out is None:
        print("Preflight passed. No model calls were made.")
        return 0
    key = _api_key()
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / "attempts").mkdir()
    packages: dict[str, str | None] = {}
    for name in ("verisight", "google-genai", "duckdb", "sqlglot", "pandas"):
        try:
            packages[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            packages[name] = None
    _write_new(
        args.out / "manifest.json",
        {
            "started_utc": datetime.now(UTC).isoformat(),
            "evaluation": "heldout-v2",
            "model": _model(),
            "revision": _git("rev-parse", "HEAD"),
            "tracked_changes": bool(
                _git("status", "--porcelain", "--untracked-files=no")
            ),
            "target": args.base_url or "in-process app",
            "python": sys.version.split()[0],
            "packages": packages,
            "runner_sha256": _sha256(Path(__file__)),
            "files": {name: _sha256(args.data_dir / name) for name in DATASETS},
            "repeats": args.repeats,
            "pause_seconds": args.pause_seconds,
            "cases": [
                {
                    "case_id": case.case_id,
                    "file": case.file,
                    "question": case.question,
                    "answer_type": case.answer_type,
                    "tolerance": str(case.tolerance),
                    "trap": case.trap,
                    **oracles[case.case_id],
                }
                for case in CASES
            ],
        },
    )
    results = []
    with (
        _client(args.base_url) as client,
        (args.out / "results.jsonl").open("x", encoding="utf-8", newline="\n") as log,
    ):
        for round_number in range(1, args.repeats + 1):
            for case in CASES:
                attempt = (
                    args.out / "attempts" / f"round-{round_number:02d}-{case.case_id}"
                )
                attempt.mkdir()
                status, body, elapsed = ask_once(client, args.data_dir, case, key)
                _write_new(attempt / "response.json", body)
                scored = classify(status, body, case)
                record = {
                    "round": round_number,
                    "case_id": case.case_id,
                    "file": case.file,
                    "elapsed_seconds": elapsed,
                    "expected": str(case.expected),
                    **scored,
                    "model_calls": body.get("model_calls"),
                }
                if (
                    scored.get("actual") is not None
                    and abs(
                        Decimal(scored["actual"])
                        - Decimal(oracles[case.case_id]["trap"])
                    )
                    <= case.tolerance
                ):
                    record["matched_trap"] = True
                results.append(record)
                log.write(json.dumps(record, default=str) + "\n")
                log.flush()
                print(
                    f"round {round_number} {case.case_id:30s} "
                    f"{record['outcome']:20s} {elapsed:7.1f}s"
                )
                time.sleep(args.pause_seconds)
    by_case: dict[str, dict[str, int]] = {}
    totals: dict[str, int] = {}
    for record in results:
        counts = by_case.setdefault(str(record["case_id"]), {})
        keys = [str(record["outcome"])]
        if record.get("matched_trap"):
            keys.append("matched_trap")
        if record.get("recovery_used"):
            keys.append("recovery_used")
        for name in keys:
            counts[name] = counts.get(name, 0) + 1
            totals[name] = totals.get(name, 0) + 1
    _write_new(
        args.out / "summary.json",
        {
            "finished_utc": datetime.now(UTC).isoformat(),
            "attempts": len(results),
            "totals": totals,
            "by_case": by_case,
        },
    )
    print(json.dumps({"attempts": len(results), "totals": totals}, indent=2))
    print("Keep every attempt, including failures. Do not rerun to replace any.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
