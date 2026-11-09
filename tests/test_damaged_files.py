"""Damage generated files in known ways and compare the repair with the original."""

import csv
import math
import random
from collections.abc import Callable
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from verisight.config import Settings
from verisight.ingestion.service import DatasetLoader

SETTINGS = Settings(allow_llm_data_disclosure=False, gemini_api_key=None)
HEADER = ["date", "temp_max", "weather", "site"]
NUMBER = "temp_max"
DAY = "date"
TEXT = "weather"
Row = dict[str, str]
Damage = Callable[[str, random.Random], str]


def _clean_rows() -> list[Row]:
    start = date(2012, 1, 1)
    return [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "temp_max": f"{12 * math.sin(i / 9) + 1.5:.1f}",
            "weather": ("rain", "sun", "snow")[i % 3],
            "site": ("north", "south")[i % 2],
        }
        for i in range(200)
    ]


BASE = _clean_rows()


def _write(
    path: Path,
    rows: list[Row],
    *,
    before: tuple[list[str], ...] = (),
    after: tuple[list[str], ...] = (),
    delimiter: str = ",",
    encoding: str = "utf-8",
) -> None:
    with path.open("w", encoding=encoding, newline="") as handle:
        writer = csv.writer(handle, delimiter=delimiter)
        writer.writerows(before)
        writer.writerow(HEADER)
        writer.writerows([row[name] for name in HEADER] for row in rows)
        writer.writerows(after)


def _load(path: Path) -> pd.DataFrame:
    return DatasetLoader(SETTINGS).load([path]).tables[0].data


def _some(damage: Callable[[str], str], share: float = 0.3) -> Damage:
    return lambda value, rng: damage(value) if rng.random() < share else value


def _all(damage: Callable[[str], str]) -> Damage:
    return lambda value, _: damage(value)


def _day(text: str) -> date:
    return date.fromisoformat(text[:10])


def _dates(shape: str) -> Damage:
    return _all(lambda value: _day(value).strftime(shape))


def _thousands(value: str) -> str:
    return f"{float(value) * 1000:,.1f}"


def _european(value: str) -> str:
    written = f"{float(value) * 1000:,.2f}"
    return written.replace(",", "X").replace(".", ",").replace("X", ".")


def _lakh(value: str) -> str:
    return "1,23,456.50" if value == BASE[0][NUMBER] else _thousands(value)


def _mixed_dates(value: str, rng: random.Random) -> str:
    return _day(value).strftime(rng.choice(("%Y-%m-%d", "%Y/%m/%d", "%d-%b-%Y")))


def _negative(shape: str) -> Callable[[str], str]:
    return lambda value: shape.format(value[1:]) if value.startswith("-") else value


# name, damage, multiplier the numbers should end up with
NUMBERS: list[tuple[str, Damage, float | None]] = [
    ("dollar", _all(lambda v: f"${float(v):.2f}"), 1),
    ("dollar_on_some", _some(lambda v: f"${float(v):.2f}"), 1),
    ("rupee", _all(lambda v: f"₹{float(v):.2f}"), 1),
    ("euro_after", _all(lambda v: f"{float(v):.2f} €"), 1),
    ("usd_before", _all(lambda v: f"USD {float(v):.2f}"), 1),
    ("thousands", _all(_thousands), 1000),
    ("european", _all(_european), 1000),
    ("indian_grouping", _all(_lakh), None),
    ("unit", _all(lambda v: f"{v} C"), 1),
    ("percent", _all(lambda v: f"{v}%"), 1),
    ("padded", _all(lambda v: f"  {v} "), 1),
    ("plus_sign", _all(lambda v: f"+{v}" if float(v) > 0 else v), 1),
    ("true_minus", _all(lambda v: v.replace("-", "−")), 1),
    ("trailing_minus", _all(_negative("{}-")), 1),
    ("brackets", _all(_negative("({})")), 1),
]
MARKERS: list[tuple[str, str, float]] = [
    ("n_a", "N/A", 0.1),
    ("dash", "-", 0.1),
    ("question_mark", "?", 0.1),
    ("unknown_word", "unknown", 0.1),
    ("null_word", "NULL", 0.1),
    ("tbd", "TBD", 0.04),
]
DATES: list[tuple[str, Damage]] = [
    ("month_first", _dates("%m/%d/%Y")),
    ("day_first", _dates("%d/%m/%Y")),
    ("short_month", _dates("%d-%b-%Y")),
    ("long_month", _dates("%B %d, %Y")),
    ("year_slashes", _dates("%Y/%m/%d")),
    ("day_dots", _dates("%d.%m.%Y")),
    ("iso_with_zone", _dates("%Y-%m-%dT00:00:00Z")),
    ("mixed_formats", _mixed_dates),
]
LABELS: list[tuple[str, Damage]] = [
    ("upper_case", _some(str.upper)),
    ("padded_labels", _some(lambda v: f" {v}  ")),
]
STRUCTURES: list[tuple[str, dict[str, Any]]] = [
    ("title_rows", {"before": (["Weather report"], ["Generated 2020-01-02"], [])}),
    ("bare_total", {"after": (["Total", "", "", ""],)}),
    ("source_note", {"after": ([], ["Source: national agency"])}),
    ("semicolons", {"delimiter": ";"}),
    ("tabs", {"delimiter": "\t"}),
    ("pipes", {"delimiter": "|"}),
    ("byte_order_mark", {"encoding": "utf-8-sig"}),
    ("latin_1", {"encoding": "latin-1"}),
    ("utf_16", {"encoding": "utf-16"}),
]


