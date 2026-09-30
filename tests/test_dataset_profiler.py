from pathlib import Path

import pandas as pd
import pytest

from verisight.ingestion.models import (
    LoadedDataset,
    LoadedTable,
    SourceMetadata,
)
from verisight.ingestion.schema import (
    DatasetSchema,
    SchemaInferer,
)
from verisight.profiling.dataset import DatasetProfiler


def make_table(
    *,
    name: str,
    data: pd.DataFrame,
) -> LoadedTable:
    """Create a loaded table for dataset profiling tests."""

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


def test_profiles_single_table_dataset() -> None:
    table = make_table(
        name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2, 3],
                "amount": [10.0, 20.0, None],
            }
        ),
    )

    dataset = LoadedDataset(tables=[table])
    schema = SchemaInferer().infer_dataset(dataset)

    profile = DatasetProfiler().profile(
        dataset=dataset,
        schema=schema,
    )

    assert profile.table_count == 1
    assert len(profile.tables) == 1

    table_profile = profile.tables[0]

    assert table_profile.name == "orders"
    assert table_profile.row_count == 3
    assert table_profile.column_count == 2
    assert len(table_profile.columns) == 2

    assert table_profile.missing_value_statistics is not None
    assert table_profile.missing_value_statistics.missing_cell_count == 1

    assert table_profile.duplicate_statistics is not None
    assert table_profile.duplicate_statistics.duplicate_row_count == 0


def test_profiles_multiple_tables() -> None:
    orders = make_table(
        name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2, 2],
                "amount": [10.0, 20.0, 20.0],
            }
        ),
    )

    customers = make_table(
        name="customers",
        data=pd.DataFrame(
            {
                "customer_id": [100, 200],
                "name": ["Ada", "Grace"],
            }
        ),
    )

    dataset = LoadedDataset(
        tables=[
            orders,
            customers,
        ]
    )

    schema = SchemaInferer().infer_dataset(dataset)

    profile = DatasetProfiler().profile(
        dataset=dataset,
        schema=schema,
    )

    assert profile.table_count == 2

    orders_profile = profile.tables[0]
    customers_profile = profile.tables[1]

    assert orders_profile.name == "orders"
    assert customers_profile.name == "customers"

    assert orders_profile.duplicate_statistics is not None
    assert orders_profile.duplicate_statistics.duplicate_row_count == 1

    assert customers_profile.duplicate_statistics is not None
    assert customers_profile.duplicate_statistics.duplicate_row_count == 0


def test_preserves_dataset_table_order() -> None:
    orders = make_table(
        name="orders",
        data=pd.DataFrame({"order_id": [1, 2]}),
    )

    customers = make_table(
        name="customers",
        data=pd.DataFrame({"customer_id": [10, 20]}),
    )

    products = make_table(
        name="products",
        data=pd.DataFrame({"product_id": [100, 200]}),
    )

    dataset = LoadedDataset(
        tables=[
            orders,
            customers,
            products,
        ]
    )

    schema = SchemaInferer().infer_dataset(dataset)

    profile = DatasetProfiler().profile(
        dataset=dataset,
        schema=schema,
    )

    assert tuple(table_profile.name for table_profile in profile.tables) == (
        "orders",
        "customers",
        "products",
    )


def test_matches_schema_by_relation_name_not_position() -> None:
    orders = make_table(
        name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2],
                "amount": [10.0, 20.0],
            }
        ),
    )

    customers = make_table(
        name="customers",
        data=pd.DataFrame(
            {
                "customer_id": [100, 200],
                "name": ["Ada", "Grace"],
            }
        ),
    )

    dataset = LoadedDataset(
        tables=[
            orders,
            customers,
        ]
    )

    inferred_schema = SchemaInferer().infer_dataset(dataset)

    reversed_schema = DatasetSchema(tables=tuple(reversed(inferred_schema.tables)))

    profile = DatasetProfiler().profile(
        dataset=dataset,
        schema=reversed_schema,
    )

    assert profile.tables[0].name == "orders"
    assert profile.tables[0].column_count == 2

    assert profile.tables[1].name == "customers"
    assert profile.tables[1].column_count == 2


