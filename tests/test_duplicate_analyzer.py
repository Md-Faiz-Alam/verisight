import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from verisight.profiling.duplicates import DuplicateAnalyzer


def test_analyzes_duplicate_rows() -> None:
    data = pd.DataFrame(
        {
            "id": [1, 1, 1, 2],
            "value": ["A", "A", "A", "B"],
        }
    )

    statistics = DuplicateAnalyzer().analyze(data)

    assert statistics.duplicate_row_count == 2
    assert statistics.duplicate_row_ratio == pytest.approx(0.5)

    assert statistics.duplicate_group_row_count == 3
    assert statistics.duplicate_group_row_ratio == pytest.approx(0.75)


def test_unique_table_has_no_duplicate_rows() -> None:
    data = pd.DataFrame(
        {
            "id": [1, 2, 3],
            "value": ["A", "B", "C"],
        }
    )

    statistics = DuplicateAnalyzer().analyze(data)

    assert statistics.duplicate_row_count == 0
    assert statistics.duplicate_row_ratio == 0.0
    assert statistics.duplicate_group_row_count == 0
    assert statistics.duplicate_group_row_ratio == 0.0


def test_all_identical_rows_are_measured_correctly() -> None:
    data = pd.DataFrame(
        {
            "id": [1, 1, 1, 1],
            "value": ["A", "A", "A", "A"],
        }
    )

    statistics = DuplicateAnalyzer().analyze(data)

    assert statistics.duplicate_row_count == 3
    assert statistics.duplicate_row_ratio == pytest.approx(0.75)

    assert statistics.duplicate_group_row_count == 4
    assert statistics.duplicate_group_row_ratio == 1.0


def test_multiple_duplicate_groups_are_measured_correctly() -> None:
    data = pd.DataFrame(
        {
            "id": [1, 1, 2, 2, 2, 3],
            "value": ["A", "A", "B", "B", "B", "C"],
        }
    )

    statistics = DuplicateAnalyzer().analyze(data)

    assert statistics.duplicate_row_count == 3
    assert statistics.duplicate_row_ratio == pytest.approx(0.5)

    assert statistics.duplicate_group_row_count == 5
    assert statistics.duplicate_group_row_ratio == pytest.approx(5 / 6)


def test_rows_with_matching_missing_values_can_be_duplicates() -> None:
    data = pd.DataFrame(
        {
            "id": [1, 1, 2],
            "value": [None, None, "A"],
        }
    )

    statistics = DuplicateAnalyzer().analyze(data)

    assert statistics.duplicate_row_count == 1
    assert statistics.duplicate_row_ratio == pytest.approx(1 / 3)
    assert statistics.duplicate_group_row_count == 2
    assert statistics.duplicate_group_row_ratio == pytest.approx(2 / 3)


def test_partially_matching_rows_are_not_duplicates() -> None:
    data = pd.DataFrame(
        {
            "id": [1, 1],
            "value": ["A", "B"],
        }
    )

    statistics = DuplicateAnalyzer().analyze(data)

    assert statistics.duplicate_row_count == 0
    assert statistics.duplicate_group_row_count == 0


def test_empty_table_has_no_duplicate_rows() -> None:
    data = pd.DataFrame(
        {
            "id": pd.Series(dtype="int64"),
            "value": pd.Series(dtype="string"),
        }
    )

    statistics = DuplicateAnalyzer().analyze(data)

    assert statistics.duplicate_row_count == 0
    assert statistics.duplicate_row_ratio == 0.0
    assert statistics.duplicate_group_row_count == 0
    assert statistics.duplicate_group_row_ratio == 0.0


def test_zero_column_table_has_no_duplicate_rows() -> None:
    data = pd.DataFrame(index=range(3))

    statistics = DuplicateAnalyzer().analyze(data)

    assert len(data) == 3
    assert statistics.duplicate_row_count == 0
    assert statistics.duplicate_row_ratio == 0.0
    assert statistics.duplicate_group_row_count == 0
    assert statistics.duplicate_group_row_ratio == 0.0


def test_duplicate_analysis_supports_mixed_dtypes() -> None:
    data = pd.DataFrame(
        {
            "integer": [1, 1, 2],
            "text": ["A", "A", "B"],
            "boolean": [True, True, False],
            "datetime": pd.to_datetime(
                [
                    "2026-01-01",
                    "2026-01-01",
                    "2026-01-02",
                ]
            ),
        }
    )

    statistics = DuplicateAnalyzer().analyze(data)

    assert statistics.duplicate_row_count == 1
    assert statistics.duplicate_group_row_count == 2


def test_duplicate_analysis_does_not_mutate_source_dataframe() -> None:
    data = pd.DataFrame(
        {
            "id": [1, 1, 2],
            "value": ["A", "A", "B"],
        }
    )
    original = data.copy(deep=True)

    DuplicateAnalyzer().analyze(data)

    assert_frame_equal(data, original)
