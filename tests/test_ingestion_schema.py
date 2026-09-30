from pathlib import Path

import pandas as pd

from verisight.ingestion.models import (
    LoadedDataset,
    LoadedTable,
    SourceMetadata,
)
from verisight.ingestion.schema import (
    LogicalType,
    SchemaInferer,
)


def make_table(
    data: pd.DataFrame,
    *,
    name: str = "customers",
) -> LoadedTable:
    metadata = SourceMetadata(
        path=Path(f"{name}.csv"),
        file_name=f"{name}.csv",
        file_extension=".csv",
        file_size_bytes=100,
    )

    return LoadedTable(
        name=name,
        data=data,
        source=metadata,
    )


def test_schema_inferer_reports_table_structure() -> None:
    table = make_table(
        pd.DataFrame(
            {
                "customer_id": [1, 2],
                "name": ["Alice", "Bob"],
            }
        )
    )

    schema = SchemaInferer().infer_table(table)

    assert schema.name == "customers"
    assert schema.relation_name == "customers"
    assert schema.row_count == 2
    assert schema.column_count == 2
    assert len(schema.columns) == 2

    assert [column.name for column in schema.columns] == [
        "customer_id",
        "name",
    ]


def test_schema_inferer_preserves_display_name_and_relation_name() -> None:
    table = make_table(
        pd.DataFrame(
            {
                "order_id": [1, 2],
            }
        ),
        name="Sales Data",
    )
    table.relation_name = "sales_data"

    schema = SchemaInferer().infer_table(table)

    assert schema.name == "Sales Data"
    assert schema.relation_name == "sales_data"


def test_schema_inferer_detects_integer() -> None:
    table = make_table(
        pd.DataFrame(
            {
                "value": [1, 2, 3],
            }
        )
    )

    column = SchemaInferer().infer_table(table).columns[0]

    assert column.logical_type is LogicalType.INTEGER
    assert column.physical_dtype == "int64"


def test_schema_inferer_detects_float() -> None:
    table = make_table(
        pd.DataFrame(
            {
                "value": [1.5, 2.5],
            }
        )
    )

    column = SchemaInferer().infer_table(table).columns[0]

    assert column.logical_type is LogicalType.FLOAT


def test_schema_inferer_detects_boolean() -> None:
    table = make_table(
        pd.DataFrame(
            {
                "active": [True, False],
            }
        )
    )

    column = SchemaInferer().infer_table(table).columns[0]

    assert column.logical_type is LogicalType.BOOLEAN


def test_schema_inferer_detects_datetime() -> None:
    table = make_table(
        pd.DataFrame(
            {
                "created_at": pd.to_datetime(
                    [
                        "2026-01-01",
                        "2026-01-02",
                    ]
                )
            }
        )
    )

    column = SchemaInferer().infer_table(table).columns[0]

    assert column.logical_type is LogicalType.DATETIME


def test_schema_inferer_detects_string() -> None:
    table = make_table(
        pd.DataFrame(
            {
                "name": ["Alice", "Bob"],
            }
        )
    )

    column = SchemaInferer().infer_table(table).columns[0]

    assert column.logical_type is LogicalType.STRING


def test_schema_inferer_reports_missing_values() -> None:
    table = make_table(
        pd.DataFrame(
            {
                "score": [10.0, None, 30.0],
            }
        )
    )

    column = SchemaInferer().infer_table(table).columns[0]

    assert column.nullable is True
    assert column.missing_count == 1


def test_schema_inferer_reports_non_nullable_column() -> None:
    table = make_table(
        pd.DataFrame(
            {
                "score": [10, 20, 30],
            }
        )
    )

    column = SchemaInferer().infer_table(table).columns[0]

    assert column.nullable is False
    assert column.missing_count == 0


def test_schema_inferer_handles_empty_table() -> None:
    table = make_table(pd.DataFrame())

    schema = SchemaInferer().infer_table(table)

    assert schema.row_count == 0
    assert schema.column_count == 0
    assert schema.columns == ()


