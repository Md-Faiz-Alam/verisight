"""VeriSight evaluation v2: messy values, dates and a two-file join.

Three generated files in three formats, each built to exercise one newer
engine ability on realistic, imperfect data:
    retail   orders.csv      messy values: "$1,234.50", "N/A", "-", "10%",
                             "Shipped" / "shipped " / "SHIPPED", a padded header,
                             ISO order dates with missing markers
    crm      customers.xlsx  joined to orders; region "NA" means North America
                             and must stay a label, some regions are blank
    energy   sensors.json    ISO date-times every six hours, kWh numbers mixed
                             with "N/A" strings, missing temperatures

The data comes from a fixed random seed, so every run on every machine uses
the same files; no download is needed. Expected answers are computed from the
generator's clean values with Decimal, never from the messy files, pandas,
DuckDB or VeriSight. Each case also has a correct control SQL and a plausible
trap SQL. Offline preflight proves, before any model call, that each file holds
exactly the generated values, that the control reproduces the answer through
VeriSight's loader and executor (which is also proof that cleaning works), and
that the trap gives a different answer.

The questions were written and frozen before any live run. VeriSight's
production code contains nothing specific to these files. This set is separate
from v1; v1 results stay comparable.

Every attempt is kept, including failures. Nothing is overwritten.

Usage (PowerShell, from the VeriSight repository root, venv active):
    python evaluation\\v2\\run_v2_eval.py --prepare --data-dir datasets\\v2
    python evaluation\\v2\\run_v2_eval.py --data-dir datasets\\v2 `
        --out F:\\verisight-validation-artifacts\\eval-v2\\run-1
Keep --out outside the repository so results are never committed by accident.
"""

import argparse
import csv
import hashlib
import json
import random
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from importlib import metadata
from pathlib import Path

SEED = 20261103
TOLERANCE = Decimal("0.005")
CENT = Decimal("0.01")

# Pinned so a change to the generator or to Python's random module is noticed.
# The workbook is checked cell by cell instead, because .xlsx files carry
# timestamps.
FILE_SHA256 = {
    "orders.csv": "df6913a40eae7f37ba7cfd0ac259254801edef2e6c217690ea8133c85bb55e71",
    "sensors.json": "5765f4f3abe009d711da9347a9be7efa0509d8daadaecfacaf6d45d3bf74f2d8",
}


@dataclass(frozen=True)
class Order:
    order_id: int
    order_date: date | None
    amount: Decimal | None
    customer_id: str
    status: str
    discount: int | None
    qty: int | None


@dataclass(frozen=True)
class Customer:
    customer_id: str
    region: str | None
    segment: str
    signup_date: date


@dataclass(frozen=True)
class Reading:
    reading_time: datetime
    sensor_id: str
    site: str
    kwh: Decimal | None
    temperature_c: Decimal | None


@dataclass(frozen=True)
class Truth:
    orders: tuple[Order, ...]
    customers: tuple[Customer, ...]
    readings: tuple[Reading, ...]


@dataclass(frozen=True)
class Files:
    """Exactly what is written, as text cells (CSV, JSON) or typed cells."""

    orders_csv: list[list[str]]
    customers_xlsx: list[list[object]]
    sensors_json: list[dict[str, object]]


