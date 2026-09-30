from pathlib import Path

import numpy as np
import pandas as pd

from verisight.ingestion.models import (
    LoadedDataset,
    LoadedTable,
    SourceMetadata,
)
from verisight.ingestion.schema import LogicalType, SchemaInferer, TableSchema
from verisight.profiling.dataset import DatasetProfiler
from verisight.profiling.models import TableProfile
from verisight.quality.models import QualityIssueType
from verisight.quality.rules import QualityRuleEngine


def make_table(
    *,
    name: str,
    data: pd.DataFrame,
) -> LoadedTable:
    """Create a loaded table for messy-data profiling tests."""

    source = SourceMetadata(
        path=Path(f"{name}.csv"),
        file_name=f"{name}.csv",
        file_extension=".csv",
        file_size_bytes=1,
    )

    return LoadedTable(
        name=name,
        data=data,
        source=source,
    )


def profile_table(
    *,
    name: str,
    data: pd.DataFrame,
) -> tuple[TableSchema, TableProfile]:
    """Run data through schema inference and dataset profiling."""

    table = make_table(
        name=name,
        data=data,
    )
    dataset = LoadedDataset(tables=[table])

    schema = SchemaInferer().infer_dataset(dataset)

    dataset_profile = DatasetProfiler().profile(
        dataset=dataset,
        schema=schema,
    )

    return schema.tables[0], dataset_profile.tables[0]


def test_profiles_realistically_messy_table() -> None:
    data = pd.DataFrame(
        {
            "record_id": pd.Series(
                [1, 2, 3, 4, 5],
                dtype="Int64",
            ),
            "amount": pd.Series(
                [10.5, None, np.inf, -5.0, 10.5],
                dtype="Float64",
            ),
            "name": pd.Series(
                ["Ada", "", "   ", "José", None],
                dtype="string",
            ),
            "active": pd.Series(
                [True, False, None, True, False],
                dtype="boolean",
            ),
            "created_at": pd.Series(
                [
                    pd.Timestamp("2026-01-01"),
                    pd.Timestamp("2026-01-02"),
                    pd.NaT,
                    pd.Timestamp("2026-01-04"),
                    pd.Timestamp("2026-01-05"),
                ],
                dtype="datetime64[ns]",
            ),
        }
    )

    schema, profile = profile_table(
        name="records",
        data=data,
    )

    assert profile.row_count == 5
    assert profile.column_count == 5

    assert tuple(column.logical_type for column in schema.columns) == (
        LogicalType.INTEGER,
        LogicalType.FLOAT,
        LogicalType.STRING,
        LogicalType.BOOLEAN,
        LogicalType.DATETIME,
    )

    amount = profile.columns[1]

    assert amount.missing_count == 1
    assert amount.numeric_statistics is not None
    assert amount.numeric_statistics.maximum == np.inf

    name = profile.columns[2]

    assert name.missing_count == 1
    assert name.text_statistics is not None
    assert name.text_statistics.empty_count == 1

    active = profile.columns[3]

    assert active.logical_type is LogicalType.BOOLEAN
    assert active.missing_count == 1

    created_at = profile.columns[4]

    assert created_at.datetime_statistics is not None
    assert created_at.missing_count == 1


def test_preserves_messy_source_data_without_cleaning() -> None:
    data = pd.DataFrame(
        {
            "text": pd.Series(
                [
                    "",
                    "   ",
                    "N/A",
                    "unknown",
                    "UNKNOWN",
                    "José",
                    None,
                ],
                dtype="string",
            ),
            "number_like_text": pd.Series(
                [
                    "10",
                    "20.5",
                    "-3",
                    "001",
                    "",
                    None,
                    "not-a-number",
                ],
                dtype="string",
            ),
        }
    )

    original = data.copy(deep=True)

    schema, profile = profile_table(
        name="messy_text",
        data=data,
    )

    assert schema.columns[0].logical_type is LogicalType.STRING
    assert schema.columns[1].logical_type is LogicalType.STRING

    text = profile.columns[0]
    number_like_text = profile.columns[1]

    assert text.missing_count == 1
    assert text.text_statistics is not None
    assert text.text_statistics.empty_count == 1

    assert number_like_text.missing_count == 1
    assert number_like_text.text_statistics is not None
    assert number_like_text.text_statistics.empty_count == 1

    pd.testing.assert_frame_equal(data, original)


def test_profiles_all_missing_columns_conservatively() -> None:
    data = pd.DataFrame(
        {
            "unknown_values": [None, None, None],
            "nullable_integer": pd.Series(
                [pd.NA, pd.NA, pd.NA],
                dtype="Int64",
            ),
            "nullable_text": pd.Series(
                [pd.NA, pd.NA, pd.NA],
                dtype="string",
            ),
        }
    )

    schema, profile = profile_table(
        name="missing",
        data=data,
    )

    assert schema.columns[0].logical_type is LogicalType.UNKNOWN
    assert schema.columns[1].logical_type is LogicalType.INTEGER
    assert schema.columns[2].logical_type is LogicalType.STRING

    assert all(column.missing_count == 3 for column in profile.columns)

    assert profile.columns[0].numeric_statistics is None
    assert profile.columns[0].text_statistics is None

    assert profile.columns[1].numeric_statistics is None
    assert profile.columns[2].text_statistics is None

    assert profile.missing_value_statistics is not None
    assert profile.missing_value_statistics.missing_cell_count == 9
    assert profile.missing_value_statistics.missing_cell_ratio == 1.0
    assert profile.missing_value_statistics.fully_missing_row_count == 3


