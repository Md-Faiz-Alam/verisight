"""Remove summary rows that exports leave at the end of a table.

A last row labelled "Total" counts every amount twice, and a label in a date
column turns the whole column into text. A row is removed only when its label
says it is a summary and one of its numbers really is the total or average of
the rows above it. A row that only looks like a summary stays.
"""

import re
from decimal import Decimal, InvalidOperation
from math import isfinite
from numbers import Number

import numpy as np
import pandas as pd

from verisight.ingestion.loaders.csv import CsvLoader
from verisight.ingestion.models import LoadedTable, NoteRule, ValueNote

_MAX_FOOTER_ROWS = 3
_MIN_BODY_ROWS = 3
_MIN_NUMERIC_SHARE = 0.9
_RELATIVE_TOLERANCE = 1e-6
_LABEL = re.compile(
    r"(?:grand\s*|sub\s*|overall\s*)?totals?(?:\s.*)?|sum|average|mean", re.IGNORECASE
)
_SYMBOLS = re.compile(r"[$€£₹¥,%\s]")
_NOTE = re.compile(
    r"(?:sources?|notes?|copyright|disclaimer|generated|prepared|compiled)\b.*"
    r"|[*†©].*",
    re.IGNORECASE,
)
_MIN_REPEATED_NAMES = 2
_MIN_COLUMNS = 2


def _number(value: object) -> float | None:
    """Read a number, or a number still written with currency or separators."""
    if isinstance(value, Number) and not isinstance(value, bool | np.bool_):
        number = float(value)  # type: ignore[arg-type]
        return number if isfinite(number) else None
    if type(value) is not str:
        return None
    text = _SYMBOLS.sub("", value)
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    try:
        number = float(Decimal(text))
    except InvalidOperation:
        return None
    return number if isfinite(number) else None


def _label_in(row: pd.Series) -> tuple[str, str] | None:
    for column, value in row.items():
        if type(value) is str and _LABEL.fullmatch(value.strip()):
            return str(column), value
    return None


def _is_summary(row: pd.Series, label: tuple[str, str], body: pd.DataFrame) -> bool:
    """Whether a number in the row equals the sum or mean of that column above."""
    averaged = label[1].strip().casefold() in ("average", "mean")
    for column, value in row.items():
        number = _number(value)
        if str(column) == label[0] or number is None or number == 0:
            continue
        above = [item for item in map(_number, body[column]) if item is not None]
        if len(above) < _MIN_NUMERIC_SHARE * len(body):
            continue
        expected = sum(above) / len(above) if averaged else sum(above)
        if abs(number - expected) <= _RELATIVE_TOLERANCE * max(abs(expected), 1.0):
            return True
    return False


def _retyped(table: LoadedTable, data: pd.DataFrame) -> pd.DataFrame:
    """Columns the summary row forced to text can be typed once it is gone."""
    if table.source.csv_delimiter is None:
        return data.infer_objects()
    objects = data.select_dtypes(include=object).copy()
    typed = CsvLoader._infer_safe_column_types(objects)
    for column in typed.columns:
        data[column] = typed[column]
    return data


def _blank_cells(data: pd.DataFrame) -> pd.DataFrame:
    blank = data.isna()
    for column in data.select_dtypes(include=object):
        spaces = data[column].map(lambda v: type(v) is str and not v.strip())
        blank[column] = blank[column] | spaces.astype(bool)
    return blank


def _repeats_header(data: pd.DataFrame, blank: pd.DataFrame, position: int) -> bool:
    filled = [c for c in data.columns if not blank.iloc[position][c]]
    return len(filled) >= _MIN_REPEATED_NAMES and all(
        str(data.iloc[position][c]).strip().casefold() == str(c).strip().casefold()
        for c in filled
    )


def _repeated_headers(data: pd.DataFrame, blank: pd.DataFrame) -> list[int]:
    first = data.columns[0]
    name = str(first).strip().casefold()
    same = data[first].astype(str).str.strip().str.casefold().eq(name)
    return [
        int(p) for p in np.flatnonzero(same) if _repeats_header(data, blank, int(p))
    ]


def _trailing_notes(
    data: pd.DataFrame, blank: pd.DataFrame, candidates: list[int]
) -> list[int]:
    """Last rows holding only a note or a bare summary label, and nothing else."""
    found: list[int] = []
    for position in reversed(candidates[-_MAX_FOOTER_ROWS:]):
        cells = data.iloc[position][~blank.iloc[position]]
        text = cells.iloc[0] if len(cells) == 1 else None
        if type(text) is not str or not (
            _NOTE.fullmatch(text.strip()) or _LABEL.fullmatch(text.strip())
        ):
            break
        found.append(position)
    return [] if len(candidates) - len(found) < _MIN_BODY_ROWS else found


def _counted(
    rule: NoteRule, rows: list[int], examples: tuple[str, ...]
) -> tuple[NoteRule, int, tuple[str, ...]]:
    return rule, len(rows), examples


def remove_non_data_rows(table: LoadedTable) -> list[ValueNote]:
    """Drop blank rows, repeated headers and closing notes, and report each kind.

    A table of one column is left alone: an empty cell there is a missing value.
    """
    data = table.data
    if data.shape[1] < _MIN_COLUMNS or data.empty:
        return []
    blank = _blank_cells(data)
    empty = [int(p) for p in np.flatnonzero(blank.all(axis=1))]
    if len(empty) == len(data):
        return []
    headers = _repeated_headers(data, blank)
    gone = {*empty, *headers}
    remaining = [p for p in range(len(data)) if p not in gone]
    notes = _trailing_notes(data, blank, remaining)
    if not gone and not notes:
        return []
    first = str(data.columns[0])
    written = [str(data.iloc[p][~blank.iloc[p]].iloc[0]) for p in notes]
    found: tuple[tuple[NoteRule, list[int], tuple[str, ...]], ...] = (
        ("blank_rows", empty, ("blank row",)),
        ("repeated_header_rows", headers, (first,)),
        ("note_rows", notes, tuple(written[:3])),
    )
    report = [
        ValueNote(first, *_counted(rule, rows, text))
        for rule, rows, text in found
        if rows
    ]
    kept = data.drop(index=data.index[[*gone, *notes]]).reset_index(drop=True)
    table.data = _retyped(table, kept)
    return report


def remove_footer_rows(table: LoadedTable) -> list[ValueNote]:
    """Drop labelled summary rows from the end of a table and report each one."""
    data = table.data
    labelled: dict[int, tuple[str, str]] = {}
    for position in range(len(data) - 1, len(data) - 1 - _MAX_FOOTER_ROWS, -1):
        found = None if position < 0 else _label_in(data.iloc[position])
        if found is None:
            break
        labelled[position] = found
    if not labelled or min(labelled) < _MIN_BODY_ROWS:
        return []
    body = data.iloc[: min(labelled)]
    removed = {
        position: label
        for position, label in labelled.items()
        if _is_summary(data.iloc[position], label, body)
    }
    if not removed:
        return []
    kept = data.drop(index=data.index[list(removed)]).reset_index(drop=True)
    table.data = _retyped(table, kept)
    return [
        ValueNote(
            column=column,
            rule="footer_total_rows",
            affected_count=1,
            examples=(text,),
            detail="row removed; a number in it matched the rows above",
        )
        for column, text in removed.values()
    ]
