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


def test_numeric_profile_excludes_non_finite_values_from_statistics() -> None:
    series = pd.Series(
        [
            1.0,
            2.0,
            float("inf"),
            float("-inf"),
        ]
    )

    profile = ColumnProfiler().profile(
        name="measurement",
        series=series,
        logical_type=LogicalType.FLOAT,
    )

    statistics = profile.numeric_statistics

    assert statistics is not None

    assert statistics.minimum == 1.0
    assert statistics.maximum == 2.0
    assert statistics.mean == pytest.approx(1.5)
    assert statistics.median == pytest.approx(1.5)
    assert statistics.standard_deviation == pytest.approx(np.sqrt(0.5))
    assert statistics.non_finite_count == 2
    assert statistics.non_finite_ratio == pytest.approx(0.5)

    assert profile.minimum == 1.0
    assert profile.maximum == 2.0


def test_numeric_profile_handles_only_non_finite_values() -> None:
    series = pd.Series(
        [
            float("inf"),
            float("-inf"),
        ]
    )

    profile = ColumnProfiler().profile(
        name="measurement",
        series=series,
        logical_type=LogicalType.FLOAT,
    )

    statistics = profile.numeric_statistics

    assert statistics is not None

    assert statistics.minimum is None
    assert statistics.maximum is None
    assert statistics.mean is None
    assert statistics.median is None
    assert statistics.standard_deviation is None
    assert statistics.non_finite_count == 2
    assert statistics.non_finite_ratio == pytest.approx(1.0)

    assert profile.minimum is None
    assert profile.maximum is None


def test_numeric_profile_distinguishes_missing_and_non_finite_values() -> None:
    series = pd.Series(
        [
            1.0,
            float("inf"),
            None,
            np.nan,
        ]
    )

    profile = ColumnProfiler().profile(
        name="measurement",
        series=series,
        logical_type=LogicalType.FLOAT,
    )

    statistics = profile.numeric_statistics

    assert statistics is not None

    assert profile.row_count == 4
    assert profile.non_missing_count == 2
    assert profile.missing_count == 2
    assert profile.missing_ratio == pytest.approx(0.5)

    assert statistics.minimum == 1.0
    assert statistics.maximum == 1.0
    assert statistics.mean == 1.0
    assert statistics.median == 1.0
    assert statistics.standard_deviation is None
    assert statistics.non_finite_count == 1
    assert statistics.non_finite_ratio == pytest.approx(0.5)
