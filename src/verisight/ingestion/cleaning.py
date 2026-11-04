"""Conservative, fully reported clean-up of common messy values.

A column changes only when every present value fits one clear pattern, and
each change is recorded as a ``ValueNote``. Anything uncertain stays as loaded.
"""

import re
from collections import defaultdict
from typing import Any

import pandas as pd

from verisight.ingestion.loaders.csv import CsvLoader
from verisight.ingestion.models import LoadedTable, NoteRule, ValueNote
from verisight.ingestion.temporal import parse_iso_datetimes

# Spreadsheet and export placeholders for a missing value. They are treated as
# missing only in a column whose other values are all numbers or ISO dates, so
# a label such as "NA" (North America) in a text column is never removed.
MISSING_MARKERS = frozenset(
    {
        "N/A",
        "n/a",
        "N/a",
        "NA",
        "na",
        "#N/A",
        "null",
        "NULL",
        "Null",
        "None",
        "none",
        "NaN",
        "nan",
        "-",
        "--",
        "?",
    }
)
CURRENCY_SYMBOLS = ("$", "€", "£", "₹", "¥")
_GROUPED = re.compile(r"[+-]?[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?")
_MAX_EXAMPLES = 3
_MAX_SAFE_INTEGER = 2**53 - 1
_MAX_VARIANT_GROUPS = 5


def clean_table(table: LoadedTable) -> None:
    """Trim padded headers, then convert or report messy values in place.

    Notes a loader already recorded, such as generated header names, are kept.
    """
    notes: list[ValueNote] = list(table.value_notes)
    notes.extend(_trim_headers(table))
    for column in table.data.columns:
        notes.extend(_clean_column(table.data, str(column)))
    table.value_notes = tuple(notes)


def _trim_headers(table: LoadedTable) -> list[ValueNote]:
    """Strip outer spaces from names when the result stays distinct."""
    names = [str(column) for column in table.data.columns]
    trimmed = [name.strip() for name in names]
    if trimmed == names:
        return []
    keys = [name.lower() for name in trimmed]
    renames: dict[str, str] = {}
    for original, new, key in zip(names, trimmed, keys, strict=True):
        if new != original and new and keys.count(key) == 1:
            renames[original] = new
    if not renames:
        return []
    table.data = table.data.rename(columns=renames)
    table.validate_column_names()
    return [
        ValueNote(
            column=new,
            rule="trimmed_column_name",
            affected_count=1,
            examples=(original,),
        )
        for original, new in renames.items()
    ]


def _clean_column(data: pd.DataFrame, column: str) -> list[ValueNote]:
    series = data[column]
    if series.dtype != object:
        return []
    present = series.dropna()
    if present.empty:
        return []
    if all(type(value) is str for value in present):
        return _clean_text(data, column, series)
    return _clean_mixed(data, column, series, present)


def _clean_text(data: pd.DataFrame, column: str, series: pd.Series) -> list[ValueNote]:
    markers = series.isin(MISSING_MARKERS)
    candidate = series.mask(markers)
    if candidate.dropna().empty:
        return _label_variants(column, series)
    converted = _parse_text(candidate)
    if converted is None:
        return _label_variants(column, series)
    typed, rule, detail, formatted = converted
    notes: list[ValueNote] = []
    if markers.any():
        notes.append(_note(column, "missing_value_markers", series[markers]))
    if rule is not None:
        notes.append(_note(column, rule, series[formatted], detail))
    if not notes:
        # Plain numbers or dates stored as text are left exactly as loaded.
        return _label_variants(column, series)
    data[column] = typed
    return notes


def _parse_text(
    values: pd.Series,
) -> tuple[pd.Series, NoteRule | None, str | None, pd.Series] | None:
    """Type strings as dates or numbers, removing one consistent format.

    Returns the typed column, the format rule applied, its description, and a
    mask of the values that carried that format.
    """
    present = values.notna()
    none = pd.Series(False, index=values.index)
    dates = parse_iso_datetimes(values)
    if dates is not None:
        return dates, None, None, none
    text = values
    rule: NoteRule | None = None
    detail: str | None = None
    formatted = none
    if all(value.endswith("%") for value in values.dropna()):
        text = text.str.removesuffix("%")
        rule, detail, formatted = (
            "percent_sign",
            "values are percent points; 10% became 10",
            present,
        )
    else:
        symbols = {_currency(value) for value in values.dropna()}
        if len(symbols) == 1 and None not in symbols:
            symbol = next(iter(symbols))
            assert symbol is not None
            text = text.str.replace(symbol, "", n=1, regex=False)
            rule, detail, formatted = "currency_symbol", f"{symbol} removed", present
    grouped = text.str.fullmatch(_GROUPED, na=False).astype(bool)
    if grouped.any():
        text = text.mask(grouped, text.str.replace(",", "", regex=False))
        if rule is None:
            rule, detail, formatted = (
                "thousands_separators",
                "comma group separators removed",
                grouped,
            )
        else:
            detail = f"{detail}; comma group separators removed"
    typed = CsvLoader._infer_safe_column_types(pd.DataFrame({"value": text}))["value"]
    if typed.dtype == object:
        return None
    typed.name = values.name
    return typed, rule, detail, formatted


def _currency(value: str) -> str | None:
    body = value[1:] if value.startswith("-") else value
    for symbol in CURRENCY_SYMBOLS:
        if body.startswith(symbol):
            return symbol
    return None


def _clean_mixed(
    data: pd.DataFrame, column: str, series: pd.Series, present: pd.Series
) -> list[ValueNote]:
    """Numbers mixed only with missing markers, as in spreadsheets and JSON."""
    numbers = [value for value in present if type(value) in (int, float)]
    markers = series.map(lambda value: type(value) is str and value in MISSING_MARKERS)
    if (
        not numbers
        or not markers.any()
        or len(numbers) + int(markers.sum()) != len(present)
        # Integers beyond exact float range keep their exact, untouched values.
        or any(
            type(value) is int and abs(value) > _MAX_SAFE_INTEGER for value in numbers
        )
    ):
        return []
    cleaned = series.mask(markers)
    if all(type(value) is int for value in numbers):
        typed: Any = pd.array(cleaned.tolist(), dtype="Int64")
    else:
        typed = pd.to_numeric(cleaned, errors="raise")
    data[column] = pd.Series(typed, index=series.index, name=series.name)
    return [_note(column, "missing_value_markers", series[markers])]


def _label_variants(column: str, series: pd.Series) -> list[ValueNote]:
    """Report labels that differ only by letter case or outer spaces."""
    spellings: dict[str, set[str]] = defaultdict(set)
    for value in series.dropna():
        spellings[value.strip().casefold()].add(value)
    groups = [sorted(group) for group in spellings.values() if len(group) > 1]
    if not groups:
        return []
    affected = series.isin({value for group in groups for value in group})
    examples = tuple(
        " / ".join(repr(value) for value in group[:_MAX_EXAMPLES])
        for group in groups[:_MAX_VARIANT_GROUPS]
    )
    return [
        ValueNote(
            column=column,
            rule="label_variants",
            affected_count=int(affected.sum()),
            examples=examples,
            detail="values differ only by letter case or surrounding spaces",
        )
    ]


def _note(
    column: str, rule: NoteRule, values: pd.Series, detail: str | None = None
) -> ValueNote:
    unique = list(dict.fromkeys(str(value) for value in values))
    return ValueNote(
        column=column,
        rule=rule,
        affected_count=len(values),
        examples=tuple(unique[:_MAX_EXAMPLES]),
        detail=detail,
    )
