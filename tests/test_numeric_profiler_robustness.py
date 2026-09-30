import math

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


def test_numeric_profile_preserves_negative_infinity() -> None:
    series = pd.Series([float("-inf"), 1.0, 2.0])

    profile = ColumnProfiler().profile(
        name="value",
        series=series,
        logical_type=LogicalType.FLOAT,
    )

    statistics = profile.numeric_statistics
    assert statistics is not None

    assert math.isinf(statistics.minimum)
    assert statistics.minimum < 0
    assert math.isinf(statistics.mean)
    assert statistics.mean < 0
    assert statistics.standard_deviation is None


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
    assert math.isinf(statistics.maximum)
    assert statistics.standard_deviation is None


def test_numeric_profile_with_both_infinities_has_undefined_mean() -> None:
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

    assert math.isinf(statistics.minimum)
    assert statistics.minimum < 0
    assert math.isinf(statistics.maximum)
    assert statistics.maximum > 0
    assert math.isnan(statistics.mean)
    assert statistics.standard_deviation is None


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


def test_nullable_float_with_both_infinities_is_profileable() -> None:
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
    assert statistics.minimum == -np.inf
    assert statistics.maximum == np.inf
    assert np.isnan(statistics.mean)
    assert np.isnan(statistics.median)
    assert statistics.standard_deviation is None
