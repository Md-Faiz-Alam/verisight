import pandas as pd
import pytest

from verisight.ingestion.schema import LogicalType
from verisight.profiling.column import ColumnProfiler


def test_profiles_integer_statistics() -> None:
    series = pd.Series([10, 20, 30, 40])

    profile = ColumnProfiler().profile(
        name="amount",
        series=series,
        logical_type=LogicalType.INTEGER,
    )

    assert profile.minimum == 10
    assert profile.maximum == 40

    statistics = profile.numeric_statistics
    assert statistics is not None

    assert statistics.minimum == 10
    assert statistics.maximum == 40
    assert statistics.mean == pytest.approx(25.0)
    assert statistics.median == pytest.approx(25.0)
    assert statistics.standard_deviation == pytest.approx(12.909944)
    assert statistics.non_finite_count == 0
    assert statistics.non_finite_ratio == pytest.approx(0.0)


def test_profiles_float_statistics() -> None:
    series = pd.Series([1.5, 2.5, 3.5])

    profile = ColumnProfiler().profile(
        name="score",
        series=series,
        logical_type=LogicalType.FLOAT,
    )

    statistics = profile.numeric_statistics
    assert statistics is not None

    assert statistics.minimum == pytest.approx(1.5)
    assert statistics.maximum == pytest.approx(3.5)
    assert statistics.mean == pytest.approx(2.5)
    assert statistics.median == pytest.approx(2.5)
    assert statistics.standard_deviation == pytest.approx(1.0)
    assert statistics.non_finite_count == 0
    assert statistics.non_finite_ratio == pytest.approx(0.0)


def test_numeric_statistics_ignore_missing_values() -> None:
    series = pd.Series([10.0, None, 30.0, None])

    profile = ColumnProfiler().profile(
        name="amount",
        series=series,
        logical_type=LogicalType.FLOAT,
    )

    statistics = profile.numeric_statistics
    assert statistics is not None

    assert profile.row_count == 4
    assert profile.non_missing_count == 2
    assert profile.missing_count == 2
    assert profile.missing_ratio == pytest.approx(0.5)

    assert statistics.minimum == pytest.approx(10.0)
    assert statistics.maximum == pytest.approx(30.0)
    assert statistics.mean == pytest.approx(20.0)
    assert statistics.median == pytest.approx(20.0)
    assert statistics.standard_deviation == pytest.approx(14.1421356)
    assert statistics.non_finite_count == 0
    assert statistics.non_finite_ratio == pytest.approx(0.0)


def test_single_numeric_value_has_no_sample_standard_deviation() -> None:
    series = pd.Series([42])

    profile = ColumnProfiler().profile(
        name="value",
        series=series,
        logical_type=LogicalType.INTEGER,
    )

    statistics = profile.numeric_statistics
    assert statistics is not None

    assert statistics.minimum == 42
    assert statistics.maximum == 42
    assert statistics.mean == pytest.approx(42.0)
    assert statistics.median == pytest.approx(42.0)
    assert statistics.standard_deviation is None
    assert statistics.non_finite_count == 0
    assert statistics.non_finite_ratio == pytest.approx(0.0)


def test_all_missing_numeric_column_has_no_numeric_statistics() -> None:
    series = pd.Series([None, None], dtype="Float64")

    profile = ColumnProfiler().profile(
        name="amount",
        series=series,
        logical_type=LogicalType.FLOAT,
    )

    assert profile.row_count == 2
    assert profile.non_missing_count == 0
    assert profile.missing_count == 2
    assert profile.missing_ratio == pytest.approx(1.0)

    assert profile.minimum is None
    assert profile.maximum is None
    assert profile.numeric_statistics is None


def test_empty_numeric_column_has_no_numeric_statistics() -> None:
    series = pd.Series([], dtype="float64")

    profile = ColumnProfiler().profile(
        name="amount",
        series=series,
        logical_type=LogicalType.FLOAT,
    )

    assert profile.row_count == 0
    assert profile.non_missing_count == 0
    assert profile.missing_count == 0
    assert profile.missing_ratio == pytest.approx(0.0)

    assert profile.minimum is None
    assert profile.maximum is None
    assert profile.numeric_statistics is None


def test_boolean_column_does_not_receive_numeric_statistics() -> None:
    series = pd.Series([True, False, True])

    profile = ColumnProfiler().profile(
        name="active",
        series=series,
        logical_type=LogicalType.BOOLEAN,
    )

    assert profile.minimum is None
    assert profile.maximum is None
    assert profile.numeric_statistics is None


def test_numeric_profile_excludes_positive_infinity() -> None:
    series = pd.Series([1.0, 2.0, float("inf")])

    profile = ColumnProfiler().profile(
        name="value",
        series=series,
        logical_type=LogicalType.FLOAT,
    )

    statistics = profile.numeric_statistics
    assert statistics is not None

    assert profile.row_count == 3
    assert profile.non_missing_count == 3
    assert profile.missing_count == 0

    assert profile.minimum == pytest.approx(1.0)
    assert profile.maximum == pytest.approx(2.0)

    assert statistics.minimum == pytest.approx(1.0)
    assert statistics.maximum == pytest.approx(2.0)
    assert statistics.mean == pytest.approx(1.5)
    assert statistics.median == pytest.approx(1.5)
    assert statistics.standard_deviation == pytest.approx(0.70710678)
    assert statistics.non_finite_count == 1
    assert statistics.non_finite_ratio == pytest.approx(1 / 3)
