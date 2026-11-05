"""Detect rows that hold the total of other rows, such as a "Total" category.

Exports often place an aggregate row next to its parts: a "Total" region per
month, or an "All natural disasters" entity per year. Summing every row then
counts each value twice. A category value is reported when, within groups of
rows that share every other non-measure column, its measure equals the sum of
the other rows in nearly every group. Detection is deterministic, reads the
loaded data only, and never changes it.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

import pandas as pd

from verisight.ingestion.models import LoadedTable
from verisight.ingestion.schema import LogicalType, SchemaInferer
from verisight.quality.models import (
    QualityIssue,
    QualityIssueType,
    QualityScope,
    QualitySeverity,
)

MAX_ROWS = 200_000
MAX_CATEGORIES = 1_000
MAX_MEASURES = 20
MAX_INTEGER_KEYS = 10
MIN_GROUP_PARTS = 2
MIN_SINGLE_GROUP_PARTS = 3
MIN_MATCHED_GROUPS = 2
MIN_MATCHED_SHARE = 0.9
RELATIVE_TOLERANCE = 1e-9
# Rows examined across all checks of one table; larger work is skipped.
MAX_ROW_CHECKS = 5_000_000

_NUMERIC = (LogicalType.INTEGER, LogicalType.FLOAT, LogicalType.DECIMAL)
_KEYS = (LogicalType.STRING, LogicalType.BOOLEAN, LogicalType.DATETIME)


class TypedColumn(Protocol):
    """A column name with its inferred logical type."""

    @property
    def name(self) -> str: ...

    @property
    def logical_type(self) -> LogicalType: ...


@dataclass(frozen=True, slots=True)
class TotalRow:
    """A category value whose rows hold the sum of the other rows in a group.

    ``keys`` are the columns that define a group; an empty tuple means the
    whole table is one group. ``matched_groups`` of ``checked_groups`` groups,
    each holding this value once and at least two other rows, matched.
    """

    column: str
    value: str
    measures: tuple[str, ...]
    keys: tuple[str, ...]
    matched_groups: int
    checked_groups: int


def find_total_rows(
    data: pd.DataFrame, columns: Sequence[TypedColumn]
) -> tuple[TotalRow, ...]:
    """Return total rows found in one table, in column and value order.

    Work is bounded: at most MAX_ROW_CHECKS rows are examined in total, and
    a grouping whose groups never hold three rows is skipped without checks.
    """
    if not MIN_SINGLE_GROUP_PARTS < len(data) <= MAX_ROWS:
        return ()
    measures = [c.name for c in columns if c.logical_type in _NUMERIC][:MAX_MEASURES]
    numbers = {name: _numbers(data[name]) for name in measures}
    # An integer key such as a year repeats; amounts that rarely repeat are not keys.
    integers = [
        c.name
        for c in columns
        if c.logical_type is LogicalType.INTEGER
        and data[c.name].nunique(dropna=True) * 3 <= len(data)
    ]
    others = [c.name for c in columns if c.logical_type in _KEYS]
    budget = [MAX_ROW_CHECKS]
    found: list[TotalRow] = []
    for column in columns:
        if column.logical_type is not LogicalType.STRING:
            continue
        if not 2 < data[column.name].nunique(dropna=True) <= MAX_CATEGORIES:
            continue
        base = [name for name in others if name != column.name]
        options = [base] + [[*base, k] for k in integers[:MAX_INTEGER_KEYS]]
        found.extend(
            _column_totals(data, column.name, options, measures, numbers, budget)
        )
    return tuple(found)


def _numbers(series: pd.Series) -> pd.Series:
    """Float values of a numeric column; booleans and other objects are missing."""
    if series.dtype != object:
        return pd.to_numeric(series, errors="coerce").astype(float)
    return pd.Series(
        [
            float(value)
            if isinstance(value, int | float | Decimal) and not isinstance(value, bool)
            else float("nan")
            for value in series
        ],
        index=series.index,
        dtype=float,
    )


def _column_totals(
    data: pd.DataFrame,
    column: str,
    options: Iterable[list[str]],
    measures: list[str],
    numbers: dict[str, pd.Series],
    budget: list[int],
) -> list[TotalRow]:
    """Use the first grouping, fewest keys first, that explains a value."""
    results: dict[str, TotalRow] = {}
    labels = data[column]
    for keys in options:
        # One integer id per group, computed once and reused for each measure.
        groups = (
            data.groupby(keys, dropna=False, sort=False).ngroup()
            if keys
            else pd.Series(0, index=data.index)
        )
        if keys and groups.value_counts().max() <= MIN_GROUP_PARTS:
            continue
        per_value: dict[str, list[tuple[str, int, int]]] = {}
        for measure in measures:
            if measure in keys:
                continue
            budget[0] -= len(data)
            if budget[0] < 0:
                return [results[value] for value in sorted(results)]
            matches = _matches(labels, numbers[measure], groups, single=not keys)
            for value, (matched, checked) in matches.items():
                per_value.setdefault(value, []).append((measure, matched, checked))
        for value, hits in sorted(per_value.items()):
            results.setdefault(
                value,
                TotalRow(
                    column=column,
                    value=value,
                    measures=tuple(measure for measure, _, _ in hits),
                    keys=tuple(keys),
                    matched_groups=min(matched for _, matched, _ in hits),
                    checked_groups=max(checked for _, _, checked in hits),
                ),
            )
    return [results[value] for value in sorted(results)]


def _matches(
    labels: pd.Series, amounts: pd.Series, groups: pd.Series, *, single: bool
) -> dict[str, tuple[int, int]]:
    """Map each qualifying value to (matched groups, checked groups)."""
    frame = pd.DataFrame({"group": groups, "label": labels, "amount": amounts})
    frame = frame.dropna(subset=["label", "amount"])
    if frame.empty:
        return {}
    by_group = frame.groupby("group", sort=False)["amount"]
    size = by_group.transform("size")
    total = by_group.transform("sum")
    repeats = frame.groupby(["group", "label"], sort=False)["amount"].transform("size")
    parts = MIN_SINGLE_GROUP_PARTS if single else MIN_GROUP_PARTS
    amount = frame["amount"]
    checked = (repeats == 1) & (size >= parts + 1)
    tolerance = RELATIVE_TOLERANCE * total.abs().clip(lower=1.0)
    matched = checked & (amount != 0) & ((2 * amount - total).abs() <= tolerance)
    names = frame["label"].astype(str)
    checked_counts = {str(k): int(v) for k, v in names[checked].value_counts().items()}
    matched_counts = {str(k): int(v) for k, v in names[matched].value_counts().items()}
    required = 1 if single else MIN_MATCHED_GROUPS
    return {
        value: (int(count), int(checked_counts[value]))
        for value, count in matched_counts.items()
        if count >= required and count >= MIN_MATCHED_SHARE * checked_counts[value]
    }


def total_row_issues(table: LoadedTable) -> tuple[QualityIssue, ...]:
    """Report each detected total row as a warning on its category column."""
    columns = SchemaInferer().infer_table(table).columns
    issues = []
    for found in find_total_rows(table.data, columns):
        within = f" within each {', '.join(found.keys)}" if found.keys else ""
        issues.append(
            QualityIssue(
                issue_type=QualityIssueType.TOTAL_ROW,
                severity=QualitySeverity.WARNING,
                scope=QualityScope.COLUMN,
                table_name=table.name,
                relation_name=table.relation_name,
                column_name=found.column,
                message=(
                    f"Rows where this column is {found.value!r} hold the total of "
                    f"the other rows for {', '.join(found.measures)}{within}. "
                    "Adding every row counts those amounts twice: use these rows "
                    "for an overall total, and exclude them when adding the other "
                    "values."
                ),
                affected_count=found.matched_groups,
                affected_ratio=found.matched_groups / table.row_count,
                evidence={
                    "value": found.value,
                    "measures": list(found.measures),
                    "keys": list(found.keys),
                    "matched_groups": found.matched_groups,
                    "checked_groups": found.checked_groups,
                },
            )
        )
    return tuple(issues)
