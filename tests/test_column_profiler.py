import numpy as np
import pandas as pd
import pytest

from verisight.ingestion.schema import LogicalType
from verisight.profiling.column import ColumnProfiler


class RaisesOnEquality:
    """Value whose equality comparison raises ValueError."""

    def __eq__(self, other: object) -> bool:
        raise ValueError("values cannot be compared")


def test_profiles_complete_column() -> None:
    series = pd.Series([10, 20, 30])

    profile = ColumnProfiler().profile(
        name="amount",
        series=series,
        logical_type=LogicalType.INTEGER,
    )

    assert profile.name == "amount"
    assert profile.logical_type is LogicalType.INTEGER
    assert profile.row_count == 3
    assert profile.non_missing_count == 3
    assert profile.missing_count == 0
    assert profile.missing_ratio == 0.0
    assert profile.distinct_count == 3
    assert profile.distinct_ratio == 1.0


def test_profiles_missing_values() -> None:
    series = pd.Series(["A", None, "B", None])

    profile = ColumnProfiler().profile(
        name="segment",
        series=series,
        logical_type=LogicalType.STRING,
    )

    assert profile.row_count == 4
    assert profile.non_missing_count == 2
    assert profile.missing_count == 2
    assert profile.missing_ratio == pytest.approx(0.5)
    assert profile.distinct_count == 2
    assert profile.distinct_ratio == pytest.approx(1.0)


def test_distinct_ratio_uses_non_missing_values() -> None:
    series = pd.Series(["A", "A", "B", None])

    profile = ColumnProfiler().profile(
        name="segment",
        series=series,
        logical_type=LogicalType.STRING,
    )

    assert profile.non_missing_count == 3
    assert profile.distinct_count == 2
    assert profile.distinct_ratio == pytest.approx(2 / 3)


def test_profiles_all_missing_column() -> None:
    series = pd.Series([None, None, None], dtype="object")

    profile = ColumnProfiler().profile(
        name="unknown",
        series=series,
        logical_type=LogicalType.UNKNOWN,
    )

    assert profile.row_count == 3
    assert profile.non_missing_count == 0
    assert profile.missing_count == 3
    assert profile.missing_ratio == pytest.approx(1.0)
    assert profile.distinct_count == 0
    assert profile.distinct_ratio == 0.0


def test_profiles_empty_column() -> None:
    series = pd.Series([], dtype="object")

    profile = ColumnProfiler().profile(
        name="empty",
        series=series,
        logical_type=LogicalType.UNKNOWN,
    )

    assert profile.row_count == 0
    assert profile.non_missing_count == 0
    assert profile.missing_count == 0
    assert profile.missing_ratio == 0.0
    assert profile.distinct_count == 0
    assert profile.distinct_ratio == 0.0


def test_counts_duplicate_values_once() -> None:
    series = pd.Series(["A", "A", "B", "B", "B"])

    profile = ColumnProfiler().profile(
        name="category",
        series=series,
        logical_type=LogicalType.STRING,
    )

    assert profile.row_count == 5
    assert profile.distinct_count == 2
    assert profile.distinct_ratio == pytest.approx(0.4)


def test_profiles_unhashable_dictionary_values() -> None:
    series = pd.Series(
        [
            {"source": "web"},
            {"source": "web"},
            {"source": "mobile"},
        ]
    )

    profile = ColumnProfiler().profile(
        name="metadata",
        series=series,
        logical_type=LogicalType.UNKNOWN,
    )

    assert profile.row_count == 3
    assert profile.non_missing_count == 3
    assert profile.distinct_count == 2
    assert profile.distinct_ratio == pytest.approx(2 / 3)


def test_values_equal_returns_false_when_comparison_raises() -> None:
    left = RaisesOnEquality()
    right = RaisesOnEquality()

    assert ColumnProfiler._values_equal(left, right) is False


def test_values_equal_returns_false_for_non_boolean_result() -> None:
    left = np.array([1, 2])
    right = np.array([1, 2])

    assert ColumnProfiler._values_equal(left, right) is False


def test_non_numeric_profile_does_not_compute_numeric_statistics() -> None:
    series = pd.Series(["A", "B", "C"])

    profile = ColumnProfiler().profile(
        name="segment",
        series=series,
        logical_type=LogicalType.STRING,
    )

    assert profile.minimum is None
    assert profile.maximum is None
    assert profile.numeric_statistics is None
