"""Build held-out set v4: 30 new questions over five new domains.

Written after the public benchmark's first live run, to measure that run's
follow-up changes on questions nothing was tuned against. It shares no domain,
file or question with the public benchmark. Every expected answer is computed
here, in plain Python with exact decimals, from the generated records, never by
reading the files back. The questions were frozen before VeriSight ever ran on
them; no prompt, rule or code may be changed to pass them.

The files keep real flaws within the documented cleaning rules: currency text,
thousands separators, mixed-case labels and N/A for missing values. Several
questions carry the traps that mislead SQL: a one-to-many join that repeats
rows, label spellings, missing values, month windows, a median, distinct counts,
percentages and signed differences.

Run from the repository root to rebuild the committed files:

    python evaluation/heldout_v4/make_heldout_v4.py
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

import pandas as pd

SEED = 4004
ROOT = Path(__file__).resolve().parent
ZERO = Decimal(0)


@dataclass(frozen=True)
class Question:
    """One question, with the SQL that checks its expected answer."""

    question_id: str
    files: tuple[str, ...]
    kind: str
    text: str
    expected: Decimal | str
    tolerance: Decimal = ZERO
    # Written by hand and run by the tests, never shown to a model.
    control_sql: str | None = None


def _day(rng: random.Random, first: date, last: date) -> date:
    return first + timedelta(days=rng.randrange((last - first).days + 1))


def _money(amount: Decimal) -> str:
    """Write an amount the way exports often do: $1,234.50."""
    return f"${amount:,.2f}"


def _mean(values: Iterable[Decimal]) -> Decimal:
    items = list(values)
    return sum(items, ZERO) / len(items)


def _rounded(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.000001"))


def _write_delimited(
    path: Path, header: list[str], rows: Iterable[list[str]], delimiter: str = ","
) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter, lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)


def _json_value(value: object) -> object:
    # Every generated decimal has at most two places, so a JSON number keeps it.
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _write_text(path: Path, text: str) -> None:
    # The same bytes on every system, so the file and its hash never vary.
    path.write_text(text, encoding="utf-8", newline="\n")


# Logistics: three CSV files; a shipment holds one or more item lines.


@dataclass(frozen=True)
class Shipment:
    shipment_id: str
    carrier_id: str
    ship_date: date
    weight_kg: Decimal
    cost: Decimal
    status: str
    status_text: str


def logistics(rng: random.Random, data: Path) -> list[Question]:
    countries = ["Germany", "France", "Poland", "Spain"]
    carriers = [(f"K{n:02d}", f"Carrier {n}", countries[n % 4]) for n in range(1, 9)]
    spellings = {
        "Delivered": ["Delivered", "delivered", "DELIVERED"],
        "In transit": ["In transit"],
        "Lost": ["Lost"],
    }
    shipments: list[Shipment] = []
    items: list[tuple[str, str, int]] = []
    for number in range(1, 301):
        status = rng.choices(list(spellings), weights=[7, 2, 1])[0]
        shipment = Shipment(
            shipment_id=f"S{number:04d}",
            carrier_id=rng.choice(carriers)[0],
            ship_date=_day(rng, date(2024, 1, 1), date(2024, 6, 30)),
            weight_kg=Decimal(rng.randrange(5, 5001)) / 10,
            cost=Decimal(rng.randrange(500, 90001)) / 100,
            status=status,
            status_text=rng.choice(spellings[status]),
        )
        shipments.append(shipment)
        # Item lines can repeat a SKU, so joining them repeats the shipment.
        for _ in range(rng.randrange(1, 5)):
            sku = rng.choice(["A-100", "B-200", "C-300", "D-400"])
            items.append((shipment.shipment_id, sku, rng.randrange(1, 11)))

    _write_delimited(
        data / "carriers.csv",
        ["carrier_id", "carrier_name", "country"],
        ([*carrier] for carrier in carriers),
    )
    _write_delimited(
        data / "shipments.csv",
        ["shipment_id", "carrier_id", "ship_date", "weight_kg", "cost", "status"],
        (
            [
                s.shipment_id,
                s.carrier_id,
                s.ship_date.isoformat(),
                str(s.weight_kg),
                _money(s.cost),
                s.status_text,
            ]
            for s in shipments
        ),
    )
    _write_delimited(
        data / "shipment_items.csv",
        ["shipment_id", "sku", "quantity"],
        ([shipment_id, sku, str(quantity)] for shipment_id, sku, quantity in items),
    )

    with_a100 = {shipment_id for shipment_id, sku, _ in items if sku == "A-100"}
    german = {carrier_id for carrier_id, _, country in carriers if country == "Germany"}

    def month_costs(month: int) -> list[Decimal]:
        return [s.cost for s in shipments if s.ship_date.month == month]

    return [
        Question(
            "l1",
            ("shipments.csv",),
            "number",
            "How many shipments were delivered, counting every spelling of the "
            "Delivered status?",
            Decimal(sum(1 for s in shipments if s.status == "Delivered")),
            control_sql="SELECT COUNT(*) FROM shipments "
            "WHERE LOWER(TRIM(status)) = 'delivered'",
        ),
        Question(
            "l2",
            ("shipments.csv", "shipment_items.csv"),
            "number",
            "What is the total shipping cost of the shipments that contain at "
            "least one item with SKU A-100?",
            sum((s.cost for s in shipments if s.shipment_id in with_a100), ZERO),
            Decimal("0.005"),
            "SELECT SUM(cost) FROM shipments WHERE shipment_id IN "
            "(SELECT shipment_id FROM shipment_items WHERE sku = 'A-100')",
        ),
        Question(
            "l3",
            ("shipments.csv", "carriers.csv"),
            "number",
            "What is the median weight, in kilograms, of the shipments handled by "
            "carriers based in Germany?",
            Decimal(
                str(
                    statistics.median(
                        s.weight_kg for s in shipments if s.carrier_id in german
                    )
                )
            ),
            Decimal("0.005"),
            "SELECT MEDIAN(s.weight_kg) FROM shipments AS s JOIN carriers AS c "
            "ON s.carrier_id = c.carrier_id WHERE c.country = 'Germany'",
        ),
        Question(
            "l4",
            ("shipments.csv",),
            "difference",
            "What is the average shipping cost of shipments sent in March 2024 "
            "minus the average shipping cost of shipments sent in February 2024?",
            _rounded(_mean(month_costs(3)) - _mean(month_costs(2))),
            Decimal("0.005"),
            "SELECT AVG(CASE WHEN MONTH(ship_date) = 3 THEN cost END) "
            "- AVG(CASE WHEN MONTH(ship_date) = 2 THEN cost END) FROM shipments",
        ),
        Question(
            "l5",
            ("shipments.csv",),
            "number",
            "How many shipments were heavy?",
            "AMBIGUOUS",
        ),
        Question(
            "l6",
            ("shipments.csv",),
            "number",
            "What is the average delivery time of the shipments, in days?",
            "UNANSWERABLE",
        ),
    ]


# Football: one JSON file of matches over two seasons.


@dataclass(frozen=True)
class Match:
    match_id: int
    season: int
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int
    attendance: int | None


def football(rng: random.Random, data: Path) -> list[Question]:
    teams = [
        "Rovers",
        "United",
        "Athletic",
        "City",
        "Wanderers",
        "Albion",
        "Rangers",
        "Town",
        "Harriers",
        "Celtic",
    ]
    matches: list[Match] = []
    for number in range(1, 361):
        home, away = rng.sample(teams, 2)
        matches.append(
            Match(
                match_id=number,
                season=2023 if number <= 180 else 2024,
                home_team=home,
                away_team=away,
                home_goals=rng.choices(range(6), weights=[20, 32, 25, 13, 7, 3])[0],
                away_goals=rng.choices(range(6), weights=[28, 33, 22, 10, 5, 2])[0],
                attendance=None if rng.random() < 0.07 else rng.randrange(5000, 60001),
            )
        )
    _write_text(
        data / "matches.json",
        json.dumps(
            [
                {name: _json_value(value) for name, value in vars(m).items()}
                for m in matches
            ],
            indent=1,
        )
        + "\n",
    )

    def season_attendance(season: int) -> list[Decimal]:
        return [
            Decimal(m.attendance)
            for m in matches
            if m.season == season and m.attendance is not None
        ]

    files = ("matches.json",)
    return [
        Question(
            "f1",
            files,
            "number",
            "How many matches ended in a draw?",
            Decimal(sum(1 for m in matches if m.home_goals == m.away_goals)),
            control_sql="SELECT COUNT(*) FROM matches WHERE home_goals = away_goals",
        ),
        Question(
            "f2",
            files,
            "number",
            "How many goals were scored in total, by both teams, in the 2024 season?",
            Decimal(
                sum(m.home_goals + m.away_goals for m in matches if m.season == 2024)
            ),
            control_sql="SELECT SUM(home_goals + away_goals) FROM matches "
            "WHERE season = 2024",
        ),
        Question(
            "f3",
            files,
            "number",
            "What was the average attendance in the 2023 season, over the matches "
            "with a recorded attendance?",
            _rounded(_mean(season_attendance(2023))),
            Decimal("0.005"),
            "SELECT AVG(attendance) FROM matches WHERE season = 2023",
        ),
        Question(
            "f4",
            files,
            "difference",
            "Over both seasons, what is the number of matches won by the home team "
            "minus the number won by the away team?",
            Decimal(
                sum(1 for m in matches if m.home_goals > m.away_goals)
                - sum(1 for m in matches if m.away_goals > m.home_goals)
            ),
            control_sql="SELECT SUM(CASE WHEN home_goals > away_goals THEN 1 ELSE 0 "
            "END) - SUM(CASE WHEN away_goals > home_goals THEN 1 ELSE 0 END) "
            "FROM matches",
        ),
        Question("f5", files, "number", "How many matches were exciting?", "AMBIGUOUS"),
        Question(
            "f6",
            files,
            "number",
            "How many yellow cards were shown in total?",
            "UNANSWERABLE",
        ),
    ]


# Energy: one Excel sheet of monthly meter readings for 2024.


@dataclass(frozen=True)
class Reading:
    meter_id: str
    region: str
    tariff: str
    reading_month: date
    kwh: Decimal
    outage_minutes: int


def energy(rng: random.Random, data: Path) -> list[Question]:
    regions = ["North", "South", "East", "West"]
    readings: list[Reading] = []
    for number in range(1, 61):
        region = regions[number % 4]
        tariff = rng.choice(["Standard", "Economy"])
        for month in range(1, 13):
            winter = 1.6 if month in (1, 2, 12) else 1.0
            readings.append(
                Reading(
                    meter_id=f"M{number:03d}",
                    region=region,
                    tariff=tariff,
                    reading_month=date(2024, month, 1),
                    kwh=Decimal(int(rng.randrange(800, 4001) * winter)) / 10,
                    outage_minutes=0 if rng.random() >= 0.12 else rng.randrange(5, 301),
                )
            )
    frame = pd.DataFrame([vars(reading) for reading in readings])
    frame["kwh"] = frame["kwh"].astype(float)
    frame["reading_month"] = pd.to_datetime(frame["reading_month"])
    # Excel cells keep their own types: dates, numbers and text.
    frame.to_excel(data / "meters.xlsx", sheet_name="meters", index=False)

    def month_total(month: int) -> Decimal:
        return sum((r.kwh for r in readings if r.reading_month.month == month), ZERO)

    files = ("meters.xlsx",)
    outages = sum(1 for r in readings if r.outage_minutes > 0)
    return [
        Question(
            "g1",
            files,
            "number",
            "What was the total electricity use, in kWh, in the North region?",
            sum((r.kwh for r in readings if r.region == "North"), ZERO),
            Decimal("0.005"),
            "SELECT SUM(kwh) FROM meters WHERE region = 'North'",
        ),
        Question(
            "g2",
            files,
            "number",
            "What percentage of the meter readings reported an outage of more than "
            "0 minutes?",
            _rounded(Decimal(100 * outages) / len(readings)),
            Decimal("0.05"),
            "SELECT 100.0 * SUM(CASE WHEN outage_minutes > 0 THEN 1 ELSE 0 END) "
            "/ COUNT(*) FROM meters",
        ),
        Question(
            "g3",
            files,
            "number",
            "How many different meters are on the Economy tariff?",
            Decimal(len({r.meter_id for r in readings if r.tariff == "Economy"})),
            control_sql="SELECT COUNT(DISTINCT meter_id) FROM meters "
            "WHERE tariff = 'Economy'",
        ),
        Question(
            "g4",
            files,
            "difference",
            "What is the total electricity use, in kWh, in July 2024 minus the total "
            "in January 2024?",
            month_total(7) - month_total(1),
            Decimal("0.005"),
            "SELECT SUM(CASE WHEN MONTH(reading_month) = 7 THEN kwh END) "
            "- SUM(CASE WHEN MONTH(reading_month) = 1 THEN kwh END) FROM meters",
        ),
        Question(
            "g5",
            files,
            "number",
            "How many meters used a lot of electricity?",
            "AMBIGUOUS",
        ),
        Question(
            "g6",
            files,
            "number",
            "What was the average electricity price per kWh?",
            "UNANSWERABLE",
        ),
    ]


# Library: one TSV file of loans; a late fee is N/A when none was charged.


@dataclass(frozen=True)
class Loan:
    loan_id: str
    member_id: str
    genre: str
    genre_text: str
    loan_date: date
    days_borrowed: int
    late_fee: Decimal | None


def library(rng: random.Random, data: Path) -> list[Question]:
    spellings = {
        "Fiction": ["Fiction", "fiction", "FICTION"],
        "Science": ["Science"],
        "History": ["History"],
        "Children": ["Children"],
    }
    loans: list[Loan] = []
    for number in range(1, 401):
        genre = rng.choices(list(spellings), weights=[4, 2, 2, 2])[0]
        days = rng.randrange(1, 61)
        loans.append(
            Loan(
                loan_id=f"L{number:04d}",
                member_id=f"MB{rng.randrange(1, 121):03d}",
                genre=genre,
                genre_text=rng.choice(spellings[genre]),
                loan_date=_day(rng, date(2024, 1, 1), date(2024, 12, 31)),
                days_borrowed=days,
                late_fee=None if days <= 21 else Decimal(rng.randrange(50, 1501)) / 100,
            )
        )
    _write_delimited(
        data / "loans.tsv",
        ["loan_id", "member_id", "genre", "loan_date", "days_borrowed", "late_fee"],
        (
            [
                loan.loan_id,
                loan.member_id,
                loan.genre_text,
                loan.loan_date.isoformat(),
                str(loan.days_borrowed),
                "N/A" if loan.late_fee is None else f"{loan.late_fee:.2f}",
            ]
            for loan in loans
        ),
        "\t",
    )
    files = ("loans.tsv",)
    return [
        Question(
            "b1",
            files,
            "number",
            "How many loans were of Fiction books, counting every spelling of Fiction?",
            Decimal(sum(1 for loan in loans if loan.genre == "Fiction")),
            control_sql="SELECT COUNT(*) FROM loans "
            "WHERE LOWER(TRIM(genre)) = 'fiction'",
        ),
        Question(
            "b2",
            files,
            "number",
            "What is the total of the late fees charged, over the loans that have a "
            "recorded fee?",
            sum((loan.late_fee for loan in loans if loan.late_fee is not None), ZERO),
            Decimal("0.005"),
            "SELECT SUM(late_fee) FROM loans",
        ),
        Question(
            "b3",
            files,
            "number",
            "What is the largest number of days a History book was borrowed for?",
            Decimal(
                max(loan.days_borrowed for loan in loans if loan.genre == "History")
            ),
            control_sql="SELECT MAX(days_borrowed) FROM loans WHERE genre = 'History'",
        ),
        Question(
            "b4",
            files,
            "number",
            "How many different members borrowed at least one book from the "
            "Children genre?",
            Decimal(
                len({loan.member_id for loan in loans if loan.genre == "Children"})
            ),
            control_sql="SELECT COUNT(DISTINCT member_id) FROM loans "
            "WHERE genre = 'Children'",
        ),
        Question(
            "b5",
            files,
            "number",
            "How many members are frequent borrowers?",
            "AMBIGUOUS",
        ),
        Question(
            "b6",
            files,
            "number",
            "What is the average age of the library members?",
            "UNANSWERABLE",
        ),
    ]


# Insurance: one JSONL file of claims; a payout exists only when approved.


@dataclass(frozen=True)
class Claim:
    claim_id: str
    policy_type: str
    filed_date: date
    amount: Decimal
    status: str
    payout: Decimal | None


def insurance(rng: random.Random, data: Path) -> list[Question]:
    claims: list[Claim] = []
    for number in range(1, 351):
        status = rng.choices(["Approved", "Rejected", "Pending"], weights=[5, 3, 2])[0]
        amount = Decimal(rng.randrange(10_000, 2_000_001)) / 100
        payout = None
        if status == "Approved":
            share = Decimal(rng.randrange(50, 101)) / 100
            payout = (amount * share).quantize(Decimal("0.01"))
        claims.append(
            Claim(
                claim_id=f"C{number:04d}",
                policy_type=rng.choice(["Auto", "Home", "Health"]),
                filed_date=_day(rng, date(2024, 1, 1), date(2024, 12, 31)),
                amount=amount,
                status=status,
                payout=payout,
            )
        )
    _write_text(
        data / "claims.jsonl",
        "".join(
            json.dumps({name: _json_value(value) for name, value in vars(c).items()})
            + "\n"
            for c in claims
        ),
    )

    def total(policy_type: str) -> Decimal:
        return sum((c.amount for c in claims if c.policy_type == policy_type), ZERO)

    home = [c for c in claims if c.policy_type == "Home"]
    files = ("claims.jsonl",)
    return [
        Question(
            "i1",
            files,
            "number",
            "How many claims were approved?",
            Decimal(sum(1 for c in claims if c.status == "Approved")),
            control_sql="SELECT COUNT(*) FROM claims WHERE status = 'Approved'",
        ),
        Question(
            "i2",
            files,
            "number",
            "What is the average payout of the approved Auto claims?",
            _rounded(
                _mean(
                    c.payout
                    for c in claims
                    if c.policy_type == "Auto" and c.payout is not None
                )
            ),
            Decimal("0.005"),
            "SELECT AVG(payout) FROM claims "
            "WHERE policy_type = 'Auto' AND status = 'Approved'",
        ),
        Question(
            "i3",
            files,
            "number",
            "What percentage of the Home claims were rejected?",
            _rounded(
                Decimal(100 * sum(1 for c in home if c.status == "Rejected"))
                / len(home)
            ),
            Decimal("0.05"),
            "SELECT 100.0 * SUM(CASE WHEN status = 'Rejected' THEN 1 ELSE 0 END) "
            "/ COUNT(*) FROM claims WHERE policy_type = 'Home'",
        ),
        Question(
            "i4",
            files,
            "difference",
            "What is the total amount claimed on Health policies minus the total "
            "amount claimed on Auto policies?",
            total("Health") - total("Auto"),
            Decimal("0.005"),
            "SELECT SUM(CASE WHEN policy_type = 'Health' THEN amount END) "
            "- SUM(CASE WHEN policy_type = 'Auto' THEN amount END) FROM claims",
        ),
        Question(
            "i5", files, "number", "How many claims were unusually costly?", "AMBIGUOUS"
        ),
        Question(
            "i6",
            files,
            "number",
            "How many of the claims were fraudulent?",
            "UNANSWERABLE",
        ),
    ]


def build(root: Path = ROOT) -> list[Question]:
    """Write every data file and questions.csv under ``root``; return the questions."""
    rng = random.Random(SEED)
    data = root / "data"
    data.mkdir(parents=True, exist_ok=True)
    questions = [
        *logistics(rng, data),
        *football(rng, data),
        *energy(rng, data),
        *library(rng, data),
        *insurance(rng, data),
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
    )
    return questions


if __name__ == "__main__":
    built = build()
    answerable = sum(1 for q in built if isinstance(q.expected, Decimal))
    print(f"Wrote {len(built)} questions ({answerable} answerable) under {ROOT}.")