def test_schema_inferer_handles_unknown_dtype() -> None:
    table = make_table(
        pd.DataFrame(
            {
                "payload": pd.Series(
                    [{"value": 1}, {"value": 2}],
                    dtype=object,
                )
            }
        )
    )

    column = SchemaInferer().infer_table(table).columns[0]

    assert column.logical_type is LogicalType.UNKNOWN


def test_schema_inferer_detects_object_column_of_strings() -> None:
    table = make_table(
        pd.DataFrame(
            {
                "name": pd.Series(
                    ["Alice", "Bob"],
                    dtype=object,
                )
            }
        )
    )

    column = SchemaInferer().infer_table(table).columns[0]

    assert column.logical_type is LogicalType.STRING


def test_schema_inferer_treats_mixed_object_column_as_unknown() -> None:
    table = make_table(
        pd.DataFrame(
            {
                "value": pd.Series(
                    ["Alice", 123],
                    dtype=object,
                )
            }
        )
    )

    column = SchemaInferer().infer_table(table).columns[0]

    assert column.logical_type is LogicalType.UNKNOWN


def test_schema_inferer_infers_entire_dataset() -> None:
    customers = make_table(
        pd.DataFrame(
            {
                "customer_id": [1, 2],
            }
        ),
        name="customers",
    )

    orders = make_table(
        pd.DataFrame(
            {
                "order_id": [101, 102],
            }
        ),
        name="orders",
    )

    dataset = LoadedDataset(
        tables=[
            customers,
            orders,
        ]
    )

    schema = SchemaInferer().infer_dataset(dataset)

    assert schema.table_count == 2
    assert [table.name for table in schema.tables] == [
        "customers",
        "orders",
    ]
    assert [table.relation_name for table in schema.tables] == [
        "customers",
        "orders",
    ]


def test_schema_inferer_supports_duplicate_display_names_with_unique_relations() -> (
    None
):
    first = make_table(
        pd.DataFrame(
            {
                "first_id": [1, 2],
            }
        ),
        name="Sales",
    )
    first.relation_name = "sales"

    second = make_table(
        pd.DataFrame(
            {
                "second_id": [10, 20],
            }
        ),
        name="Sales",
    )
    second.relation_name = "sales_2"

    dataset = LoadedDataset(
        tables=[
            first,
            second,
        ]
    )

    schema = SchemaInferer().infer_dataset(dataset)

    assert schema.table_count == 2
    assert [table.name for table in schema.tables] == [
        "Sales",
        "Sales",
    ]
    assert [table.relation_name for table in schema.tables] == [
        "sales",
        "sales_2",
    ]


def test_schema_inferer_handles_empty_dataset() -> None:
    dataset = LoadedDataset(tables=[])

    schema = SchemaInferer().infer_dataset(dataset)

    assert schema.table_count == 0
    assert schema.tables == ()


def test_schema_inferer_treats_all_missing_object_column_as_unknown() -> None:
    table = make_table(
        pd.DataFrame(
            {
                "value": pd.Series(
                    [None, None],
                    dtype=object,
                )
            }
        )
    )

    column = SchemaInferer().infer_table(table).columns[0]

    assert column.logical_type is LogicalType.UNKNOWN
    assert column.nullable is True
    assert column.missing_count == 2


def test_schema_inferer_detects_pandas_string_dtype() -> None:
    table = make_table(
        pd.DataFrame(
            {
                "name": pd.Series(
                    ["Alice", "Bob"],
                    dtype="string",
                )
            }
        )
    )

    column = SchemaInferer().infer_table(table).columns[0]

    assert column.logical_type is LogicalType.STRING
    assert column.physical_dtype == "string"


def test_schema_inferer_treats_unsupported_dtype_as_unknown() -> None:
    table = make_table(
        pd.DataFrame(
            {
                "category": pd.Series(
                    ["A", "B"],
                    dtype="category",
                )
            }
        )
    )

    column = SchemaInferer().infer_table(table).columns[0]

    assert column.logical_type is LogicalType.UNKNOWN
    assert column.physical_dtype == "category"
