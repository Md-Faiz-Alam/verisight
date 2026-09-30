import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from verisight.profiling.missing import MissingValueAnalyzer


def test_analyzes_table_missing_values() -> None:
    data = pd.DataFrame(
        {
            "a": [1, None, None, None],
            "b": ["x", "y", None, None],
            "c": [10, 20, 30, None],
        }
    )

    statistics = MissingValueAnalyzer().analyze(data)

    assert statistics.total_cell_count == 12
    assert statistics.missing_cell_count == 6
    assert statistics.missing_cell_ratio == pytest.approx(0.5)

    assert statistics.rows_with_missing_count == 3
    assert statistics.rows_with_missing_ratio == pytest.approx(0.75)

    assert statistics.fully_missing_row_count == 1
    assert statistics.fully_missing_row_ratio == pytest.approx(0.25)

    assert statistics.columns_with_missing_count == 3
    assert statistics.columns_with_missing_ratio == pytest.approx(1.0)


def test_complete_table_has_zero_missing_values() -> None:
    data = pd.DataFrame(
        {
            "a": [1, 2],
            "b": ["x", "y"],
        }
    )

    statistics = MissingValueAnalyzer().analyze(data)

    assert statistics.total_cell_count == 4
    assert statistics.missing_cell_count == 0
    assert statistics.missing_cell_ratio == 0.0
    assert statistics.rows_with_missing_count == 0
    assert statistics.rows_with_missing_ratio == 0.0
    assert statistics.fully_missing_row_count == 0
    assert statistics.fully_missing_row_ratio == 0.0
    assert statistics.columns_with_missing_count == 0
    assert statistics.columns_with_missing_ratio == 0.0


def test_empty_table_with_columns_has_zero_missing_values() -> None:
    data = pd.DataFrame(
        {
            "a": pd.Series(dtype="float64"),
            "b": pd.Series(dtype="string"),
        }
    )

    statistics = MissingValueAnalyzer().analyze(data)

    assert statistics.total_cell_count == 0
    assert statistics.missing_cell_count == 0
    assert statistics.missing_cell_ratio == 0.0
    assert statistics.rows_with_missing_count == 0
    assert statistics.rows_with_missing_ratio == 0.0
    assert statistics.fully_missing_row_count == 0
    assert statistics.fully_missing_row_ratio == 0.0
    assert statistics.columns_with_missing_count == 0
    assert statistics.columns_with_missing_ratio == 0.0


def test_zero_column_table_has_zero_missing_values() -> None:
    data = pd.DataFrame(index=range(3))

    statistics = MissingValueAnalyzer().analyze(data)

    assert len(data) == 3
    assert statistics.total_cell_count == 0
    assert statistics.missing_cell_count == 0
    assert statistics.missing_cell_ratio == 0.0
    assert statistics.rows_with_missing_count == 0
    assert statistics.rows_with_missing_ratio == 0.0
    assert statistics.fully_missing_row_count == 0
    assert statistics.fully_missing_row_ratio == 0.0
    assert statistics.columns_with_missing_count == 0
    assert statistics.columns_with_missing_ratio == 0.0


def test_all_missing_table_is_measured_correctly() -> None:
    data = pd.DataFrame(
        {
            "a": [None, None],
            "b": [None, None],
        }
    )

    statistics = MissingValueAnalyzer().analyze(data)

    assert statistics.total_cell_count == 4
    assert statistics.missing_cell_count == 4
    assert statistics.missing_cell_ratio == 1.0
    assert statistics.rows_with_missing_count == 2
    assert statistics.rows_with_missing_ratio == 1.0
    assert statistics.fully_missing_row_count == 2
    assert statistics.fully_missing_row_ratio == 1.0
    assert statistics.columns_with_missing_count == 2
    assert statistics.columns_with_missing_ratio == 1.0


def test_empty_and_whitespace_strings_are_not_missing() -> None:
    data = pd.DataFrame(
        {
            "value": ["", "   ", None],
        }
    )

    statistics = MissingValueAnalyzer().analyze(data)

    assert statistics.total_cell_count == 3
    assert statistics.missing_cell_count == 1
    assert statistics.missing_cell_ratio == pytest.approx(1 / 3)
    assert statistics.rows_with_missing_count == 1


def test_missing_analysis_does_not_mutate_source_dataframe() -> None:
    data = pd.DataFrame(
        {
            "a": [1, None, 3],
            "b": ["x", None, "z"],
        }
    )
    original = data.copy(deep=True)

    MissingValueAnalyzer().analyze(data)

    assert_frame_equal(data, original)