def generate() -> tuple[Truth, Files]:
    """Build clean values and the messy files that represent them."""
    rng = random.Random(SEED)

    customers = []
    for number in range(1, 121):
        region = rng.choices(["NA", "EU", "APAC", None], weights=[45, 30, 20, 5])[0]
        customers.append(
            Customer(
                customer_id=f"C{number:03d}",
                region=region,
                segment=rng.choices(["Consumer", "Business"], weights=[65, 35])[0],
                signup_date=date(2023, 1, 1) + timedelta(days=rng.randrange(730)),
            )
        )

    first_day = date(2024, 1, 1)
    days = (date(2025, 6, 30) - first_day).days + 1
    # A few fixed dates make the calendar boundaries in the questions matter.
    pinned_dates = [date(2024, 10, 1), date(2024, 12, 31), date(2024, 12, 31)]
    pinned_dates += [date(2024, 3, 15), date(2025, 3, 31)]
    orders = []
    for order_id in range(1001, 1601):
        if pinned_dates:
            order_date: date | None = pinned_dates.pop()
        elif rng.random() < 0.015:
            order_date = None
        else:
            order_date = first_day + timedelta(days=rng.randrange(days))
        cents = rng.randrange(500, 250_001)
        if rng.random() < 0.15:
            cents = rng.randrange(100_000, 600_001)
        amount = None if rng.random() < 0.025 else Decimal(cents) / 100
        discount = None if rng.random() < 0.2 else rng.choice([0, 5, 10, 15, 20])
        roll = rng.random()
        qty = None if roll < 0.02 else 0 if roll < 0.035 else rng.randint(1, 5)
        orders.append(
            Order(
                order_id=order_id,
                order_date=order_date,
                amount=amount,
                customer_id=f"C{rng.randint(1, 100):03d}",
                status=rng.choices(
                    ["shipped", "pending", "cancelled"], weights=[70, 18, 12]
                )[0],
                discount=discount,
                qty=qty,
            )
        )

    sites = {"Alpha": Decimal("21.5"), "Beta": Decimal("19.8"), "Gamma": Decimal(17)}
    readings = []
    start = datetime(2025, 3, 1)
    for step in range(31 * 4):
        moment = start + timedelta(hours=6 * step)
        for site, base_temperature in sites.items():
            for sensor in (1, 2):
                kwh = Decimal(rng.randrange(2_000, 40_000)) / 1000
                temperature = base_temperature + Decimal(rng.randint(-40, 40)) / 10
                readings.append(
                    Reading(
                        reading_time=moment,
                        sensor_id=f"{site[0]}{sensor}",
                        site=site,
                        kwh=None if rng.random() < 0.04 else kwh,
                        temperature_c=None if rng.random() < 0.03 else temperature,
                    )
                )

    status_spellings = {
        "shipped": (["Shipped", "shipped", "SHIPPED", "Shipped "], [55, 20, 15, 10]),
        "pending": (["Pending"], [1]),
        "cancelled": (["Cancelled", "cancelled"], [80, 20]),
    }
    orders_csv = [
        ["order_id", "order_date", " Amount ", "customer_id", "status"]
        + ["discount", "qty"]
    ]
    for order in orders:
        spellings, weights = status_spellings[order.status]
        orders_csv.append(
            [
                str(order.order_id),
                "N/A" if order.order_date is None else order.order_date.isoformat(),
                rng.choice(["N/A", "-"])
                if order.amount is None
                else f"${order.amount:,.2f}",
                order.customer_id,
                rng.choices(spellings, weights)[0],
                "" if order.discount is None else f"{order.discount}%",
                rng.choice(["N/A", "-", ""]) if order.qty is None else str(order.qty),
            ]
        )

    customers_xlsx: list[list[object]] = [
        ["customer_id", "region", "segment", "signup_date"]
    ]
    for customer in customers:
        customers_xlsx.append(
            [
                customer.customer_id,
                customer.region,
                customer.segment,
                datetime.combine(customer.signup_date, datetime.min.time()),
            ]
        )

    sensors_json: list[dict[str, object]] = [
        {
            "reading_time": reading.reading_time.isoformat(),
            "sensor_id": reading.sensor_id,
            "site": reading.site,
            "kwh": "N/A" if reading.kwh is None else float(reading.kwh),
            "temperature_c": None
            if reading.temperature_c is None
            else float(reading.temperature_c),
        }
        for reading in readings
    ]
    truth = Truth(tuple(orders), tuple(customers), tuple(readings))
    return truth, Files(orders_csv, customers_xlsx, sensors_json)