def _damaged(column: str, damage: Damage) -> list[Row]:
    rng = random.Random(7)
    return [{**row, column: damage(row[column], rng)} for row in BASE]


@pytest.fixture(scope="module")
def clean(tmp_path_factory: pytest.TempPathFactory) -> pd.DataFrame:
    path = tmp_path_factory.mktemp("clean") / "data.csv"
    _write(path, BASE)
    return _load(path)


def _same_table(frame: pd.DataFrame, clean: pd.DataFrame) -> None:
    assert [str(column) for column in frame.columns] == list(clean.columns)
    assert len(frame) == len(clean)
    for column in clean:
        assert frame[column].astype(str).tolist() == clean[column].astype(str).tolist()


def test_the_suite_covers_the_agreed_damage_types() -> None:
    kinds = (NUMBERS, MARKERS, DATES, LABELS, STRUCTURES)

    # Two more below, and one known limit, make the 43 in docs/system-spec.md.
    assert sum(len(kind) for kind in kinds) == 40


@pytest.mark.parametrize(("name", "damage", "scale"), NUMBERS, ids=lambda v: v)
def test_written_numbers_come_back_exact(
    tmp_path: Path,
    clean: pd.DataFrame,
    name: str,
    damage: Damage,
    scale: float | None,
) -> None:
    path = tmp_path / f"{name}.csv"
    _write(path, _damaged(NUMBER, damage))

    read = _load(path)[NUMBER]

    assert pd.api.types.is_numeric_dtype(read)
    assert int(read.isna().sum()) == 0
    if scale is not None:
        assert (read - clean[NUMBER] * scale).abs().max() < 1e-6


@pytest.mark.parametrize(("name", "marker", "share"), MARKERS, ids=lambda v: v)
def test_placeholders_become_missing_and_nothing_else_does(
    tmp_path: Path, clean: pd.DataFrame, name: str, marker: str, share: float
) -> None:
    rows = _damaged(NUMBER, _some(lambda _: marker, share))
    path = tmp_path / f"{name}.csv"
    _write(path, rows)

    read = _load(path)[NUMBER]

    assert pd.api.types.is_numeric_dtype(read)
    assert int(read.isna().sum()) == sum(row[NUMBER] == marker for row in rows)
    kept = read.notna()
    assert (read[kept] - clean[NUMBER][kept]).abs().max() < 1e-6


@pytest.mark.parametrize(("name", "damage"), DATES, ids=lambda v: v)
def test_written_dates_come_back_exact(
    tmp_path: Path, clean: pd.DataFrame, name: str, damage: Damage
) -> None:
    path = tmp_path / f"{name}.csv"
    _write(path, _damaged(DAY, damage))

    read = _load(path)[DAY]

    assert pd.api.types.is_datetime64_any_dtype(read)
    assert read.dt.date.tolist() == clean[DAY].dt.date.tolist()


