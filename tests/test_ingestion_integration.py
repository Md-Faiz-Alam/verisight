from pathlib import Path

import pandas as pd
import pytest

from verisight.config import Settings
from verisight.ingestion.exceptions import (
    DataLoadError,
    FileValidationError,
    UnsupportedFileTypeError,
)
from verisight.ingestion.schema import LogicalType, SchemaInferer
from verisight.ingestion.service import DatasetLoader


def test_phase_two_end_to_end_ingestion_workflow(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "customers.csv"
    csv_path.write_text(
        "customer_id,name,active\n1,Alice,true\n2,Bob,false\n",
        encoding="utf-8",
    )

    json_path = tmp_path / "events.json"
    json_path.write_text(
        '[{"event_id": 101, "event": "signup"}, '
        '{"event_id": 102, "event": "purchase"}]',
        encoding="utf-8",
    )

    excel_path = tmp_path / "business.xlsx"

    with pd.ExcelWriter(excel_path) as writer:
        pd.DataFrame(
            {
                "order_id": [1001, 1002],
                "amount": [49.5, 75.0],
            }
        ).to_excel(
            writer,
            sheet_name="Orders",
            index=False,
        )

        pd.DataFrame(
            {
                "product_id": [501, 502],
                "product_name": ["Keyboard", "Mouse"],
            }
        ).to_excel(
            writer,
            sheet_name="Products",
            index=False,
        )

    dataset = DatasetLoader(Settings()).load(
        [
            csv_path,
            json_path,
            excel_path,
        ]
    )

    assert dataset.source_count == 3
    assert dataset.table_count == 4

    assert [table.name for table in dataset.tables] == [
        "customers",
        "events",
        "Orders",
        "Products",
    ]

    customers = dataset.tables[0]
    events = dataset.tables[1]
    orders = dataset.tables[2]
    products = dataset.tables[3]

    assert customers.source.path == csv_path
    assert customers.source.sheet_name is None

    assert events.source.path == json_path
    assert events.source.sheet_name is None

    assert orders.source.path == excel_path
    assert orders.source.sheet_name == "Orders"

    assert products.source.path == excel_path
    assert products.source.sheet_name == "Products"

    schema = SchemaInferer().infer_dataset(dataset)

    assert schema.table_count == 4

    schemas = {table.name: table for table in schema.tables}

    customer_columns = {column.name: column for column in schemas["customers"].columns}

    assert schemas["customers"].row_count == 2
    assert schemas["customers"].column_count == 3
    assert customer_columns["customer_id"].logical_type is LogicalType.INTEGER
    assert customer_columns["name"].logical_type is LogicalType.STRING
    assert customer_columns["active"].logical_type is LogicalType.BOOLEAN

    event_columns = {column.name: column for column in schemas["events"].columns}

    assert schemas["events"].row_count == 2
    assert event_columns["event_id"].logical_type is LogicalType.INTEGER
    assert event_columns["event"].logical_type is LogicalType.STRING

    order_columns = {column.name: column for column in schemas["Orders"].columns}

    assert schemas["Orders"].row_count == 2
    assert order_columns["order_id"].logical_type is LogicalType.INTEGER
    assert order_columns["amount"].logical_type is LogicalType.FLOAT

    product_columns = {column.name: column for column in schemas["Products"].columns}

    assert schemas["Products"].row_count == 2
    assert product_columns["product_id"].logical_type is LogicalType.INTEGER
    assert product_columns["product_name"].logical_type is LogicalType.STRING


def test_dataset_loader_rejects_unsupported_file_type(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "customers.txt"
    file_path.write_text("customer_id,name\n1,Alice\n", encoding="utf-8")

    loader = DatasetLoader(Settings())

    with pytest.raises(UnsupportedFileTypeError):
        loader.load([file_path])


def test_dataset_loader_rejects_missing_file(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "missing.csv"

    loader = DatasetLoader(Settings())

    with pytest.raises(FileValidationError):
        loader.load([file_path])


def test_dataset_loader_propagates_data_load_failure(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "broken.json"
    file_path.write_text(
        '{"customer_id": 1,',
        encoding="utf-8",
    )

    loader = DatasetLoader(Settings())

    with pytest.raises(DataLoadError):
        loader.load([file_path])
