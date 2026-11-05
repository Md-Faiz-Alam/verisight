"""Multi-domain VeriSight evaluation on three public datasets in three formats.

Domains and formats (sources pinned to one seaborn-data commit):
    transport  NYC taxi trips   -> JSON  (missing values as null)
    ecology    Palmer penguins  -> XLSX  (missing values as empty cells)
    retail     diamonds         -> CSV   (unchanged)

Expected answers are computed here from the ORIGINAL source CSV files with the
csv module and Decimal, independent of the converted files, pandas, DuckDB
and VeriSight. Each case also has a correct control SQL and a plausible trap
SQL. Offline preflight proves, before any model call, that each converted file
holds exactly the source values, that the control reproduces the answer
through VeriSight's executor, and that the trap gives a different answer.

The questions were written and frozen before any live run. VeriSight's
production code contains nothing specific to these datasets.

Every attempt is kept, including failures. Nothing is overwritten.

Usage (PowerShell, from the VeriSight repository root, venv active):
    python evaluation\\multidomain\\run_multidomain_eval.py --prepare `
        --data-dir datasets\\multidomain
    python evaluation\\multidomain\\run_multidomain_eval.py `
        --data-dir datasets\\multidomain `
        --out F:\\verisight-validation-artifacts\\multidomain-eval-v1\\run-1 `
        --preflight-only
Keep --out outside the repository so results are never committed by accident.
"""

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from importlib import metadata
from pathlib import Path

SOURCE_COMMIT = "71e2436a092d714350de0fc409ca8a8714e7e78f"
SOURCE_URL = (
    "https://raw.githubusercontent.com/mwaskom/seaborn-data/{commit}/{name}.csv"
)
TOLERANCE = Decimal("0.005")
Row = dict[str, str]


@dataclass(frozen=True)
class Dataset:
    name: str
    domain: str
    source_sha256: str
    rows: int
    file_name: str


DATASETS = {
    "taxis": Dataset(
        "taxis",
        "transport",
        "08d6d71784dbaa2651fee37fc03389754194c05d72d2d19cbc2c799dea6ac09d",
        6433,
        "taxis.json",
    ),
    "penguins": Dataset(
        "penguins",
        "ecology",
        "e07636bd8af74260099ea2f8678e2eabbf35def579940cc76f67061ee16c06c1",
        344,
        "penguins.xlsx",
    ),
    "diamonds": Dataset(
        "diamonds",
        "retail",
        "9574730b03aba241d899c4a97511c5061b19358fab89510774fb6c24168345c4",
        53940,
        "diamonds.csv",
    ),
}
TEXT_COLUMNS = {"pickup", "dropoff"}


def _value(text: str) -> int | float | str | None:
    """Typed value for converted files; empty source cells become missing."""
    if text in ("", "NA"):
        return None
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        return text


def _missing(text: str) -> bool:
    return text in ("", "NA")


def _num(text: str) -> Decimal:
    return Decimal(text)


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / len(values)


def _median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def _pct(rows: list[Row], numerator: Callable[[Row], bool]) -> Decimal:
    return Decimal(100) * sum(1 for row in rows if numerator(row)) / len(rows)


def _where(rows: list[Row], keep: Callable[[Row], bool]) -> list[Row]:
    return [row for row in rows if keep(row)]


def _column(rows: list[Row], name: str) -> list[Decimal]:
    return [_num(row[name]) for row in rows if not _missing(row[name])]


@dataclass(frozen=True)
class Case:
    case_id: str
    dataset: str
    skill: str
    question: str
    operation: str
    oracle: Callable[[list[Row]], Decimal]
    control_sql: str
    trap_sql: str
    trap_description: str
    integer: bool = False


def _fare(rows: list[Row], color: str) -> Decimal:
    return _mean(_column(_where(rows, lambda row: row["color"] == color), "fare"))


def _flipper(rows: list[Row], species: str) -> Decimal:
    chosen = _where(rows, lambda row: row["species"] == species)
    return _mean(_column(chosen, "flipper_length_mm"))


def _known_boroughs(row: Row) -> bool:
    return not _missing(row["pickup_borough"]) and not _missing(row["dropoff_borough"])


