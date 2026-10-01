"""Column-level profiling for VeriSight."""

import numpy as np
import pandas as pd

from verisight.ingestion.schema import LogicalType
from verisight.profiling.models import (
    ColumnProfile,
    DatetimeStatistics,
    NumericStatistics,
    TextStatistics,
)


class ColumnProfiler:
    """Compute deterministic profiling metrics for a column."""

    def profile(
        self,
        *,
        name: str,
        series: pd.Series,
        logical_type: LogicalType,
    ) -> ColumnProfile:
        """Profile one column without modifying its data."""

        row_count = len(series)
        missing_count = int(series.isna().sum())
        non_missing_count = row_count - missing_count

        missing_ratio = missing_count / row_count if row_count > 0 else 0.0

        non_missing = series.dropna()
        distinct_count = self._count_distinct(non_missing)

        distinct_ratio = (
            distinct_count / non_missing_count if non_missing_count > 0 else 0.0
        )

        minimum: object | None = None
        maximum: object | None = None
        numeric_statistics: NumericStatistics | None = None
        text_statistics: TextStatistics | None = None
        datetime_statistics: DatetimeStatistics | None = None

        if logical_type in {LogicalType.INTEGER, LogicalType.FLOAT}:
            numeric_statistics = self._profile_numeric(non_missing)

            if numeric_statistics is not None:
                minimum = numeric_statistics.minimum
                maximum = numeric_statistics.maximum

        elif logical_type is LogicalType.STRING:
            text_statistics = self._profile_text(non_missing)

        elif logical_type is LogicalType.DATETIME:
            datetime_statistics = self._profile_datetime(non_missing)

            if datetime_statistics is not None:
                minimum = datetime_statistics.earliest
                maximum = datetime_statistics.latest

        return ColumnProfile(
            name=name,
            logical_type=logical_type,
            row_count=row_count,
            non_missing_count=non_missing_count,
            missing_count=missing_count,
            missing_ratio=missing_ratio,
            distinct_count=distinct_count,
            distinct_ratio=distinct_ratio,
            minimum=minimum,
            maximum=maximum,
            numeric_statistics=numeric_statistics,
            text_statistics=text_statistics,
            datetime_statistics=datetime_statistics,
        )

    @staticmethod
    def _profile_numeric(series: pd.Series) -> NumericStatistics | None:
        """Compute descriptive statistics for non-missing numeric values."""

        if series.empty:
            return None

        numeric_values = np.asarray(series, dtype=float)

        finite_mask = np.isfinite(numeric_values)
        finite_series = series.iloc[np.flatnonzero(finite_mask)]
        finite_values = numeric_values[finite_mask]

        non_finite_count = int((~finite_mask).sum())
        non_finite_ratio = non_finite_count / len(numeric_values)

        if finite_values.size == 0:
            return NumericStatistics(
                minimum=None,
                maximum=None,
                mean=None,
                median=None,
                standard_deviation=None,
                non_finite_count=non_finite_count,
                non_finite_ratio=non_finite_ratio,
            )

        minimum = finite_series.min()
        maximum = finite_series.max()

        mean = float(np.mean(finite_values))
        median = float(np.median(finite_values))

        if finite_values.size <= 1:
            standard_deviation = None
        else:
            standard_deviation = float(
                np.std(
                    finite_values,
                    ddof=1,
                )
            )

        return NumericStatistics(
            minimum=minimum,
            maximum=maximum,
            mean=mean,
            median=median,
            standard_deviation=standard_deviation,
            non_finite_count=non_finite_count,
            non_finite_ratio=non_finite_ratio,
        )

    @staticmethod
    def _profile_text(series: pd.Series) -> TextStatistics | None:
        """Compute descriptive statistics for non-missing text values."""

        if series.empty:
            return None

        lengths = series.map(len)

        empty_count = int((lengths == 0).sum())
        value_count = len(series)

        value_counts = series.value_counts(
            dropna=False,
            sort=True,
        )

        most_frequent_value = str(value_counts.index[0])
        most_frequent_count = int(value_counts.iloc[0])
        most_frequent_ratio = most_frequent_count / value_count

        return TextStatistics(
            minimum_length=int(lengths.min()),
            maximum_length=int(lengths.max()),
            mean_length=float(lengths.mean()),
            empty_count=empty_count,
            empty_ratio=empty_count / value_count,
            most_frequent_value=most_frequent_value,
            most_frequent_count=most_frequent_count,
            most_frequent_ratio=most_frequent_ratio,
        )

    @staticmethod
    def _profile_datetime(series: pd.Series) -> DatetimeStatistics | None:
        """Compute descriptive statistics for non-missing datetime values."""

        if series.empty:
            return None

        earliest = pd.Timestamp(series.min())
        latest = pd.Timestamp(series.max())

        timezone = str(earliest.tz) if earliest.tz is not None else None

        return DatetimeStatistics(
            earliest=earliest,
            latest=latest,
            span=latest - earliest,
            timezone=timezone,
        )

    @staticmethod
    def _count_distinct(series: pd.Series) -> int:
        """Count distinct values, including values that are unhashable."""

        try:
            return int(series.nunique(dropna=True))
        except TypeError:
            distinct_values: list[object] = []

            for value in series:
                if not any(
                    ColumnProfiler._values_equal(value, existing)
                    for existing in distinct_values
                ):
                    distinct_values.append(value)

            return len(distinct_values)

    @staticmethod
    def _values_equal(left: object, right: object) -> bool:
        """Return whether two potentially nested values are equal."""

        try:
            result = left == right
        except (TypeError, ValueError):
            return False

        if isinstance(result, bool):
            return result

        return False