# ---- independent expected answers (clean values, Decimal) -------------------


def _mean(values: list[Decimal]) -> Decimal:
    return sum(values, Decimal(0)) / len(values)


def _amounts(orders: list[Order]) -> list[Decimal]:
    return [order.amount for order in orders if order.amount is not None]


def _shipped(truth: Truth) -> list[Order]:
    return [order for order in truth.orders if order.status == "shipped"]


def _dated(truth: Truth, keep: Callable[[date], bool]) -> list[Order]:
    return [
        order
        for order in truth.orders
        if order.order_date is not None and keep(order.order_date)
    ]


def _customers(truth: Truth, keep: Callable[[Customer], bool]) -> set[str]:
    return {c.customer_id for c in truth.customers if keep(c)}


def _of(truth: Truth, ids: set[str]) -> list[Order]:
    return [order for order in truth.orders if order.customer_id in ids]


def _readings(truth: Truth, keep: Callable[[Reading], bool]) -> list[Reading]:
    return [reading for reading in truth.readings if keep(reading)]


def _kwh(readings: list[Reading]) -> list[Decimal]:
    return [reading.kwh for reading in readings if reading.kwh is not None]


def _temperature(truth: Truth, site: str) -> Decimal:
    chosen = _readings(truth, lambda r: r.site == site)
    return _mean([r.temperature_c for r in chosen if r.temperature_c is not None])


def _span(truth: Truth) -> Decimal:
    dates = [o.order_date for o in truth.orders if o.order_date is not None]
    return Decimal((max(dates) - min(dates)).days)


@dataclass(frozen=True)
class Case:
    case_id: str
    files: tuple[str, ...]
    skill: str
    question: str
    operation: str
    oracle: Callable[[Truth], Decimal]
    control_sql: str
    trap_sql: str
    trap_description: str
    integer: bool = False


