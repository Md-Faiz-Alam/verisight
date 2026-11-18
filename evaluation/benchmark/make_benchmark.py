"""Build VeriSight's public benchmark: data files, questions and expected answers.

Five domains in five formats, generated from a fixed seed, with 20 answerable,
5 ambiguous and 5 unanswerable questions. Every expected answer is computed
here, in plain Python with exact decimals, from the generated records
themselves, never by reading the files back, so neither pandas, DuckDB nor
VeriSight takes part. The files carry real-world flaws on purpose: currency
text, thousands separators, mixed-case labels and missing values.

Run from the repository root to rebuild the committed files:

    python evaluation/benchmark/make_benchmark.py

Then score a setup with the comparison runner, which reads questions.csv and
data/ from this folder:

    python evaluation/baseline/run_baseline_eval.py --root evaluation/benchmark --freeze
"""

import csv
import json
import random
import statistics
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import cast

import pandas as pd

SEED = 2026
ROOT = Path(__file__).resolve().parent
Record = dict[str, object]


@dataclass(frozen=True)
class Question:
    """One benchmark question, with the SQL that checks its expected answer."""

    question_id: str
    files: tuple[str, ...]
    kind: str
    text: str
    expected: Decimal | str
    tolerance: Decimal = Decimal(0)
    # Written by hand and run by the tests, never shown to a model.
    control_sql: str | None = None


def _dec(row: Record, name: str) -> Decimal:
    return cast(Decimal, row[name])


def _int(row: Record, name: str) -> int:
    return cast(int, row[name])


def _day(rng: random.Random, year: int) -> date:
    return date(year, 1, 1) + timedelta(days=rng.randrange(365))


def _money(amount: Decimal) -> str:
    """Write an amount the way exports often do: $1,234.50."""
    return f"${amount:,.2f}"


def _mean(values: Iterable[Decimal]) -> Decimal:
    items = list(values)
    return sum(items, Decimal(0)) / len(items)