CROSS = "SUM(CASE WHEN pickup_borough <> dropoff_borough THEN 1 ELSE 0 END)"
FARE = "SELECT AVG(fare) AS v FROM taxis WHERE color = '{}'"
FLIP = "SELECT AVG(flipper_length_mm) AS v FROM penguins WHERE species = '{}'"
CASES = (
    Case(
        "taxi_credit_card_mean_tip",
        "taxis",
        "population: payment subset",
        "Among taxi trips paid by credit card, what is the mean tip? Report it as "
        "a single number.",
        "value",
        lambda rows: _mean(
            _column(_where(rows, lambda row: row["payment"] == "credit card"), "tip")
        ),
        "SELECT AVG(tip) AS v FROM taxis WHERE payment = 'credit card'",
        "SELECT AVG(tip) AS v FROM taxis",
        "averages tips over all trips, including cash trips",
    ),
    Case(
        "taxi_missing_payment_count",
        "taxis",
        "missing values: null count",
        "How many taxi trips have no recorded payment method? Report the count as "
        "a single number.",
        "value",
        lambda rows: Decimal(sum(1 for row in rows if _missing(row["payment"]))),
        "SELECT COUNT(*) AS v FROM taxis WHERE payment IS NULL",
        "SELECT COUNT(*) AS v FROM taxis WHERE payment NOT IN ('cash', 'credit card')",
        "NOT IN never matches null, so missing payments are not counted",
        integer=True,
    ),
    Case(
        "taxi_brooklyn_green_median_distance",
        "taxis",
        "population: two filters, median",
        "What is the median trip distance of green taxi trips picked up in "
        "Brooklyn? Report it as a single number.",
        "value",
        lambda rows: _median(
            _column(
                _where(
                    rows,
                    lambda row: (
                        row["color"] == "green" and row["pickup_borough"] == "Brooklyn"
                    ),
                ),
                "distance",
            )
        ),
        "SELECT MEDIAN(distance) AS v FROM taxis "
        "WHERE color = 'green' AND pickup_borough = 'Brooklyn'",
        "SELECT MEDIAN(distance) AS v FROM taxis WHERE pickup_borough = 'Brooklyn'",
        "drops the green taxi filter",
    ),
    Case(
        "taxi_yellow_minus_green_mean_fare",
        "taxis",
        "difference: direction",
        "Measure the mean fare of yellow taxi trips and of green taxi trips "
        "separately, then report the yellow mean fare minus the green mean fare "
        "as one DIFFERENCE claim.",
        "difference",
        lambda rows: _fare(rows, "yellow") - _fare(rows, "green"),
        f"SELECT ({FARE.format('yellow')}) - ({FARE.format('green')}) AS v",
        f"SELECT ({FARE.format('green')}) - ({FARE.format('yellow')}) AS v",
        "reverses the subtraction",
    ),
    Case(
        "taxi_cross_borough_share_known",
        "taxis",
        "denominator: exclude missing",
        "Among taxi trips where both the pickup borough and the dropoff borough "
        "are recorded, what percentage ended in a different borough from where "
        "they started? Report the percentage as a single number.",
        "value",
        lambda rows: _pct(
            _where(rows, _known_boroughs),
            lambda row: row["pickup_borough"] != row["dropoff_borough"],
        ),
        f"SELECT 100.0 * {CROSS} / COUNT(*) AS v FROM taxis "
        "WHERE pickup_borough IS NOT NULL AND dropoff_borough IS NOT NULL",
        f"SELECT 100.0 * {CROSS} / COUNT(*) AS v FROM taxis",
        "divides by all trips, including trips with a missing borough",
    ),
    Case(
        "penguin_female_gentoo_mean_mass",
        "penguins",
        "population: two filters",
        "What is the mean body mass in grams of female Gentoo penguins? Report it "
        "as a single number.",
        "value",
        lambda rows: _mean(
            _column(
                _where(
                    rows,
                    lambda row: row["species"] == "Gentoo" and row["sex"] == "FEMALE",
                ),
                "body_mass_g",
            )
        ),
        "SELECT AVG(body_mass_g) AS v FROM penguins "
        "WHERE species = 'Gentoo' AND sex = 'FEMALE'",
        "SELECT AVG(body_mass_g) AS v FROM penguins WHERE species = 'Gentoo'",
        "drops the female filter",
    ),
    Case(
        "penguin_biscoe_known_sex_count",
        "penguins",
        "missing values: exclude nulls, count",
        "How many penguins on Biscoe island have a recorded sex? Report the count "
        "as a single number.",
        "value",
        lambda rows: Decimal(
            sum(
                1
                for row in rows
                if row["island"] == "Biscoe" and not _missing(row["sex"])
            )
        ),
        "SELECT COUNT(*) AS v FROM penguins "
        "WHERE island = 'Biscoe' AND sex IS NOT NULL",
        "SELECT COUNT(*) AS v FROM penguins WHERE island = 'Biscoe'",
        "counts all Biscoe penguins, including those with missing sex",
        integer=True,
    ),
    Case(
        "penguin_adelie_minus_chinstrap_flipper",
        "penguins",
        "difference: direction",
        "Measure the mean flipper length of Adelie penguins and of Chinstrap "
        "penguins separately, then report the Adelie mean minus the Chinstrap mean "
        "as one DIFFERENCE claim.",
        "difference",
        lambda rows: _flipper(rows, "Adelie") - _flipper(rows, "Chinstrap"),
        f"SELECT ({FLIP.format('Adelie')}) - ({FLIP.format('Chinstrap')}) AS v",
        f"SELECT ({FLIP.format('Chinstrap')}) - ({FLIP.format('Adelie')}) AS v",
        "reverses the subtraction",
    ),
    Case(
        "penguin_dream_share_of_adelie",
        "penguins",
        "denominator: direction of a share",
        "What percentage of Adelie penguins live on Dream island? Report the "
        "percentage as a single number.",
        "value",
        lambda rows: _pct(
            _where(rows, lambda row: row["species"] == "Adelie"),
            lambda row: row["island"] == "Dream",
        ),
        "SELECT 100.0 * SUM(CASE WHEN island = 'Dream' THEN 1 ELSE 0 END) "
        "/ COUNT(*) AS v FROM penguins WHERE species = 'Adelie'",
        "SELECT 100.0 * SUM(CASE WHEN species = 'Adelie' THEN 1 ELSE 0 END) "
        "/ COUNT(*) AS v FROM penguins WHERE island = 'Dream'",
        "reports the share of Dream penguins that are Adelie instead",
    ),
    Case(
        "diamond_ideal_one_carat_mean_price",
        "diamonds",
        "boundary: inclusive threshold",
        "What is the mean price of Ideal-cut diamonds weighing at least 1 carat? "
        "Report it as a single number.",
        "value",
        lambda rows: _mean(
            _column(
                _where(
                    rows,
                    lambda row: row["cut"] == "Ideal" and _num(row["carat"]) >= 1,
                ),
                "price",
            )
        ),
        "SELECT AVG(price) AS v FROM diamonds WHERE cut = 'Ideal' AND carat >= 1",
        "SELECT AVG(price) AS v FROM diamonds WHERE cut = 'Ideal' AND carat > 1",
        "carat > 1 drops the diamonds weighing exactly 1 carat",
    ),
    Case(
        "diamond_color_d_median_price",
        "diamonds",
        "statistic: median, not mean",
        "What is the median price of color D diamonds? Report it as a single number.",
        "value",
        lambda rows: _median(
            _column(_where(rows, lambda row: row["color"] == "D"), "price")
        ),
        "SELECT MEDIAN(price) AS v FROM diamonds WHERE color = 'D'",
        "SELECT AVG(price) AS v FROM diamonds WHERE color = 'D'",
        "reports the mean instead of the median",
    ),
    Case(
        "diamond_vvs1_mean_price_per_carat",
        "diamonds",
        "grain: mean of ratios, not ratio of sums",
        "For VVS1-clarity diamonds, compute each diamond's price per carat, then "
        "report the mean of those per-diamond values as a single number.",
        "value",
        lambda rows: _mean(
            [
                _num(row["price"]) / _num(row["carat"])
                for row in rows
                if row["clarity"] == "VVS1"
            ]
        ),
        "SELECT AVG(price / carat) AS v FROM diamonds WHERE clarity = 'VVS1'",
        "SELECT SUM(price) / SUM(carat) AS v FROM diamonds WHERE clarity = 'VVS1'",
        "computes total price over total carats instead",
    ),
    Case(
        "diamond_premium_share_over_10000",
        "diamonds",
        "denominator: direction of a share",
        "Among Premium-cut diamonds, what percentage are priced above 10000? "
        "Report the percentage as a single number.",
        "value",
        lambda rows: _pct(
            _where(rows, lambda row: row["cut"] == "Premium"),
            lambda row: _num(row["price"]) > 10000,
        ),
        "SELECT 100.0 * SUM(CASE WHEN price > 10000 THEN 1 ELSE 0 END) / COUNT(*) "
        "AS v FROM diamonds WHERE cut = 'Premium'",
        "SELECT 100.0 * SUM(CASE WHEN cut = 'Premium' THEN 1 ELSE 0 END) "
        "/ COUNT(*) AS v FROM diamonds WHERE price > 10000",
        "reports the share of diamonds above 10000 that are Premium instead",
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


def _source_path(data_dir: Path, dataset: Dataset) -> Path:
    return data_dir / "source" / f"{dataset.name}.csv"


def _source_rows(data_dir: Path, dataset: Dataset) -> list[Row]:
    path = _source_path(data_dir, dataset)
    if _sha256(path) != dataset.source_sha256:
        raise SystemExit(f"{path} differs from the pinned source; stopped.")
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != dataset.rows:
        raise SystemExit(f"{path}: unexpected row count {len(rows)}; stopped.")
    return rows


def _typed(rows: list[Row]) -> list[dict[str, object]]:
    return [
        {
            key: text if key in TEXT_COLUMNS else _value(text)
            for key, text in row.items()
        }
        for row in rows
    ]


def prepare(data_dir: Path) -> None:
    """Download pinned sources and write the converted evaluation files."""
    import openpyxl

    (data_dir / "source").mkdir(parents=True, exist_ok=True)
    for dataset in DATASETS.values():
        source = _source_path(data_dir, dataset)
        if not source.exists():
            url = SOURCE_URL.format(commit=SOURCE_COMMIT, name=dataset.name)
            with urllib.request.urlopen(url, timeout=60) as response:
                source.write_bytes(response.read())
        rows = _typed(_source_rows(data_dir, dataset))
        target = data_dir / dataset.file_name
        if target.exists():
            print(f"kept     {target}")
            continue
        if dataset.file_name.endswith(".json"):
            target.write_text(json.dumps(rows), encoding="utf-8")
        elif dataset.file_name.endswith(".xlsx"):
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            assert sheet is not None
            sheet.title = dataset.name
            sheet.append(list(rows[0]))
            for row in rows:
                sheet.append(list(row.values()))
            workbook.save(target)
        else:
            target.write_bytes(source.read_bytes())
        print(f"prepared {target}")


def _converted_rows(path: Path) -> list[dict[str, object]]:
    """Read a converted file without VeriSight, pandas or DuckDB."""
    if path.suffix == ".json":
        loaded = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(loaded, list)
        return loaded
    if path.suffix == ".xlsx":
        import openpyxl

        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        sheet = workbook.worksheets[0]
        values = list(sheet.iter_rows(values_only=True))
        workbook.close()
        header = [str(name) for name in values[0]]
        return [dict(zip(header, row, strict=True)) for row in values[1:]]
    with path.open(newline="", encoding="utf-8") as handle:
        return _typed(list(csv.DictReader(handle)))


def _same(left: object, right: object) -> bool:
    if isinstance(left, float) or isinstance(right, float):
        return (
            isinstance(left, (int, float))
            and isinstance(right, (int, float))
            and math.isclose(left, right, rel_tol=0, abs_tol=0)
        )
    return left == right


def preflight(data_dir: Path) -> dict[str, dict[str, str]]:
    """Prove file fidelity and that each case discriminates, without a model."""
    from verisight import VeriSight
    from verisight.config import Settings

    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False, gemini_api_key=None)
    )
    sources: dict[str, list[Row]] = {}
    for dataset in DATASETS.values():
        rows = _source_rows(data_dir, dataset)
        converted = _converted_rows(data_dir / dataset.file_name)
        expected = _typed(rows)
        if len(converted) != len(expected) or any(
            set(a) != set(b) or any(not _same(a[key], b[key]) for key in a)
            for a, b in zip(converted, expected, strict=True)
        ):
            raise SystemExit(f"{dataset.file_name} does not match its source.")
        sources[dataset.name] = rows
        print(
            f"fidelity ok   {dataset.file_name:14s} {len(rows)} rows ({dataset.domain})"
        )
    oracles: dict[str, dict[str, str]] = {}
    for case in CASES:
        path = data_dir / DATASETS[case.dataset].file_name
        expected_value = case.oracle(sources[case.dataset])
        control = Decimal(str(app.execute(path, case.control_sql).rows[0][0]))
        trap = Decimal(str(app.execute(path, case.trap_sql).rows[0][0]))
        if not _close(control, expected_value, case.integer):
            raise SystemExit(
                f"{case.case_id}: control {control} != expected {expected_value}"
            )
        if _close(trap, expected_value, case.integer):
            raise SystemExit(f"{case.case_id}: trap {trap} is not distinguishable")
        oracles[case.case_id] = {
            "expected": str(expected_value),
            "control": str(control),
            "trap": str(trap),
        }
        print(
            f"preflight ok  {case.case_id:40s} "
            f"expected={float(expected_value):.6f}  trap={float(trap):.6f}"
        )
    return oracles


