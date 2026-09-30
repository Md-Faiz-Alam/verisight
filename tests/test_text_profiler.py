import pandas as pd
import pytest

from verisight.ingestion.schema import LogicalType
from verisight.profiling.column import ColumnProfiler


def test_profiles_text_lengths() -> None:
    series = pd.Series(["A", "Alice", "Bob"])

    profile = ColumnProfiler().profile(
        name="name",
        series=series,
        logical_type=LogicalType.STRING,
    )

    statistics = profile.text_statistics
    assert statistics is not None

    assert statistics.minimum_length == 1
    assert statistics.maximum_length == 5
    assert statistics.mean_length == pytest.approx(3.0)
    assert statistics.empty_count == 0
    assert statistics.empty_ratio == 0.0


def test_text_statistics_ignore_missing_values() -> None:
    series = pd.Series(["A", None, "ABC", None])

    profile = ColumnProfiler().profile(
        name="code",
        series=series,
        logical_type=LogicalType.STRING,
    )

    statistics = profile.text_statistics
    assert statistics is not None

    assert profile.row_count == 4
    assert profile.non_missing_count == 2
    assert profile.missing_count == 2

    assert statistics.minimum_length == 1
    assert statistics.maximum_length == 3
    assert statistics.mean_length == pytest.approx(2.0)


def test_profiles_empty_strings_separately_from_missing_values() -> None:
    series = pd.Series(["", "A", "", None])

    profile = ColumnProfiler().profile(
        name="value",
        series=series,
        logical_type=LogicalType.STRING,
    )

    statistics = profile.text_statistics
    assert statistics is not None

    assert profile.missing_count == 1
    assert profile.non_missing_count == 3

    assert statistics.minimum_length == 0
    assert statistics.maximum_length == 1
    assert statistics.empty_count == 2
    assert statistics.empty_ratio == pytest.approx(2 / 3)


def test_whitespace_only_string_is_not_treated_as_empty() -> None:
    series = pd.Series(["", "   ", "A"])

    profile = ColumnProfiler().profile(
        name="value",
        series=series,
        logical_type=LogicalType.STRING,
    )

    statistics = profile.text_statistics
    assert statistics is not None

    assert statistics.minimum_length == 0
    assert statistics.maximum_length == 3
    assert statistics.empty_count == 1
    assert statistics.empty_ratio == pytest.approx(1 / 3)


def test_all_missing_string_column_has_no_text_statistics() -> None:
    series = pd.Series([None, None], dtype="string")

    profile = ColumnProfiler().profile(
        name="description",
        series=series,
        logical_type=LogicalType.STRING,
    )

    assert profile.text_statistics is None


def test_empty_string_column_has_no_text_statistics() -> None:
    series = pd.Series([], dtype="string")

    profile = ColumnProfiler().profile(
        name="description",
        series=series,
        logical_type=LogicalType.STRING,
    )

    assert profile.text_statistics is None


def test_numeric_column_does_not_receive_text_statistics() -> None:
    series = pd.Series([10, 20, 30])

    profile = ColumnProfiler().profile(
        name="amount",
        series=series,
        logical_type=LogicalType.INTEGER,
    )

    assert profile.text_statistics is None


def test_text_profile_does_not_compute_numeric_statistics() -> None:
    series = pd.Series(["10", "20", "30"])

    profile = ColumnProfiler().profile(
        name="code",
        series=series,
        logical_type=LogicalType.STRING,
    )

    assert profile.text_statistics is not None
    assert profile.numeric_statistics is None