SHIPPED = "LOWER(TRIM(status)) = 'shipped'"
JOIN = "FROM orders o JOIN customers c ON o.customer_id = c.customer_id"
ORDERS = ("orders.csv",)
BOTH = ("orders.csv", "customers.xlsx")
SENSORS = ("sensors.json",)
CASES = (
    Case(
        "messy_shipped_count",
        ORDERS,
        "label variants: case and spaces",
        "How many orders were shipped? Report the count as a single number.",
        "value",
        lambda t: Decimal(len(_shipped(t))),
        f"SELECT COUNT(*) AS v FROM orders WHERE {SHIPPED}",
        "SELECT COUNT(*) AS v FROM orders WHERE status = 'Shipped'",
        "matches one spelling and misses 'shipped', 'SHIPPED' and 'Shipped '",
        integer=True,
    ),
    Case(
        "messy_mean_amount",
        ORDERS,
        "currency, separators and missing markers",
        "What is the average order amount? Report it as a single number.",
        "value",
        lambda t: _mean(_amounts(list(t.orders))),
        "SELECT AVG(Amount) AS v FROM orders",
        "SELECT AVG(COALESCE(Amount, 0)) AS v FROM orders",
        "counts orders with a missing amount as zero",
    ),
    Case(
        "messy_missing_qty",
        ORDERS,
        "missing markers: N/A, - and empty",
        "How many orders have no recorded quantity? Report the count as a single "
        "number.",
        "value",
        lambda t: Decimal(sum(1 for o in t.orders if o.qty is None)),
        "SELECT COUNT(*) AS v FROM orders WHERE qty IS NULL",
        "SELECT COUNT(*) AS v FROM orders WHERE qty = 0",
        "counts zero-quantity orders instead of missing quantities",
        integer=True,
    ),
    Case(
        "messy_mean_discount",
        ORDERS,
        "percent values",
        "Among orders with a recorded discount, what is the average discount in "
        "percent? Report it as a single number.",
        "value",
        lambda t: _mean(
            [Decimal(o.discount) for o in t.orders if o.discount is not None]
        ),
        "SELECT AVG(discount) AS v FROM orders",
        "SELECT AVG(discount) / 100 AS v FROM orders",
        "reports a fraction instead of percent points",
    ),
    Case(
        "messy_shipped_revenue",
        ORDERS,
        "label variants with currency",
        "What is the total amount of all shipped orders? Report it as a single number.",
        "value",
        lambda t: sum(_amounts(_shipped(t)), Decimal(0)),
        f"SELECT SUM(Amount) AS v FROM orders WHERE {SHIPPED}",
        "SELECT SUM(Amount) AS v FROM orders WHERE status = 'Shipped'",
        "sums one spelling of shipped only",
    ),
    Case(
        "dates_march_2025_total",
        ORDERS,
        "dates: one month of one year",
        "What was the total amount of orders placed in March 2025? Report it as "
        "a single number.",
        "value",
        lambda t: sum(
            _amounts(_dated(t, lambda d: (d.year, d.month) == (2025, 3))), Decimal(0)
        ),
        "SELECT SUM(Amount) AS v FROM orders "
        "WHERE order_date >= DATE '2025-03-01' AND order_date < DATE '2025-04-01'",
        "SELECT SUM(Amount) AS v FROM orders WHERE MONTH(order_date) = 3",
        "adds March 2024 to March 2025",
    ),
    Case(
        "dates_q4_2024_count",
        ORDERS,
        "dates: quarter boundaries",
        "How many orders were placed in the fourth quarter of 2024? Report the "
        "count as a single number.",
        "value",
        lambda t: Decimal(
            len(_dated(t, lambda d: date(2024, 10, 1) <= d <= date(2024, 12, 31)))
        ),
        "SELECT COUNT(*) AS v FROM orders "
        "WHERE order_date >= DATE '2024-10-01' AND order_date < DATE '2025-01-01'",
        "SELECT COUNT(*) AS v FROM orders "
        "WHERE order_date >= DATE '2024-10-01' AND order_date < DATE '2024-12-31'",
        "drops orders placed on 31 December",
        integer=True,
    ),
    Case(
        "dates_span_days",
        ORDERS,
        "dates: difference in days",
        "How many days passed between the first and the last order date? Report "
        "the number of days as a single number.",
        "value",
        _span,
        "SELECT date_diff('day', MIN(order_date), MAX(order_date)) AS v FROM orders",
        "SELECT COUNT(DISTINCT order_date) AS v FROM orders",
        "counts days that have orders instead of the elapsed days",
        integer=True,
    ),
    Case(
        "join_na_region_amount",
        BOTH,
        "join: two files, NA is a label",
        "What is the total amount of orders placed by customers in the NA "
        "region? Report it as a single number.",
        "value",
        lambda t: sum(
            _amounts(_of(t, _customers(t, lambda c: c.region == "NA"))), Decimal(0)
        ),
        f"SELECT SUM(o.Amount) AS v {JOIN} WHERE c.region = 'NA'",
        f"SELECT SUM(o.Amount) AS v {JOIN} WHERE c.region IS NULL",
        "treats the NA region as a missing region",
    ),
    Case(
        "join_business_mean_amount",
        BOTH,
        "join: segment filter",
        "Among orders from Business-segment customers, what is the average order "
        "amount? Report it as a single number.",
        "value",
        lambda t: _mean(
            _amounts(_of(t, _customers(t, lambda c: c.segment == "Business")))
        ),
        f"SELECT AVG(o.Amount) AS v {JOIN} WHERE c.segment = 'Business'",
        "SELECT AVG(Amount) AS v FROM orders",
        "averages all orders, ignoring the customer segment",
    ),
    Case(
        "join_customers_without_orders",
        BOTH,
        "join: anti-join",
        "How many customers have never placed an order? Report the count as a "
        "single number.",
        "value",
        lambda t: Decimal(
            len(
                {c.customer_id for c in t.customers} - {o.customer_id for o in t.orders}
            )
        ),
        "SELECT COUNT(*) AS v FROM customers c WHERE NOT EXISTS "
        "(SELECT 1 FROM orders o WHERE o.customer_id = c.customer_id)",
        "SELECT COUNT(DISTINCT customer_id) AS v FROM orders",
        "counts customers who did place orders",
        integer=True,
    ),
    Case(
        "sensors_alpha_mean_kwh",
        SENSORS,
        "JSON numbers mixed with N/A",
        "What is the mean kWh reading at site Alpha? Report it as a single number.",
        "value",
        lambda t: _mean(_kwh(_readings(t, lambda r: r.site == "Alpha"))),
        "SELECT AVG(kwh) AS v FROM sensors WHERE site = 'Alpha'",
        "SELECT AVG(COALESCE(kwh, 0)) AS v FROM sensors WHERE site = 'Alpha'",
        "counts missing readings as zero",
    ),
    Case(
        "sensors_day_total",
        SENSORS,
        "date-times: one calendar day",
        "What was the total kWh recorded across all sensors on 15 March 2025? "
        "Report it as a single number.",
        "value",
        lambda t: sum(
            _kwh(_readings(t, lambda r: r.reading_time.date() == date(2025, 3, 15))),
            Decimal(0),
        ),
        "SELECT SUM(kwh) AS v FROM sensors "
        "WHERE CAST(reading_time AS DATE) = DATE '2025-03-15'",
        "SELECT SUM(kwh) AS v FROM sensors "
        "WHERE reading_time = TIMESTAMP '2025-03-15 00:00:00'",
        "keeps only the midnight readings of that day",
    ),
    Case(
        "sensors_temperature_difference",
        SENSORS,
        "difference of two means",
        "How much warmer is site Alpha than site Beta on average? Report Alpha's "
        "mean temperature minus Beta's mean temperature.",
        "difference",
        lambda t: _temperature(t, "Alpha") - _temperature(t, "Beta"),
        "SELECT (SELECT AVG(temperature_c) FROM sensors WHERE site = 'Alpha') - "
        "(SELECT AVG(temperature_c) FROM sensors WHERE site = 'Beta') AS v",
        "SELECT (SELECT AVG(temperature_c) FROM sensors WHERE site = 'Beta') - "
        "(SELECT AVG(temperature_c) FROM sensors WHERE site = 'Alpha') AS v",
        "subtracts in the wrong direction",
    ),
)


