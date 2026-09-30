import pandas as pd
import pytest
from pandas.testing import assert_series_equal

from verisight.ingestion.schema import LogicalType
from verisight.profiling.column import ColumnProfiler


def test_profiles_most_frequent_text_value() -> None:
    series = pd.Series(["web", "mobile", "web", "web", "store"])

    profile = ColumnProfiler().profile(
        name="channel",
        series=series,
        logical_type=LogicalType.STRING,
    )

    statistics = profile.text_statistics
    assert statistics is not None

    assert statistics.most_frequent_value == "web"
    assert statistics.most_frequent_count == 3
    assert statistics.most_frequent_ratio == pytest.approx(3 / 5)


def test_frequency_ratio_excludes_missing_values() -> None:
    series = pd.Series(["A", None, "A", "B", None])

    profile = ColumnProfiler().profile(
        name="value",
        series=series,
        logical_type=LogicalType.STRING,
    )

    statistics = profile.text_statistics
    assert statistics is not None

    assert profile.non_missing_count == 3
    assert statistics.most_frequent_value == "A"
    assert statistics.most_frequent_count == 2
    assert statistics.most_frequent_ratio == pytest.approx(2 / 3)


def test_empty_string_can_be_most_frequent_value() -> None:
    series = pd.Series(["", "", "A"])

    profile = ColumnProfiler().profile(
        name="value",
        series=series,
        logical_type=LogicalType.STRING,
    )

    statistics = profile.text_statistics
    assert statistics is not None

    assert statistics.most_frequent_value == ""
    assert statistics.most_frequent_count == 2
    assert statistics.most_frequent_ratio == pytest.approx(2 / 3)


def test_profiles_unicode_text() -> None:
    series = pd.Series(["café", "東京", "नमस्ते", "東京"])

    profile = ColumnProfiler().profile(
        name="label",
        series=series,
        logical_type=LogicalType.STRING,
    )

    statistics = profile.text_statistics
    assert statistics is not None

    assert statistics.minimum_length == 2
    assert statistics.maximum_length == 6
    assert statistics.most_frequent_value == "東京"
    assert statistics.most_frequent_count == 2


def test_profiles_pandas_string_dtype() -> None:
    series = pd.Series(
        ["alpha", "beta", None, "alpha"],
        dtype="string",
    )

    profile = ColumnProfiler().profile(
        name="label",
        series=series,
        logical_type=LogicalType.STRING,
    )

    statistics = profile.text_statistics
    assert statistics is not None

    assert profile.non_missing_count == 3
    assert statistics.minimum_length == 4
    assert statistics.maximum_length == 5
    assert statistics.most_frequent_value == "alpha"
    assert statistics.most_frequent_count == 2
    assert statistics.most_frequent_ratio == pytest.approx(2 / 3)


def test_profiles_long_text_without_truncating() -> None:
    long_value = "x" * 10_000
    series = pd.Series([long_value, "short"])

    profile = ColumnProfiler().profile(
        name="description",
        series=series,
        logical_type=LogicalType.STRING,
    )

    statistics = profile.text_statistics
    assert statistics is not None

    assert statistics.maximum_length == 10_000
    assert statistics.minimum_length == 5


def test_case_variants_remain_distinct() -> None:
    series = pd.Series(["Active", "active", "ACTIVE"])

    profile = ColumnProfiler().profile(
        name="status",
        series=series,
        logical_type=LogicalType.STRING,
    )

    assert profile.distinct_count == 3


def test_text_profiling_does_not_mutate_source_series() -> None:
    series = pd.Series(
        ["alpha", None, "", "東京"],
        dtype="string",
        name="label",
    )
    original = series.copy(deep=True)

    ColumnProfiler().profile(
        name="label",
        series=series,
        logical_type=LogicalType.STRING,
    )

    assert_series_equal(series, original)