@pytest.mark.parametrize(("name", "damage"), LABELS, ids=lambda v: v)
def test_label_variants_keep_their_meaning(
    tmp_path: Path, clean: pd.DataFrame, name: str, damage: Damage
) -> None:
    path = tmp_path / f"{name}.csv"
    _write(path, _damaged(TEXT, damage))

    read = _load(path)[TEXT].astype(str).str.strip().str.casefold().tolist()

    assert read == clean[TEXT].astype(str).str.casefold().tolist()


@pytest.mark.parametrize(("name", "options"), STRUCTURES, ids=lambda v: str(v)[:20])
def test_file_shapes_load_as_the_same_table(
    tmp_path: Path, clean: pd.DataFrame, name: str, options: dict[str, Any]
) -> None:
    path = tmp_path / f"{name}.csv"
    _write(path, BASE, **options)

    _same_table(_load(path), clean)


def test_a_repeated_header_is_not_a_row(tmp_path: Path, clean: pd.DataFrame) -> None:
    path = tmp_path / "data.csv"
    _write(path, [*BASE[:100], dict(zip(HEADER, HEADER, strict=True)), *BASE[100:]])

    _same_table(_load(path), clean)


def test_blank_rows_are_not_rows(tmp_path: Path, clean: pd.DataFrame) -> None:
    rows: list[Row] = []
    for number, row in enumerate(BASE):
        rows.append(row)
        if number % 40 == 20:
            rows.append(dict.fromkeys(HEADER, ""))
    path = tmp_path / "data.csv"
    _write(path, rows)

    _same_table(_load(path), clean)


def _flags(path: Path, column: str) -> list[str]:
    table = DatasetLoader(SETTINGS).load([path]).tables[0]
    return [note.rule for note in table.value_notes if note.column == column]


def test_dates_written_as_eight_digits_are_flagged_not_guessed(tmp_path: Path) -> None:
    """A known limit: 20120101 looks exactly like an identifier."""
    path = tmp_path / "data.csv"
    _write(path, _damaged(DAY, _dates("%Y%m%d")))

    assert pd.api.types.is_numeric_dtype(_load(path)[DAY])
    assert _flags(path, DAY) == ["possible_dates"]


@pytest.mark.parametrize(
    ("column", "values"),
    [
        ("order_id", ["20120101", "20120102", "20120103"]),
        ("amount", ["20121399", "20120102", "20120103"]),
        ("amount", ["5", "6", "7"]),
    ],
    ids=["identifier-name", "not-a-calendar-date", "small-numbers"],
)
def test_ordinary_numbers_are_not_flagged_as_dates(
    tmp_path: Path, column: str, values: list[str]
) -> None:
    path = tmp_path / "data.csv"
    path.write_text(
        f"{column},other\n" + "".join(f"{v},x\n" for v in values), encoding="utf-8"
    )

    assert "possible_dates" not in _flags(path, column)


@pytest.mark.parametrize(
    ("values", "rule"),
    [
        (["03/04/2012", "05/06/2012", "07/08/2012"], "ambiguous_dates"),
        (["10M", "20M", "30M"], "ambiguous_numbers"),
        (["$5.00", "\u20ac6.00", "\u00a37.00"], "mixed_currencies"),
    ],
    ids=["day-or-month", "amount-or-code", "several-currencies"],
)
def test_ambiguous_values_stay_as_loaded_and_are_flagged(
    tmp_path: Path, values: list[str], rule: str
) -> None:
    path = tmp_path / "data.csv"
    path.write_text(
        "reading,other\n" + "".join(f"{v},x\n" for v in values), encoding="utf-8"
    )

    assert _load(path)["reading"].tolist() == values
    assert rule in _flags(path, "reading")


@pytest.mark.parametrize(
    ("column", "values"),
    [
        ("sku", ["$5.00", "\u20ac6.00"]),
        ("reading", ["$5.00", "\u20ac6 apples"]),
        ("reading", ["red", "blue"]),
    ],
    ids=["label-column", "not-only-amounts", "no-currency"],
)
def test_other_text_is_not_flagged_as_mixed_currencies(
    tmp_path: Path, column: str, values: list[str]
) -> None:
    path = tmp_path / "data.csv"
    path.write_text(
        f"{column},other\n" + "".join(f"{v},x\n" for v in values), encoding="utf-8"
    )

    assert "mixed_currencies" not in _flags(path, column)