# ---- files, fidelity and preflight -------------------------------------------


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare(data_dir: Path) -> None:
    """Write the generated files; existing files are kept, never replaced."""
    import openpyxl

    data_dir.mkdir(parents=True, exist_ok=True)
    _, files = generate()
    targets = {
        "orders.csv": data_dir / "orders.csv",
        "customers.xlsx": data_dir / "customers.xlsx",
        "sensors.json": data_dir / "sensors.json",
    }
    for name, target in targets.items():
        if target.exists():
            print(f"kept     {target}")
            continue
        if name == "orders.csv":
            with target.open("x", newline="", encoding="utf-8") as handle:
                csv.writer(handle).writerows(files.orders_csv)
        elif name == "sensors.json":
            with target.open("x", encoding="utf-8", newline="\n") as handle:
                json.dump(files.sensors_json, handle)
        else:
            workbook = openpyxl.Workbook()
            sheet = workbook.active
            assert sheet is not None
            sheet.title = "customers"
            for row in files.customers_xlsx:
                sheet.append(row)
            workbook.save(target)
        print(f"prepared {target}")


def check_files(data_dir: Path, files: Files) -> None:
    """Prove each file holds exactly the generated cells, without VeriSight."""
    import openpyxl

    for name, expected in FILE_SHA256.items():
        actual = _sha256(data_dir / name)
        if actual != expected:
            raise SystemExit(f"{name}: sha256 {actual} differs from the pinned file.")
    with (data_dir / "orders.csv").open(newline="", encoding="utf-8") as handle:
        if list(csv.reader(handle)) != files.orders_csv:
            raise SystemExit("orders.csv does not match the generated values.")
    if json.loads((data_dir / "sensors.json").read_text(encoding="utf-8")) != (
        files.sensors_json
    ):
        raise SystemExit("sensors.json does not match the generated values.")
    workbook = openpyxl.load_workbook(
        data_dir / "customers.xlsx", read_only=True, data_only=True
    )
    sheet = workbook.worksheets[0]
    cells = [list(row) for row in sheet.iter_rows(values_only=True)]
    title = sheet.title
    workbook.close()
    if title != "customers" or cells != files.customers_xlsx:
        raise SystemExit("customers.xlsx does not match the generated values.")
    for name in ("orders.csv", "customers.xlsx", "sensors.json"):
        print(f"fidelity ok   {name}")