def test_profiles_mixed_object_column_without_forcing_a_type() -> None:
    data = pd.DataFrame(
        {
            "mixed": [
                "alpha",
                10,
                3.5,
                True,
                None,
            ]
        }
    )

    schema, profile = profile_table(
        name="mixed",
        data=data,
    )

    assert schema.columns[0].logical_type is LogicalType.UNKNOWN

    column = profile.columns[0]

    assert column.logical_type is LogicalType.UNKNOWN
    assert column.row_count == 5
    assert column.non_missing_count == 4
    assert column.missing_count == 1
    assert column.numeric_statistics is None
    assert column.text_statistics is None
    assert column.datetime_statistics is None


def test_profiles_unusual_column_names() -> None:
    data = pd.DataFrame(
        {
            "Customer Name": ["Ada", "Grace"],
            "amount ($)": [10.0, 20.0],
            "created-at": pd.to_datetime(
                [
                    "2026-01-01",
                    "2026-01-02",
                ]
            ),
            "日本語": ["東京", "大阪"],
            "": [1, 2],
        }
    )

    _, profile = profile_table(
        name="unusual_columns",
        data=data,
    )

    assert tuple(column.name for column in profile.columns) == (
        "Customer Name",
        "amount ($)",
        "created-at",
        "日本語",
        "",
    )


def test_exact_duplicates_with_missing_values_are_reported() -> None:
    data = pd.DataFrame(
        {
            "id": [1, 1, 2, 2],
            "value": [None, None, "x", "x"],
        }
    )

    _, profile = profile_table(
        name="duplicates",
        data=data,
    )

    assert profile.duplicate_statistics is not None

    assert profile.duplicate_statistics.duplicate_row_count == 2
    assert profile.duplicate_statistics.duplicate_row_ratio == 0.5
    assert profile.duplicate_statistics.duplicate_group_row_count == 4
    assert profile.duplicate_statistics.duplicate_group_row_ratio == 1.0


def test_quality_rules_work_with_messy_profile() -> None:
    data = pd.DataFrame(
        {
            "status": ["", "", None, ""],
            "value": [10.0, 10.0, None, 10.0],
        }
    )

    _, profile = profile_table(
        name="messy",
        data=data,
    )

    issues = QualityRuleEngine().evaluate(profile)

    issue_types = tuple(issue.issue_type for issue in issues)

    assert issue_types == (
        QualityIssueType.MISSING_VALUES,
        QualityIssueType.EMPTY_STRINGS,
        QualityIssueType.CONSTANT_COLUMN,
        QualityIssueType.MISSING_VALUES,
        QualityIssueType.CONSTANT_COLUMN,
        QualityIssueType.FULLY_MISSING_ROWS,
        QualityIssueType.DUPLICATE_ROWS,
    )


def test_empty_and_zero_column_tables_remain_profileable() -> None:
    empty_with_columns = pd.DataFrame(
        {
            "id": pd.Series(dtype="Int64"),
            "name": pd.Series(dtype="string"),
        }
    )

    _, empty_profile = profile_table(
        name="empty",
        data=empty_with_columns,
    )

    assert empty_profile.row_count == 0
    assert empty_profile.column_count == 2
    assert len(empty_profile.columns) == 2

    zero_columns = pd.DataFrame(index=range(4))

    _, zero_column_profile = profile_table(
        name="zero_columns",
        data=zero_columns,
    )

    assert zero_column_profile.row_count == 4
    assert zero_column_profile.column_count == 0
    assert zero_column_profile.columns == ()


def test_messy_dataset_profiling_does_not_mutate_any_table() -> None:
    first_data = pd.DataFrame(
        {
            "id": pd.Series(
                [1, 2, pd.NA],
                dtype="Int64",
            ),
            "text": pd.Series(
                ["", "   ", None],
                dtype="string",
            ),
        }
    )

    second_data = pd.DataFrame(
        {
            "value": pd.Series(
                [np.inf, -np.inf, None],
                dtype="Float64",
            ),
            "when": pd.Series(
                [
                    pd.Timestamp("2026-01-01"),
                    pd.NaT,
                    pd.Timestamp("2026-01-03"),
                ],
                dtype="datetime64[ns]",
            ),
        }
    )

    original_first = first_data.copy(deep=True)
    original_second = second_data.copy(deep=True)

    first = make_table(
        name="first",
        data=first_data,
    )
    second = make_table(
        name="second",
        data=second_data,
    )

    dataset = LoadedDataset(
        tables=[
            first,
            second,
        ]
    )

    schema = SchemaInferer().infer_dataset(dataset)

    DatasetProfiler().profile(
        dataset=dataset,
        schema=schema,
    )

    pd.testing.assert_frame_equal(
        first_data,
        original_first,
    )
    pd.testing.assert_frame_equal(
        second_data,
        original_second,
    )
