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
from verisight.ingestion.models import LoadedTable, ValueNote

_MAX_FOOTER_ROWS = 3
_MIN_BODY_ROWS = 3
_MIN_NUMERIC_SHARE = 0.9
_RELATIVE_TOLERANCE = 1e-6
_LABEL = re.compile(
    r"(?:grand\s*|sub\s*|overall\s*)?totals?(?:\s.*)?|sum|average|mean", re.IGNORECASE
)
_SYMBOLS = re.compile(r"[$€£₹¥,%\s]")


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
