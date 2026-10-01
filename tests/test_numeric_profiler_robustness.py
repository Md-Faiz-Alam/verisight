import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_series_equal

from verisight.ingestion.schema import LogicalType
from verisight.profiling.column import ColumnProfiler


def test_profiles_nullable_integer_dtype() -> None:
    series = pd.Series([10, None, 30], dtype="Int64")

    profile = ColumnProfiler().profile(
        name="quantity",
        series=series,
        logical_type=LogicalType.INTEGER,
    )

    statistics = profile.numeric_statistics
    assert statistics is not None

    assert profile.row_count == 3
    assert profile.non_missing_count == 2
    assert profile.missing_count == 1
    assert statistics.minimum == 10
    assert statistics.maximum == 30
    assert statistics.mean == pytest.approx(20.0)
    assert statistics.median == pytest.approx(20.0)
    assert statistics.standard_deviation == pytest.approx(14.1421356)
    assert statistics.non_finite_count == 0
    assert statistics.non_finite_ratio == pytest.approx(0.0)


def test_profiles_nullable_float_dtype() -> None:
    series = pd.Series([1.5, None, 3.5], dtype="Float64")

    profile = ColumnProfiler().profile(
        name="score",
        series=series,
        logical_type=LogicalType.FLOAT,
    )

    statistics = profile.numeric_statistics
    assert statistics is not None

    assert profile.missing_count == 1
    assert statistics.minimum == pytest.approx(1.5)
    assert statistics.maximum == pytest.approx(3.5)
    assert statistics.mean == pytest.approx(2.5)
    assert statistics.median == pytest.approx(2.5)
    assert statistics.standard_deviation == pytest.approx(1.41421356)
    assert statistics.non_finite_count == 0
    assert statistics.non_finite_ratio == pytest.approx(0.0)


def test_profiles_negative_numeric_values() -> None:
    series = pd.Series([-20, -10, 0, 10])

    profile = ColumnProfiler().profile(
        name="change",
        series=series,
        logical_type=LogicalType.INTEGER,
    )

    statistics = profile.numeric_statistics
    assert statistics is not None

    assert statistics.minimum == -20
    assert statistics.maximum == 10
    assert statistics.mean == pytest.approx(-5.0)
    assert statistics.median == pytest.approx(-5.0)
    assert statistics.non_finite_count == 0
    assert statistics.non_finite_ratio == pytest.approx(0.0)


def test_profiles_constant_numeric_column() -> None:
    series = pd.Series([7, 7, 7, 7])

    profile = ColumnProfiler().profile(
        name="constant",
        series=series,
        logical_type=LogicalType.INTEGER,
    )

    statistics = profile.numeric_statistics
    assert statistics is not None

    assert profile.distinct_count == 1
    assert profile.distinct_ratio == pytest.approx(0.25)
    assert statistics.minimum == 7
    assert statistics.maximum == 7
    assert statistics.mean == pytest.approx(7.0)
    assert statistics.median == pytest.approx(7.0)
    assert statistics.standard_deviation == pytest.approx(0.0)
    assert statistics.non_finite_count == 0
    assert statistics.non_finite_ratio == pytest.approx(0.0)


def test_numeric_profile_excludes_negative_infinity() -> None:
    series = pd.Series([float("-inf"), 1.0, 2.0])

    profile = ColumnProfiler().profile(
        name="value",
        series=series,
        logical_type=LogicalType.FLOAT,
    )

    statistics = profile.numeric_statistics
    assert statistics is not None

    assert profile.minimum == pytest.approx(1.0)
    assert profile.maximum == pytest.approx(2.0)

    assert statistics.minimum == pytest.approx(1.0)
    assert statistics.maximum == pytest.approx(2.0)
    assert statistics.mean == pytest.approx(1.5)
    assert statistics.median == pytest.approx(1.5)
    assert statistics.standard_deviation == pytest.approx(0.70710678)
    assert statistics.non_finite_count == 1
    assert statistics.non_finite_ratio == pytest.approx(1 / 3)


def test_numeric_profile_handles_missing_values_with_infinity() -> None:
    series = pd.Series([1.0, None, float("inf"), 3.0])

    profile = ColumnProfiler().profile(
        name="value",
        series=series,
        logical_type=LogicalType.FLOAT,
    )

    statistics = profile.numeric_statistics
    assert statistics is not None

    assert profile.row_count == 4
    assert profile.non_missing_count == 3
    assert profile.missing_count == 1
    assert profile.missing_ratio == pytest.approx(0.25)

    assert profile.minimum == pytest.approx(1.0)
    assert profile.maximum == pytest.approx(3.0)

    assert statistics.minimum == pytest.approx(1.0)
    assert statistics.maximum == pytest.approx(3.0)
    assert statistics.mean == pytest.approx(2.0)
    assert statistics.median == pytest.approx(2.0)
    assert statistics.standard_deviation == pytest.approx(1.41421356)
    assert statistics.non_finite_count == 1
    assert statistics.non_finite_ratio == pytest.approx(1 / 3)


def test_numeric_profile_excludes_both_infinities() -> None:
    series = pd.Series(
        [
            float("-inf"),
            1.0,
            float("inf"),
        ]
    )

    profile = ColumnProfiler().profile(
        name="value",
        series=series,
        logical_type=LogicalType.FLOAT,
    )

    statistics = profile.numeric_statistics
    assert statistics is not None

    assert profile.minimum == pytest.approx(1.0)
    assert profile.maximum == pytest.approx(1.0)

    assert statistics.minimum == pytest.approx(1.0)
    assert statistics.maximum == pytest.approx(1.0)
    assert statistics.mean == pytest.approx(1.0)
    assert statistics.median == pytest.approx(1.0)
    assert statistics.standard_deviation is None
    assert statistics.non_finite_count == 2
    assert statistics.non_finite_ratio == pytest.approx(2 / 3)


def test_numeric_profiling_does_not_mutate_source_series() -> None:
    series = pd.Series(
        [10.0, None, 30.0, float("inf")],
        name="amount",
    )
    original = series.copy(deep=True)

    ColumnProfiler().profile(
        name="amount",
        series=series,
        logical_type=LogicalType.FLOAT,
    )

    assert_series_equal(series, original)


def test_nullable_float_with_only_infinities_is_profileable() -> None:
    series = pd.Series(
        [np.inf, -np.inf, pd.NA],
        dtype="Float64",
    )

    profile = ColumnProfiler().profile(
        name="value",
        series=series,
        logical_type=LogicalType.FLOAT,
    )

    statistics = profile.numeric_statistics
    assert statistics is not None

    assert profile.row_count == 3
    assert profile.non_missing_count == 2
    assert profile.missing_count == 1

    assert profile.minimum is None
    assert profile.maximum is None

    assert statistics.minimum is None
    assert statistics.maximum is None
    assert statistics.mean is None
    assert statistics.median is None
    assert statistics.standard_deviation is None
    assert statistics.non_finite_count == 2
    assert statistics.non_finite_ratio == pytest.approx(1.0)