def _rounded(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"))


def healthcare(rng: random.Random) -> tuple[list[Record], list[Question]]:
    departments = ["Cardiology", "Oncology", "Pediatrics", "Orthopedics"]
    visits: list[Record] = []
    for number in range(1, 301):
        visits.append(
            {
                "visit_id": f"V{number:04d}",
                "patient_id": f"P{rng.randrange(1, 181):03d}",
                "department": rng.choice(departments),
                "visit_date": _day(rng, 2024).isoformat(),
                "wait_minutes": None if rng.random() < 0.08 else rng.randrange(5, 121),
                "cost": Decimal(rng.randrange(5_000, 250_000)) / 100,
                "readmitted": rng.random() < 0.18,
            }
        )
    waits = [
        Decimal(_int(v, "wait_minutes"))
        for v in visits
        if v["wait_minutes"] is not None
    ]
    readmitted = sum(1 for v in visits if v["readmitted"])

    def cost_of(department: str) -> Decimal:
        return sum(
            (_dec(v, "cost") for v in visits if v["department"] == department),
            Decimal(0),
        )

    files = ("visits.json",)
    questions = [
        Question(
            "h1",
            files,
            "number",
            "How many visits were to the Cardiology department?",
            Decimal(sum(1 for v in visits if v["department"] == "Cardiology")),
            control_sql="SELECT COUNT(*) FROM visits WHERE department = 'Cardiology'",
        ),
        Question(
            "h2",
            files,
            "number",
            "What is the average wait in minutes, over the visits that have a "
            "recorded wait time?",
            _rounded(_mean(waits)),
            Decimal("0.005"),
            "SELECT AVG(wait_minutes) FROM visits",
        ),
        Question(
            "h3",
            files,
            "number",
            "What percentage of visits were followed by a readmission?",
            _rounded(Decimal(100 * readmitted) / len(visits)),
            Decimal("0.05"),
            "SELECT 100.0 * SUM(CASE WHEN readmitted THEN 1 ELSE 0 END) / COUNT(*) "
            "FROM visits",
        ),
        Question(
            "h4",
            files,
            "difference",
            "What is the total cost of Oncology visits minus the total cost of "
            "Pediatrics visits?",
            cost_of("Oncology") - cost_of("Pediatrics"),
            Decimal("0.005"),
            "SELECT SUM(CASE WHEN department = 'Oncology' THEN cost END) "
            "- SUM(CASE WHEN department = 'Pediatrics' THEN cost END) FROM visits",
        ),
        Question(
            "h5", files, "number", "How many visits had a long wait?", "AMBIGUOUS"
        ),
        Question(
            "h6",
            files,
            "number",
            "What is the average age of the patients?",
            "UNANSWERABLE",
        ),
    ]
    return visits, questions


def retail(
    rng: random.Random,
) -> tuple[list[Record], list[Record], list[Question]]:
    regions = ["North", "South", "East", "West"]
    customers: list[Record] = [
        {
            "customer_id": f"C{number:03d}",
            "region": rng.choice(regions),
            "segment": rng.choice(["Consumer", "Business"]),
        }
        for number in range(1, 81)
    ]
    # Exports spell one status several ways; the questions count them as one.
    spellings = {
        "Shipped": ["Shipped", "shipped", "SHIPPED"],
        "Pending": ["Pending", "pending"],
        "Cancelled": ["Cancelled"],
    }
    orders: list[Record] = []
    for number in range(1, 401):
        status = rng.choices(list(spellings), weights=[6, 3, 1])[0]
        orders.append(
            {
                "order_id": 10_000 + number,
                "customer_id": f"C{rng.randrange(1, 71):03d}",
                "order_date": _day(rng, rng.choice([2023, 2024])).isoformat(),
                "status": status,
                "status_text": rng.choice(spellings[status]),
                "amount": Decimal(rng.randrange(1_000, 400_000)) / 100,
            }
        )
    region_of = {c["customer_id"]: c["region"] for c in customers}

    def total(rows: Iterable[Record]) -> Decimal:
        return sum((_dec(row, "amount") for row in rows), Decimal(0))

    files = ("orders.csv", "customers.csv")
    questions = [
        Question(
            "r1",
            ("orders.csv",),
            "number",
            "How many orders are shipped, counting every spelling of the Shipped "
            "status?",
            Decimal(sum(1 for o in orders if o["status"] == "Shipped")),
            control_sql="SELECT COUNT(*) FROM orders "
            "WHERE LOWER(TRIM(status)) = 'shipped'",
        ),
        Question(
            "r2",
            files,
            "number",
            "What is the total amount of all orders placed by customers in the West "
            "region?",
            total(o for o in orders if region_of[o["customer_id"]] == "West"),
            Decimal("0.005"),
            "SELECT SUM(o.amount) FROM orders AS o JOIN customers AS c "
            "ON o.customer_id = c.customer_id WHERE c.region = 'West'",
        ),
        Question(
            "r3",
            ("orders.csv",),
            "number",
            "How many different customers placed at least one order?",
            Decimal(len({o["customer_id"] for o in orders})),
            control_sql="SELECT COUNT(DISTINCT customer_id) FROM orders",
        ),
        Question(
            "r4",
            ("orders.csv",),
            "difference",
            "How much more was the total amount of orders placed in 2024 than of "
            "orders placed in 2023?",
            total(o for o in orders if str(o["order_date"]).startswith("2024"))
            - total(o for o in orders if str(o["order_date"]).startswith("2023")),
            Decimal("0.005"),
            "SELECT SUM(CASE WHEN YEAR(order_date) = 2024 THEN amount END) "
            "- SUM(CASE WHEN YEAR(order_date) = 2023 THEN amount END) FROM orders",
        ),
        Question(
            "r5",
            files,
            "number",
            "What is the total amount spent by the most valuable customers?",
            "AMBIGUOUS",
        ),
        Question(
            "r6",
            ("orders.csv",),
            "number",
            "What is the total profit made on all orders?",
            "UNANSWERABLE",
        ),
    ]
    return orders, customers, questions


def manufacturing(rng: random.Random) -> tuple[list[Record], list[Question]]:
    runs: list[Record] = []
    for number in range(1, 241):
        units = rng.randrange(200, 1_201)
        runs.append(
            {
                "run_id": f"R{number:04d}",
                "line": f"L{rng.randrange(1, 5)}",
                "shift": rng.choice(["Day", "Night"]),
                "run_date": _day(rng, 2024),
                "units_produced": units,
                "defects": rng.randrange(0, units // 25 + 1),
            }
        )

    def total(name: str, rows: Iterable[Record]) -> int:
        return sum(_int(row, name) for row in rows)

    night = [_int(r, "units_produced") for r in runs if r["shift"] == "Night"]
    files = ("production.xlsx",)
    questions = [
        Question(
            "m1",
            files,
            "number",
            "What is the total number of units produced on line L2?",
            Decimal(total("units_produced", (r for r in runs if r["line"] == "L2"))),
            control_sql="SELECT SUM(units_produced) FROM runs WHERE line = 'L2'",
        ),
        Question(
            "m2",
            files,
            "number",
            "What is the overall defect rate, as a percentage of all units produced?",
            _rounded(
                Decimal(100 * total("defects", runs)) / total("units_produced", runs)
            ),
            Decimal("0.01"),
            "SELECT 100.0 * SUM(defects) / SUM(units_produced) FROM runs",
        ),
        Question(
            "m3",
            files,
            "number",
            "What is the median number of units produced per run on the Night shift?",
            Decimal(str(statistics.median(night))),
            control_sql="SELECT MEDIAN(units_produced) FROM runs WHERE shift = 'Night'",
        ),
        Question(
            "m4",
            files,
            "difference",
            "What is the number of defects recorded on the Day shift minus the "
            "number recorded on the Night shift?",
            Decimal(
                total("defects", (r for r in runs if r["shift"] == "Day"))
                - total("defects", (r for r in runs if r["shift"] == "Night"))
            ),
            control_sql="SELECT SUM(CASE WHEN shift = 'Day' THEN defects END) "
            "- SUM(CASE WHEN shift = 'Night' THEN defects END) FROM runs",
        ),
        Question("m5", files, "number", "How many runs had poor quality?", "AMBIGUOUS"),
        Question(
            "m6",
            files,
            "number",
            "What was the average machine temperature on line L1?",
            "UNANSWERABLE",
        ),
    ]
    return runs, questions


def education(rng: random.Random) -> tuple[list[Record], list[Question]]:
    scores: list[Record] = []
    for year in (2023, 2024):
        for student in range(1, 61):
            school = "ABC"[student % 3]
            for subject in ("Math", "Science", "English"):
                missing = rng.random() < 0.05
                scores.append(
                    {
                        "student_id": f"S{year % 100}{student:03d}",
                        "school": school,
                        "subject": subject,
                        "year": year,
                        "score": None if missing else rng.randrange(35, 101),
                    }
                )

    def recorded(**match: object) -> list[Decimal]:
        return [
            Decimal(_int(row, "score"))
            for row in scores
            if row["score"] is not None
            and all(row[key] == value for key, value in match.items())
        ]

    files = ("scores.tsv",)
    questions = [
        Question(
            "e1",
            files,
            "number",
            "What is the average Math score, over the Math scores that were recorded?",
            _rounded(_mean(recorded(subject="Math"))),
            Decimal("0.005"),
            "SELECT AVG(score) FROM scores WHERE subject = 'Math'",
        ),
        Question(
            "e2",
            files,
            "number",
            "How many Science scores were 90 or higher?",
            Decimal(sum(1 for value in recorded(subject="Science") if value >= 90)),
            control_sql="SELECT COUNT(*) FROM scores "
            "WHERE subject = 'Science' AND score >= 90",
        ),
        Question(
            "e3",
            files,
            "number",
            "What is the highest English score at school B?",
            max(recorded(subject="English", school="B")),
            control_sql="SELECT MAX(score) FROM scores "
            "WHERE subject = 'English' AND school = 'B'",
        ),
        Question(
            "e4",
            files,
            "difference",
            "How much higher was the average Math score in 2024 than in 2023?",
            _rounded(
                _mean(recorded(subject="Math", year=2024))
                - _mean(recorded(subject="Math", year=2023))
            ),
            Decimal("0.005"),
            "SELECT AVG(CASE WHEN year = 2024 THEN score END) "
            "- AVG(CASE WHEN year = 2023 THEN score END) "
            "FROM scores WHERE subject = 'Math'",
        ),
        Question(
            "e5", files, "number", "How many students are struggling?", "AMBIGUOUS"
        ),
        Question(
            "e6",
            files,
            "number",
            "What is the average attendance rate of the students?",
            "UNANSWERABLE",
        ),
    ]
    return scores, questions


def climate(rng: random.Random) -> tuple[list[Record], list[Question]]:
    normals = {"Oslo": 6, "Lima": 19, "Perth": 19, "Cairo": 22}
    readings: list[Record] = []
    for station, normal in normals.items():
        for offset in range(0, 365, 3):
            day = date(2024, 1, 1) + timedelta(days=offset)
            tenths = normal * 10 + rng.randrange(-120, 121)
            readings.append(
                {
                    "station": station,
                    "date": day.isoformat(),
                    "temperature_c": Decimal(tenths) / 10,
                    "rainfall_mm": (
                        None
                        if rng.random() < 0.1
                        else Decimal(rng.randrange(0, 300)) / 10
                    ),
                }
            )

    def values(name: str, station: str) -> list[Decimal]:
        return [
            _dec(row, name)
            for row in readings
            if row["station"] == station and row[name] is not None
        ]

    files = ("readings.jsonl",)
    questions = [
        Question(
            "c1",
            files,
            "number",
            "What is the highest temperature recorded at the Cairo station, in "
            "degrees Celsius?",
            max(values("temperature_c", "Cairo")),
            control_sql="SELECT MAX(temperature_c) FROM readings "
            "WHERE station = 'Cairo'",
        ),
        Question(
            "c2",
            files,
            "number",
            "What is the total recorded rainfall at the Lima station, in millimetres?",
            sum(values("rainfall_mm", "Lima"), Decimal(0)),
            Decimal("0.005"),
            "SELECT SUM(rainfall_mm) FROM readings WHERE station = 'Lima'",
        ),
        Question(
            "c3",
            files,
            "number",
            "On how many of its reading days did Oslo record a temperature below 0 "
            "degrees Celsius?",
            Decimal(sum(1 for value in values("temperature_c", "Oslo") if value < 0)),
            control_sql="SELECT COUNT(*) FROM readings "
            "WHERE station = 'Oslo' AND temperature_c < 0",
        ),
        Question(
            "c4",
            files,
            "difference",
            "How much higher is the average temperature at Perth than at Oslo, in "
            "degrees Celsius?",
            _rounded(
                _mean(values("temperature_c", "Perth"))
                - _mean(values("temperature_c", "Oslo"))
            ),
            Decimal("0.005"),
            "SELECT AVG(CASE WHEN station = 'Perth' THEN temperature_c END) "
            "- AVG(CASE WHEN station = 'Oslo' THEN temperature_c END) FROM readings",
        ),
        Question(
            "c5", files, "number", "On how many days was it hot in Perth?", "AMBIGUOUS"
        ),
        Question(
            "c6",
            files,
            "number",
            "What was the average wind speed at the Cairo station?",
            "UNANSWERABLE",
        ),
    ]
    return readings, questions


def _text(value: object) -> str:
    return "" if value is None else str(value)


def _write_delimited(
    path: Path, header: list[str], rows: Iterable[list[str]], delimiter: str
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _json_value(value: object) -> object:
    # Every generated decimal has at most two places, so a JSON number keeps it.
    return float(value) if isinstance(value, Decimal) else value


def build(root: Path = ROOT) -> list[Question]:
    """Write every data file and questions.csv under ``root``; return the questions."""
    rng = random.Random(SEED)
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)

    visits, health_questions = healthcare(rng)
    (data / "visits.json").write_text(
        json.dumps(
            [{k: _json_value(v) for k, v in row.items()} for row in visits], indent=1
        )
        + "\n",
        encoding="utf-8",
        # The same bytes on every system, so the file and its hash never vary.
        newline="\n",
    )

    orders, customers, retail_questions = retail(rng)
    _write_delimited(
        data / "orders.csv",
        ["order_id", "customer_id", "order_date", "status", "amount"],
        (
            [
                str(row["order_id"]),
                str(row["customer_id"]),
                str(row["order_date"]),
                str(row["status_text"]),
                _money(_dec(row, "amount")),
            ]
            for row in orders
        ),
        ",",
    )
    _write_delimited(
        data / "customers.csv",
        ["customer_id", "region", "segment"],
        (
            [_text(row[k]) for k in ("customer_id", "region", "segment")]
            for row in customers
        ),
        ",",
    )

    runs, factory_questions = manufacturing(rng)
    # Excel cells keep their own types: dates, whole numbers and text.
    pd.DataFrame(runs).to_excel(
        data / "production.xlsx", sheet_name="runs", index=False
    )

    scores, school_questions = education(rng)
    _write_delimited(
        data / "scores.tsv",
        ["student_id", "school", "subject", "year", "score"],
        (
            [
                _text(row[k]) if row[k] is not None else "N/A"
                for k in ("student_id", "school", "subject", "year", "score")
            ]
            for row in scores
        ),
        "\t",
    )

    readings, climate_questions = climate(rng)
    (data / "readings.jsonl").write_text(
        "".join(
            json.dumps({k: _json_value(v) for k, v in row.items()}) + "\n"
            for row in readings
        ),
        encoding="utf-8",
        newline="\n",
    )

    questions = [
        *health_questions,
        *retail_questions,
        *factory_questions,
        *school_questions,
        *climate_questions,
    ]
    _write_delimited(
        root / "questions.csv",
        ["id", "files", "type", "question", "expected", "tolerance"],
        (
            [
                q.question_id,
                ";".join(q.files),
                q.kind,
                q.text,
                str(q.expected),
                str(q.tolerance),
            ]
            for q in questions
        ),
        ",",
    )
    return questions


if __name__ == "__main__":
    built = build()
    answerable = sum(1 for q in built if isinstance(q.expected, Decimal))
    print(f"Wrote {len(built)} questions ({answerable} answerable) under {ROOT}.")
