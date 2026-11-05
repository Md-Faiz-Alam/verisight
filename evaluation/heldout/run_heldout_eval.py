"""VeriSight held-out evaluation: 15 frozen questions on 5 unseen public datasets.

None of these files was used while building or tuning VeriSight. The questions
and their expected answers were written and committed before any live run, so
the commit history shows they were not adjusted to fit results.

    domain          file                    format  source
    entertainment   movies.json             JSON    vega-datasets v3.2.0
    humanitarian    disasters.csv           CSV     vega-datasets v3.2.0
    agriculture     barley.xlsx             Excel   vega-datasets v3.2.0 (JSON
                                                    converted to one worksheet)
    climate         co2_concentration.csv   CSV     vega-datasets v3.2.0
    machine         glue.csv                CSV     seaborn-data (pinned commit)
    learning

Downloads are pinned to exact commits and checked by SHA-256. Expected answers
were computed with Decimal from the downloaded source text, not with pandas,
DuckDB or VeriSight. Each case also has a correct control SQL and a plausible
trap SQL; offline preflight proves, before any model call, that VeriSight's
loader and executor reproduce the expected answer with the control and that
the trap gives a different one.

One case is a deliberate semantic trap: disasters.csv holds an "All natural
disasters" row per year next to the individual disaster types, so summing
every row for a year double counts. Verification can prove a number came from
the SQL result; only the SQL shows whether it was the right total.

Questions go through the website's REST API, the same path a visitor uses:
upload, then POST /api/datasets/{id}/ask with consent and a Gemini key, then
DELETE. By default the app runs in this process; --base-url sends the same
requests to a running server, such as the AWS deployment. The key comes from
VERISIGHT_GEMINI_API_KEY (or your .env), is sent only with each question, and
is never written to any output.

Every attempt is kept, including failures. Nothing is overwritten.

Usage (PowerShell, from the VeriSight repository root, venv active):
    python evaluation\\heldout\\run_heldout_eval.py --prepare `
        --data-dir F:\\verisight-validation-artifacts\\heldout\\data
    python evaluation\\heldout\\run_heldout_eval.py `
        --data-dir F:\\verisight-validation-artifacts\\heldout\\data `
        --out F:\\verisight-validation-artifacts\\heldout\\run-1
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
SEABORN = (
    "https://raw.githubusercontent.com/mwaskom/seaborn-data/"
    "71e2436a092d714350de0fc409ca8a8714e7e78f/"
)


@dataclass(frozen=True)
class Source:
    url: str
    sha256: str
    saved_as: str


SOURCES = (
    Source(
        VEGA + "movies.json",
        "e63c499759e3b07b49563e036f55290f87feb56def8703ec049ca305ab1523d3",
        "movies.json",
    ),
    Source(
        VEGA + "disasters.csv",
        "36d151b50da0aeb82e86b152f91b8cf912a0e4cb50fe32744cf33f22463847d9",
        "disasters.csv",
    ),
    Source(
        VEGA + "barley.json",
        "800faf5a0524e2145822a72af7821e153b80ad3433631f4bd30100b24c9fa2bc",
        "barley_source.json",
    ),
    Source(
        VEGA + "co2-concentration.csv",
        "c1a4a970864145940a28225cae288618b156cb32f9a2a1b6606ba7124134febb",
        "co2_concentration.csv",
    ),
    Source(
        SEABORN + "glue.csv",
        "0c6b840da0a2c7fba3422d3b6867492bc8e61dd99dec7a276f6108774c81744e",
        "glue.csv",
    ),
)
DATASETS = (
    "movies.json",
    "disasters.csv",
    "barley.xlsx",
    "co2_concentration.csv",
    "glue.csv",
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
# The adjusted series differs by only 0.0017 here, so allow float noise only.
FINE = Decimal("0.0005")

CASES = (
    Case(
        "movies_comedy_count",
        "movies.json",
        "How many movies have Comedy as their Major Genre? Count only the genre "
        "named exactly Comedy.",
        "number",
        Decimal("675"),
        EXACT,
        """SELECT COUNT(*) FROM movies WHERE "Major Genre" = 'Comedy'""",
        """SELECT COUNT(*) FROM movies WHERE "Major Genre" LIKE '%Comedy%'""",
        "includes Romantic Comedy and Black Comedy",
    ),
    Case(
        "movies_spielberg_imdb",
        "movies.json",
        "What is the average IMDB Rating of the movies directed by Steven "
        "Spielberg? Ignore movies that have no rating.",
        "number",
        Decimal("7.35"),
        TWO_PLACES,
        """SELECT AVG("IMDB Rating") FROM movies
        WHERE Director = 'Steven Spielberg'""",
        """SELECT AVG(COALESCE("IMDB Rating", 0)) FROM movies
        WHERE Director = 'Steven Spielberg'""",
        "counts the unrated movie as 0",
    ),
    Case(
        "movies_pg13_worldwide_gross",
        "movies.json",
        "What is the total Worldwide Gross of all movies with an MPAA Rating of PG-13?",
        "number",
        Decimal("112506971270"),
        EXACT,
        """SELECT SUM("Worldwide Gross") FROM movies
        WHERE "MPAA Rating" = 'PG-13'""",
        """SELECT SUM("US Gross") FROM movies WHERE "MPAA Rating" = 'PG-13'""",
        "uses US Gross",
    ),
    Case(
        "disasters_2010_total",
        "disasters.csv",
        "How many people died in natural disasters in 2010 in total?",
        "number",
        Decimal("329900"),
        EXACT,
        """SELECT Deaths FROM disasters
        WHERE Year = 2010 AND Entity = 'All natural disasters'""",
        "SELECT SUM(Deaths) FROM disasters WHERE Year = 2010",
        "adds the All natural disasters row to its own parts (double count)",
    ),
    Case(
        "disasters_earthquake_total",
        "disasters.csv",
        "What is the total number of deaths from earthquakes over all years in "
        "the table?",
        "number",
        Decimal("2576801"),
        EXACT,
        "SELECT SUM(Deaths) FROM disasters WHERE Entity = 'Earthquake'",
        """SELECT SUM(Deaths) FROM disasters
        WHERE Entity IN ('Earthquake', 'Volcanic activity')""",
        "adds volcanic activity",
    ),
    Case(
        "disasters_drought_minus_flood",
        "disasters.csv",
        "Over all years, how many more people died from drought than from "
        "floods? Give drought deaths minus flood deaths.",
        "difference",
        Decimal("4776302"),
        EXACT,
        """SELECT SUM(Deaths) FILTER (WHERE Entity = 'Drought')
             - SUM(Deaths) FILTER (WHERE Entity = 'Flood') FROM disasters""",
        """SELECT SUM(Deaths) FILTER (WHERE Entity = 'Flood')
             - SUM(Deaths) FILTER (WHERE Entity = 'Drought') FROM disasters""",
        "subtracts in the wrong order",
    ),
    Case(
        "barley_waseca_1931_mean",
        "barley.xlsx",
        "What was the average barley yield at the Waseca site in 1931?",
        "number",
        Decimal("54.346666"),
        TWO_PLACES,
        """SELECT AVG(yield) FROM barley WHERE site = 'Waseca' AND year = 1931""",
        "SELECT AVG(yield) FROM barley WHERE site = 'Waseca'",
        "averages both years",
    ),
    Case(
        "barley_1931_minus_1932",
        "barley.xlsx",
        "How much higher was the total barley yield in 1931 than in 1932? Give "
        "the 1931 total minus the 1932 total.",
        "difference",
        Decimal("318.86672"),
        TWO_PLACES,
        """SELECT SUM(yield) FILTER (WHERE year = 1931)
             - SUM(yield) FILTER (WHERE year = 1932) FROM barley""",
        """SELECT SUM(yield) FILTER (WHERE year = 1932)
             - SUM(yield) FILTER (WHERE year = 1931) FROM barley""",
        "subtracts in the wrong order",
    ),
    Case(
        "barley_variety_count",
        "barley.xlsx",
        "How many different barley varieties are in the data?",
        "number",
        Decimal("10"),
        EXACT,
        "SELECT COUNT(DISTINCT variety) FROM barley",
        "SELECT COUNT(variety) FROM barley",
        "counts rows instead of varieties",
    ),
    Case(
        "co2_max_1990",
        "co2_concentration.csv",
        "What was the highest monthly CO2 reading in 1990? Use the CO2 column, "
        "not the adjusted CO2.",
        "number",
        Decimal("357.16"),
        EXACT,
        """SELECT MAX(CO2) FROM co2_concentration WHERE YEAR("Date") = 1990""",
        """SELECT MAX("adjusted CO2") FROM co2_concentration
        WHERE YEAR("Date") = 1990""",
        "uses adjusted CO2",
    ),
    Case(
        "co2_2018_minus_1959",
        "co2_concentration.csv",
        "By how much did the average CO2 reading rise from 1959 to 2018? Give "
        "the 2018 average minus the 1959 average, using the CO2 column, not the "
        "adjusted CO2.",
        "difference",
        Decimal("92.6058333333333333333333333"),
        FINE,
        """SELECT AVG(CO2) FILTER (WHERE YEAR("Date") = 2018)
             - AVG(CO2) FILTER (WHERE YEAR("Date") = 1959)
        FROM co2_concentration""",
        """SELECT AVG("adjusted CO2") FILTER (WHERE YEAR("Date") = 2018)
             - AVG("adjusted CO2") FILTER (WHERE YEAR("Date") = 1959)
        FROM co2_concentration""",
        "uses adjusted CO2",
    ),
    Case(
        "co2_months_above_400",
        "co2_concentration.csv",
        "In how many months was the CO2 reading above 400? Use the CO2 column, "
        "not the adjusted CO2.",
        "number",
        Decimal("63"),
        EXACT,
        "SELECT COUNT(*) FROM co2_concentration WHERE CO2 > 400",
        """SELECT COUNT(*) FROM co2_concentration WHERE "adjusted CO2" > 400""",
        "uses adjusted CO2",
    ),
    Case(
        "glue_bert_mean",
        "glue.csv",
        "What is BERT's average score across all GLUE tasks in the table?",
        "number",
        Decimal("81.7375"),
        TWO_PLACES,
        "SELECT AVG(Score) FROM glue WHERE Model = 'BERT'",
        "SELECT AVG(Score) FROM glue",
        "averages every model",
    ),
    Case(
        "glue_roberta_minus_bert_mnli",
        "glue.csv",
        "On the MNLI task, how many points higher did RoBERTa score than BERT? "
        "Give RoBERTa's score minus BERT's score.",
        "difference",
        Decimal("4.1"),
        TWO_PLACES,
        """SELECT MAX(Score) FILTER (WHERE Model = 'RoBERTa')
             - MAX(Score) FILTER (WHERE Model = 'BERT')
        FROM glue WHERE Task = 'MNLI'""",
        """SELECT MAX(Score) FILTER (WHERE Model = 'BERT')
             - MAX(Score) FILTER (WHERE Model = 'RoBERTa')
        FROM glue WHERE Task = 'MNLI'""",
        "subtracts in the wrong order",
    ),
    Case(
        "glue_lstm_model_count",
        "glue.csv",
        "How many different models in the table use an LSTM encoder?",
        "number",
        Decimal("4"),
        EXACT,
        "SELECT COUNT(DISTINCT Model) FROM glue WHERE Encoder = 'LSTM'",
        "SELECT COUNT(*) FROM glue WHERE Encoder = 'LSTM'",
        "counts rows instead of models",
    ),
)


# ---- data ---------------------------------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _barley_rows(data_dir: Path) -> list[list[Any]]:
    """Rows of the barley workbook, in source order, header first."""
    records = json.loads((data_dir / "barley_source.json").read_text("utf-8"))
    columns = ["yield", "variety", "year", "site"]
    return [columns] + [[record[name] for name in columns] for record in records]


def prepare(data_dir: Path) -> None:
    """Download each pinned file, check its hash, and build barley.xlsx."""
    from openpyxl import Workbook

    data_dir.mkdir(parents=True, exist_ok=True)
    for source in SOURCES:
        target = data_dir / source.saved_as
        if not target.exists():
            with urllib.request.urlopen(source.url, timeout=60) as response:
                target.write_bytes(response.read())
            print(f"downloaded    {source.saved_as}")
    check_sources(data_dir)
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = "barley"
    for row in _barley_rows(data_dir):
        sheet.append(row)
    workbook.save(data_dir / "barley.xlsx")
    print("built         barley.xlsx")


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
    """The .xlsx carries timestamps, so compare its cells with the source."""
    from openpyxl import load_workbook

    workbook = load_workbook(data_dir / "barley.xlsx", read_only=True)
    try:
        sheet = workbook["barley"]
        cells = [list(row) for row in sheet.iter_rows(values_only=True)]
    finally:
        workbook.close()
    if cells != _barley_rows(data_dir):
        raise SystemExit("barley.xlsx does not match barley_source.json.")
    print("fidelity ok   barley.xlsx")


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
            "evaluation": "heldout-v1",
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