def test_profiles_duplicate_display_names_using_relation_identity() -> None:
    first = make_table(
        name="Sales",
        data=pd.DataFrame(
            {
                "first_id": [1, 2],
            }
        ),
    )
    first.relation_name = "sales"

    second = make_table(
        name="Sales",
        data=pd.DataFrame(
            {
                "second_id": [10, 20],
                "amount": [100.0, 200.0],
            }
        ),
    )
    second.relation_name = "sales_2"

    dataset = LoadedDataset(
        tables=[
            first,
            second,
        ]
    )

    schema = SchemaInferer().infer_dataset(dataset)

    profile = DatasetProfiler().profile(
        dataset=dataset,
        schema=schema,
    )

    assert profile.table_count == 2

    assert profile.tables[0].name == "Sales"
    assert profile.tables[0].column_count == 1
    assert profile.tables[0].columns[0].name == "first_id"

    assert profile.tables[1].name == "Sales"
    assert profile.tables[1].column_count == 2
    assert [column.name for column in profile.tables[1].columns] == [
        "second_id",
        "amount",
    ]


def test_profiles_empty_dataset() -> None:
    dataset = LoadedDataset(tables=[])
    schema = DatasetSchema(tables=())

    profile = DatasetProfiler().profile(
        dataset=dataset,
        schema=schema,
    )

    assert profile.table_count == 0
    assert profile.tables == ()


def test_rejects_missing_table_schema() -> None:
    orders = make_table(
        name="orders",
        data=pd.DataFrame({"order_id": [1, 2]}),
    )

    customers = make_table(
        name="customers",
        data=pd.DataFrame({"customer_id": [10, 20]}),
    )

    dataset = LoadedDataset(
        tables=[
            orders,
            customers,
        ]
    )

    inferred_schema = SchemaInferer().infer_dataset(dataset)

    incomplete_schema = DatasetSchema(tables=(inferred_schema.tables[0],))

    with pytest.raises(
        ValueError,
        match="Schema does not contain table 'customers'",
    ):
        DatasetProfiler().profile(
            dataset=dataset,
            schema=incomplete_schema,
        )


def test_dataset_profile_contains_complete_table_profiles() -> None:
    table = make_table(
        name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2, 2, 4],
                "amount": [10.0, 20.0, 20.0, None],
                "status": ["open", "", "", "closed"],
            }
        ),
    )

    dataset = LoadedDataset(tables=[table])
    schema = SchemaInferer().infer_dataset(dataset)

    profile = DatasetProfiler().profile(
        dataset=dataset,
        schema=schema,
    )

    table_profile = profile.tables[0]

    assert len(table_profile.columns) == 3

    assert table_profile.missing_value_statistics is not None
    assert table_profile.missing_value_statistics.missing_cell_count == 1

    assert table_profile.duplicate_statistics is not None
    assert table_profile.duplicate_statistics.duplicate_row_count == 1

    status_profile = table_profile.columns[2]

    assert status_profile.text_statistics is not None
    assert status_profile.text_statistics.empty_count == 2


def test_dataset_profiling_does_not_mutate_source_tables() -> None:
    orders_data = pd.DataFrame(
        {
            "order_id": [1, 2, 2],
            "amount": [10.0, None, None],
        }
    )
    customers_data = pd.DataFrame(
        {
            "customer_id": [10, 20],
            "name": ["Ada", ""],
        }
    )

    original_orders = orders_data.copy(deep=True)
    original_customers = customers_data.copy(deep=True)

    orders = make_table(
        name="orders",
        data=orders_data,
    )
    customers = make_table(
        name="customers",
        data=customers_data,
    )

    dataset = LoadedDataset(
        tables=[
            orders,
            customers,
        ]
    )

    schema = SchemaInferer().infer_dataset(dataset)

    DatasetProfiler().profile(
        dataset=dataset,
        schema=schema,
    )

    pd.testing.assert_frame_equal(
        orders_data,
        original_orders,
    )
    pd.testing.assert_frame_equal(
        customers_data,
        original_customers,
    )
