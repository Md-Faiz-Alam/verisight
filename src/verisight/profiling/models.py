"""Domain models for VeriSight dataset profiling."""

from dataclasses import dataclass
from typing import Any

import pandas as pd

from verisight.ingestion.schema import LogicalType


@dataclass(frozen=True, slots=True)
class NumericStatistics:
    """Descriptive statistics for a numeric column."""

    minimum: float | int
    maximum: float | int
    mean: float
    median: float
    standard_deviation: float | None


@dataclass(frozen=True, slots=True)
class TextStatistics:
    """Descriptive statistics for a text column."""

    minimum_length: int
    maximum_length: int
    mean_length: float
    empty_count: int
    empty_ratio: float
    most_frequent_value: str | None = None
    most_frequent_count: int = 0
    most_frequent_ratio: float = 0.0


@dataclass(frozen=True, slots=True)
class DatetimeStatistics:
    """Descriptive statistics for a datetime column."""

    earliest: pd.Timestamp
    latest: pd.Timestamp
    span: pd.Timedelta
    timezone: str | None


@dataclass(frozen=True, slots=True)
class MissingValueStatistics:
    """Missing-value measurements for a table."""

    total_cell_count: int
    missing_cell_count: int
    missing_cell_ratio: float
    rows_with_missing_count: int
    rows_with_missing_ratio: float
    fully_missing_row_count: int
    fully_missing_row_ratio: float
    columns_with_missing_count: int
    columns_with_missing_ratio: float


@dataclass(frozen=True, slots=True)
class DuplicateStatistics:
    """Duplicate-row measurements for a table."""

    duplicate_row_count: int
    duplicate_row_ratio: float
    duplicate_group_row_count: int
    duplicate_group_row_ratio: float


@dataclass(frozen=True, slots=True)
class ColumnProfile:
    """Observed profiling information for one column."""

    name: str
    logical_type: LogicalType
    row_count: int
    non_missing_count: int
    missing_count: int
    missing_ratio: float
    distinct_count: int
    distinct_ratio: float
    minimum: Any | None = None
    maximum: Any | None = None
    numeric_statistics: NumericStatistics | None = None
    text_statistics: TextStatistics | None = None
    datetime_statistics: DatetimeStatistics | None = None


@dataclass(frozen=True, slots=True)
class TableProfile:
    """Profiling information for one table."""

    name: str
    relation_name: str
    row_count: int
    column_count: int
    columns: tuple[ColumnProfile, ...]
    missing_value_statistics: MissingValueStatistics
    duplicate_statistics: DuplicateStatistics


@dataclass(frozen=True, slots=True)
class DatasetProfile:
    """Profiling information for an ingested dataset."""

    tables: tuple[TableProfile, ...]

    @property
    def table_count(self) -> int:
        """Return the number of profiled tables."""

        return len(self.tables)