def classify(
    report: dict[str, object] | None, case: Case, expected: Decimal
) -> dict[str, object]:
    """Score one CLI report. Only the SQL evidence cell is compared, never prose.

    Correct and incorrect require an accepted answer; a matching cell in a
    rejected answer is reported separately as not_accepted.
    """
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
        "synthesis_recovery": investigation.get("synthesis_recovery"),
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
    matches = _close(actual, expected, case.integer)
    scored = {**base, "numeric_match": matches, "actual": str(actual)}
    if base["contract_accepted"] is not True:
        # A matching cell inside a rejected answer is not an answer users get.
        return {**scored, "outcome": "not_accepted"}
    return {**scored, "outcome": "correct" if matches else "incorrect"}


def _write_new(path: Path, payload: object) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, indent=2, default=str)
        handle.write("\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--out", type=Path, help="New directory; must not exist.")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=3)
    parser.add_argument("--max-seconds", type=float, default=300.0)
    parser.add_argument("--pause-seconds", type=float, default=60.0)
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()

    if args.prepare:
        prepare(args.data_dir)
    oracles = preflight(args.data_dir)
    if args.preflight_only or args.out is None:
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
    packages: dict[str, str | None] = {}
    for name in (
        "verisight",
        "google-genai",
        "duckdb",
        "sqlglot",
        "pandas",
        "openpyxl",
    ):
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
            "source_commit": SOURCE_COMMIT,
            "datasets": {
                d.name: {
                    "domain": d.domain,
                    "file": d.file_name,
                    "file_sha256": _sha256(args.data_dir / d.file_name),
                    "source_sha256": d.source_sha256,
                    "rows": d.rows,
                }
                for d in DATASETS.values()
            },
            "repeats": args.repeats,
            "max_steps": args.max_steps,
            "max_seconds": args.max_seconds,
            "pause_seconds": args.pause_seconds,
            "tolerance": str(TOLERANCE),
            "cases": [
                {
                    "case_id": c.case_id,
                    "dataset": c.dataset,
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
                    str(args.data_dir / DATASETS[case.dataset].file_name),
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
                    "dataset": case.dataset,
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
                    f"round {round_number} {case.case_id:40s} "
                    f"{record['outcome']:20s} {elapsed:7.1f}s"
                )
                time.sleep(args.pause_seconds)

    summary: dict[str, dict[str, int]] = {}
    for record in results:
        counts = summary.setdefault(str(record["case_id"]), {})
        outcome = str(record["outcome"])
        counts[outcome] = counts.get(outcome, 0) + 1
        if record.get("matched_trap"):
            counts["matched_trap"] = counts.get("matched_trap", 0) + 1
        if record.get("synthesis_recovery"):
            counts["recovery_used"] = counts.get("recovery_used", 0) + 1
    totals: dict[str, int] = {}
    for counts in summary.values():
        for key, value in counts.items():
            totals[key] = totals.get(key, 0) + value
    by_domain: dict[str, dict[str, int]] = {}
    for record in results:
        domain = DATASETS[str(record["dataset"])].domain
        counts = by_domain.setdefault(domain, {})
        counts[str(record["outcome"])] = counts.get(str(record["outcome"]), 0) + 1
    _write_new(
        args.out / "summary.json",
        {
            "finished_utc": datetime.now(UTC).isoformat(),
            "attempts": len(results),
            "totals": totals,
            "by_domain": by_domain,
            "by_case": summary,
        },
    )
    print(
        json.dumps(
            {"attempts": len(results), "totals": totals, "by_domain": by_domain},
            indent=2,
        )
    )
    print("Keep every attempt, including failures. Do not rerun to replace any.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