def _close(actual: Decimal, expected: Decimal, integer: bool) -> bool:
    return actual == expected if integer else abs(actual - expected) <= TOLERANCE


def preflight(data_dir: Path) -> dict[str, dict[str, str]]:
    """Prove fidelity and that each case discriminates, without a model."""
    from verisight import VeriSight
    from verisight.config import Settings

    truth, files = generate()
    check_files(data_dir, files)
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False, gemini_api_key=None)
    )
    oracles: dict[str, dict[str, str]] = {}
    for case in CASES:
        paths = [data_dir / name for name in case.files]
        expected = case.oracle(truth)
        control = Decimal(str(app.execute(paths, case.control_sql).rows[0][0]))
        trap = Decimal(str(app.execute(paths, case.trap_sql).rows[0][0]))
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
            f"preflight ok  {case.case_id:32s} "
            f"expected={float(expected):.4f}  trap={float(trap):.4f}"
        )
    return oracles


# ---- live run and scoring ----------------------------------------------------


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


def _command(case: Case, args: argparse.Namespace, report_path: Path) -> list[str]:
    return [
        sys.executable,
        "-m",
        "verisight.cli",
        "investigate",
        *(str(args.data_dir / name) for name in case.files),
        "--question",
        case.question,
        "--require-claim",
        case.operation,
        "--max-steps",
        str(args.max_steps),
        "--max-seconds",
        str(args.max_seconds),
        "--provider-retries",
        str(args.provider_retries),
        "--provider-retry-delay-seconds",
        str(args.provider_retry_delay_seconds),
        "--allow-llm-data-disclosure",
        "--output",
        str(report_path),
    ]


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
    parser.add_argument("--provider-retries", type=int, choices=range(6), default=3)
    parser.add_argument("--provider-retry-delay-seconds", type=float, default=2.0)
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
            "evaluation": "v2",
            "revision": revision,
            "tracked_changes": bool(dirty),
            "python": sys.version.split()[0],
            "packages": packages,
            "runner_sha256": _sha256(Path(__file__)),
            "seed": SEED,
            "files": {
                name: _sha256(args.data_dir / name)
                for name in ("orders.csv", "customers.xlsx", "sensors.json")
            },
            "repeats": args.repeats,
            "max_steps": args.max_steps,
            "max_seconds": args.max_seconds,
            "provider_retries": args.provider_retries,
            "provider_retry_delay_seconds": args.provider_retry_delay_seconds,
            "pause_seconds": args.pause_seconds,
            "tolerance": str(TOLERANCE),
            "cases": [
                {
                    "case_id": c.case_id,
                    "files": list(c.files),
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
                started = time.perf_counter()
                try:
                    done = subprocess.run(
                        _command(case, args, report_path),
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
                expected = Decimal(oracles[case.case_id]["expected"])
                scored = classify(report, case, expected)
                record = {
                    "round": round_number,
                    "case_id": case.case_id,
                    "files": list(case.files),
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
                    f"round {round_number} {case.case_id:32s} "
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
