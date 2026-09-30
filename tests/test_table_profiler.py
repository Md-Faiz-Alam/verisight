from pathlib import Path

import pandas as pd
import pytest

from verisight.ingestion.models import LoadedTable, SourceMetadata
from verisight.ingestion.schema import SchemaInferer, TableSchema
from verisight.profiling.table import TableProfiler


def make_table(
    *,
    name: str,
    data: pd.DataFrame,
) -> LoadedTable:
    """Create a loaded table for profiling tests."""

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


def infer_schema(table: LoadedTable) -> TableSchema:
    """Infer the schema used by table profiling tests."""

    return SchemaInferer().infer_table(table)


def test_profiles_columns_using_inferred_schema() -> None:
    table = make_table(
        name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2, 3],
                "amount": [10.5, 20.0, 30.5],
            }
        ),
    )

    schema = infer_schema(table)

    profiles = TableProfiler().profile_columns(
        table=table,
        schema=schema,
    )

    assert len(profiles) == 2

    assert profiles[0].name == "order_id"
    assert profiles[0].logical_type == schema.columns[0].logical_type
    assert profiles[0].numeric_statistics is not None

    assert profiles[1].name == "amount"
    assert profiles[1].logical_type == schema.columns[1].logical_type
    assert profiles[1].numeric_statistics is not None


def test_preserves_source_column_order() -> None:
    table = make_table(
        name="orders",
        data=pd.DataFrame(
            {
                "amount": [10.0, 20.0],
                "order_id": [1, 2],
            }
        ),
    )

    inferred_schema = infer_schema(table)

    schema = TableSchema(
        name=inferred_schema.name,
        relation_name=inferred_schema.relation_name,
        row_count=inferred_schema.row_count,
        column_count=inferred_schema.column_count,
        columns=tuple(reversed(inferred_schema.columns)),
    )

    profiles = TableProfiler().profile_columns(
        table=table,
        schema=schema,
    )

    assert tuple(profile.name for profile in profiles) == (
        "amount",
        "order_id",
    )


def test_profiles_empty_table() -> None:
    table = make_table(
        name="orders",
        data=pd.DataFrame(
            {
                "order_id": pd.Series(dtype="int64"),
                "amount": pd.Series(dtype="float64"),
            }
        ),
    )

    schema = infer_schema(table)

    profiles = TableProfiler().profile_columns(
        table=table,
        schema=schema,
    )

    assert len(profiles) == 2
    assert all(profile.row_count == 0 for profile in profiles)


def test_rejects_schema_missing_table_column() -> None:
    table = make_table(
        name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2],
                "amount": [10.0, 20.0],
            }
        ),
    )

    inferred_schema = infer_schema(table)

    schema = TableSchema(
        name=inferred_schema.name,
        relation_name=inferred_schema.relation_name,
        row_count=inferred_schema.row_count,
        column_count=1,
        columns=(inferred_schema.columns[0],),
    )

    with pytest.raises(
        ValueError,
        match="Schema does not contain column 'amount'",
    ):
        TableProfiler().profile_columns(
            table=table,
            schema=schema,
        )


def test_profiles_complete_table() -> None:
    table = make_table(
        name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2, 2, 4],
                "amount": [10.0, 20.0, 20.0, None],
            }
        ),
    )

    schema = infer_schema(table)

    profile = TableProfiler().profile(
        table=table,
        schema=schema,
    )

    assert profile.name == "orders"
    assert profile.row_count == 4
    assert profile.column_count == 2
    assert len(profile.columns) == 2

    assert profile.missing_value_statistics is not None
    assert profile.missing_value_statistics.missing_cell_count == 1
    assert profile.missing_value_statistics.missing_cell_ratio == 1 / 8

    assert profile.duplicate_statistics is not None
    assert profile.duplicate_statistics.duplicate_row_count == 1
    assert profile.duplicate_statistics.duplicate_row_ratio == 0.25
    assert profile.duplicate_statistics.duplicate_group_row_count == 2
    assert profile.duplicate_statistics.duplicate_group_row_ratio == 0.5

    assert profile.duplicate_row_count == 1
    assert profile.duplicate_row_ratio == 0.25


def test_complete_profile_contains_column_statistics() -> None:
    table = make_table(
        name="customers",
        data=pd.DataFrame(
            {
                "customer_id": [1, 2, 3],
                "name": ["Ada", "", "Grace"],
            }
        ),
    )

    schema = infer_schema(table)

    profile = TableProfiler().profile(
        table=table,
        schema=schema,
    )

    customer_id = profile.columns[0]
    name = profile.columns[1]

    assert customer_id.numeric_statistics is not None
    assert customer_id.numeric_statistics.minimum == 1
    assert customer_id.numeric_statistics.maximum == 3

    assert name.text_statistics is not None
    assert name.text_statistics.empty_count == 1
    assert name.text_statistics.empty_ratio == 1 / 3


def test_complete_profile_handles_empty_table() -> None:
    table = make_table(
        name="orders",
        data=pd.DataFrame(
            {
                "order_id": pd.Series(dtype="int64"),
                "amount": pd.Series(dtype="float64"),
            }
        ),
    )

    schema = infer_schema(table)

    profile = TableProfiler().profile(
        table=table,
        schema=schema,
    )

    assert profile.row_count == 0
    assert profile.column_count == 2
    assert len(profile.columns) == 2

    assert profile.missing_value_statistics is not None
    assert profile.missing_value_statistics.total_cell_count == 0
    assert profile.missing_value_statistics.missing_cell_count == 0

    assert profile.duplicate_statistics is not None
    assert profile.duplicate_statistics.duplicate_row_count == 0
    assert profile.duplicate_statistics.duplicate_group_row_count == 0

    assert profile.duplicate_row_count == 0
    assert profile.duplicate_row_ratio == 0.0


def test_complete_profile_handles_zero_column_table() -> None:
    table = make_table(
        name="empty",
        data=pd.DataFrame(index=range(3)),
    )

    schema = infer_schema(table)

    profile = TableProfiler().profile(
        table=table,
        schema=schema,
    )

    assert profile.row_count == 3
    assert profile.column_count == 0
    assert profile.columns == ()

    assert profile.missing_value_statistics is not None
    assert profile.missing_value_statistics.total_cell_count == 0
    assert profile.missing_value_statistics.missing_cell_count == 0
    assert profile.missing_value_statistics.rows_with_missing_count == 0
    assert profile.missing_value_statistics.fully_missing_row_count == 0

    assert profile.duplicate_statistics is not None
    assert profile.duplicate_statistics.duplicate_row_count == 0
    assert profile.duplicate_statistics.duplicate_group_row_count == 0


def test_complete_profiling_does_not_mutate_source_table() -> None:
    data = pd.DataFrame(
        {
            "order_id": [1, 2, 2],
            "amount": [10.0, None, None],
            "status": ["open", "", ""],
        }
    )
    original = data.copy(deep=True)

    table = make_table(
        name="orders",
        data=data,
    )

    schema = infer_schema(table)

    TableProfiler().profile(
        table=table,
        schema=schema,
    )

    pd.testing.assert_frame_equal(data, original)
