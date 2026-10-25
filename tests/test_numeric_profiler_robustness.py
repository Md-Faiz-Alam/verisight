import json
import math
import sys
import warnings
from decimal import Decimal, localcontext
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_series_equal

from verisight import VeriSight
from verisight.config import Settings
from verisight.ingestion.schema import LogicalType
from verisight.profiling.column import ColumnProfiler
from verisight.serialization import to_jsonable


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
    assert not statistics.standard_deviation_overflow
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
    assert not statistics.standard_deviation_overflow
    assert statistics.non_finite_count == 2
    assert statistics.non_finite_ratio == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("values", "expected_mean", "expected_median", "expected_deviation"),
    [
        ([1e308, 1e308], "1e308", "1e308", "0"),
        ([-1e308, -1e308], "-1e308", "-1e308", "0"),
        ([1e308, -1e308], "0", "0", "sqrt2_large"),
        ([1e-300, -1e-300], "0", "0", "sqrt2_small"),
        ([5e-324, 5e-324], "5e-324", "5e-324", "0"),
        ([0.0, 5e-324], "0", "0", "5e-324"),
        ([1e308, 1.0, -1e308], "one_third", "1", "1e308"),
        ([sys.float_info.max], str(sys.float_info.max), str(sys.float_info.max), None),
        ([0.0, 0.0], "0", "0", "0"),
    ],
    ids=[
        "large-positive-constant",
        "large-negative-constant",
        "large-opposite-signs",
        "tiny-opposite-signs",
        "constant-subnormal",
        "subnormal-spread",
        "cancelling-sum",
        "single-maximum",
        "zeros",
    ],
)
def test_finite_statistics_avoid_intermediate_overflow_and_underflow(
    values: list[float],
    expected_mean: str,
    expected_median: str,
    expected_deviation: str | None,
) -> None:
    with localcontext() as context:
        context.prec = 80
        constants = {
            "sqrt2_large": Decimal(2).sqrt() * Decimal("1e308"),
            "sqrt2_small": Decimal(2).sqrt() * Decimal("1e-300"),
            "one_third": Decimal(1) / Decimal(3),
        }

    def expected_float(value: str) -> float:
        return float(constants[value] if value in constants else Decimal(value))

    series = pd.Series(values, dtype="float64")
    original = series.copy(deep=True)
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        profile = ColumnProfiler().profile(
            name="measurement", series=series, logical_type=LogicalType.FLOAT
        )
    statistics = profile.numeric_statistics
    assert statistics is not None
    assert statistics.minimum == min(values)
    assert statistics.maximum == max(values)
    assert statistics.mean is not None
    assert math.isclose(
        statistics.mean, expected_float(expected_mean), rel_tol=1e-15, abs_tol=0.0
    )
    assert statistics.median is not None
    assert statistics.median == expected_float(expected_median)
    if expected_deviation is None:
        assert statistics.standard_deviation is None
    else:
        assert statistics.standard_deviation is not None
        assert math.isclose(
            statistics.standard_deviation,
            expected_float(expected_deviation),
            rel_tol=1e-15,
            abs_tol=0.0,
        )
    assert statistics.non_finite_count == 0
    assert statistics.non_finite_ratio == 0.0
    assert not statistics.standard_deviation_overflow
    assert_series_equal(series, original)


@pytest.mark.parametrize("overflow", [False, True], ids=["representable", "overflow"])
def test_extreme_csv_statistics_have_explicit_json_results(
    tmp_path: Path, overflow: bool
) -> None:
    path = tmp_path / "measurements.csv"
    maximum = str(sys.float_info.max)
    content = (
        f"measurement\n{maximum}\n-{maximum}\n"
        if overflow
        else "measurement\n1e308\n1e308\n"
    )
    path.write_text(content, encoding="utf-8")
    app = VeriSight(
        settings=Settings(gemini_api_key=None, allow_llm_data_disclosure=False)
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        result = app.analyze(path)
    statistics = result.analysis.profile.tables[0].columns[0].numeric_statistics
    assert statistics is not None
    assert statistics.mean == (0.0 if overflow else 1e308)
    assert statistics.median == (0.0 if overflow else 1e308)
    assert (
        statistics.standard_deviation is None
        if overflow
        else (statistics.standard_deviation == 0.0)
    )
    assert statistics.standard_deviation_overflow is overflow
    assert statistics.non_finite_count == 0
    assert statistics.non_finite_ratio == 0.0
    serialized = json.loads(json.dumps(to_jsonable(result), allow_nan=False))
    exported = serialized["analysis"]["profile"]["tables"][0]["columns"][0][
        "numeric_statistics"
    ]
    assert exported["mean"] == statistics.mean
    assert exported["median"] == statistics.median
    assert exported["standard_deviation"] == statistics.standard_deviation
    assert exported["standard_deviation_overflow"] is overflow
    assert path.read_text(encoding="utf-8") == content
