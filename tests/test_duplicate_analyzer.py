import json
from pathlib import Path

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from verisight import VeriSight
from verisight.config import Settings
from verisight.profiling.duplicates import DuplicateAnalyzer
from verisight.quality.models import QualityIssueType
from verisight.serialization import to_jsonable


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


@pytest.mark.parametrize(
    ("left", "right", "duplicate_count"),
    [
        ([1, 2], [1, 2], 1),
        ([1, 2], [2, 1], 0),
        ({"a": 1, "b": 2}, {"b": 2, "a": 1}, 1),
        ({"tags": ["a", {"x": [None, True]}]}, {"tags": ["a", {"x": [None, True]}]}, 1),
        ([], {}, 0),
        ([1, 2], "[1, 2]", 0),
        ((1, 2), [1, 2], 0),
        (([1], {"a": 2}), ([1], {"a": 2}), 1),
        ({"a": None}, {}, 0),
    ],
)
def test_nested_values_have_structural_duplicate_counts(
    left: object, right: object, duplicate_count: int
) -> None:
    data = pd.DataFrame({"id": [1, 1], "value": [left, right]})
    original = repr(data.to_dict("list"))

    statistics = DuplicateAnalyzer().analyze(data)

    assert statistics.duplicate_row_count == duplicate_count
    assert statistics.duplicate_group_row_count == 2 * duplicate_count
    assert statistics.duplicate_row_ratio == duplicate_count / 2
    assert statistics.duplicate_group_row_ratio == duplicate_count
    assert repr(data.to_dict("list")) == original


def test_nested_duplicates_keep_missing_cell_behavior() -> None:
    data = pd.DataFrame(
        {
            "value": [["a"], ["a"], {"x": None}, {"x": None}],
            "optional": [None, None, float("nan"), float("nan")],
        }
    )

    statistics = DuplicateAnalyzer().analyze(data)

    assert statistics.duplicate_row_count == 2
    assert statistics.duplicate_group_row_count == 4


def test_public_analysis_profiles_nested_json_and_serializes_counts(
    tmp_path: Path,
) -> None:
    path = tmp_path / "events.json"
    records = [
        {"id": 1, "payload": {"tags": ["a", "b"], "meta": {"values": [1, None]}}},
        {"id": 1, "payload": {"meta": {"values": [1, None]}, "tags": ["a", "b"]}},
        {"id": 1, "payload": {"tags": ["b", "a"], "meta": {"values": [1, None]}}},
        {"id": 2, "payload": []},
        {"id": 2, "payload": []},
        {"id": 3, "payload": None},
        {"id": 3, "payload": None},
    ]
    content = json.dumps(records)
    path.write_bytes(content.encode("utf-8"))
    app = VeriSight(
        settings=Settings(gemini_api_key=None, allow_llm_data_disclosure=False)
    )

    result = app.analyze(path)

    statistics = result.analysis.profile.tables[0].duplicate_statistics
    assert statistics is not None
    assert statistics.duplicate_row_count == 3
    assert statistics.duplicate_group_row_count == 6
    assert statistics.duplicate_row_ratio == pytest.approx(3 / 7)
    assert statistics.duplicate_group_row_ratio == pytest.approx(6 / 7)
    duplicate_issue = next(
        issue
        for issue in result.analysis.issues
        if issue.issue_type is QualityIssueType.DUPLICATE_ROWS
    )
    assert duplicate_issue.affected_count == 3
    payload = json.loads(json.dumps(to_jsonable(result)))
    assert (
        payload["analysis"]["profile"]["tables"][0]["duplicate_statistics"][
            "duplicate_row_count"
        ]
        == 3
    )
    assert path.read_bytes() == content.encode("utf-8")
