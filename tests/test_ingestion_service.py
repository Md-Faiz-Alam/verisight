from pathlib import Path

import pandas as pd
import pytest

from verisight.config import Settings
from verisight.ingestion.exceptions import (
    FileValidationError,
    UnsupportedFileTypeError,
)
from verisight.ingestion.service import DatasetLoader


def test_dataset_loader_loads_multiple_files(tmp_path: Path) -> None:
    csv_path = tmp_path / "customers.csv"
    csv_path.write_text(
        "customer_id,name\n1,Alice\n2,Bob\n",
        encoding="utf-8",
    )

    json_path = tmp_path / "orders.json"
    json_path.write_text(
        '[{"order_id": 101}, {"order_id": 102}]',
        encoding="utf-8",
    )

    loader = DatasetLoader(Settings())
    dataset = loader.load([csv_path, json_path])

    assert dataset.table_count == 2
    assert dataset.source_count == 2
    assert [table.name for table in dataset.tables] == [
        "customers",
        "orders",
    ]


def test_dataset_loader_flattens_excel_workbook(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "business.xlsx"

    customers = pd.DataFrame(
        {
            "customer_id": [1, 2],
            "name": ["Alice", "Bob"],
        }
    )

    orders = pd.DataFrame(
        {
            "order_id": [101, 102],
            "customer_id": [1, 2],
        }
    )

    with pd.ExcelWriter(file_path) as writer:
        customers.to_excel(
            writer,
            sheet_name="Customers",
            index=False,
        )
        orders.to_excel(
            writer,
            sheet_name="Orders",
            index=False,
        )

    loader = DatasetLoader(Settings())
    dataset = loader.load([file_path])

    assert dataset.table_count == 2
    assert dataset.source_count == 1

    assert [table.name for table in dataset.tables] == [
        "Customers",
        "Orders",
    ]


def test_dataset_loader_combines_files_and_workbooks(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "customers.csv"
    csv_path.write_text(
        "customer_id\n1\n2\n",
        encoding="utf-8",
    )

    workbook_path = tmp_path / "catalog.xlsx"

    with pd.ExcelWriter(workbook_path) as writer:
        pd.DataFrame({"product_id": [10, 20]}).to_excel(
            writer,
            sheet_name="Products",
            index=False,
        )

        pd.DataFrame({"category_id": [100, 200]}).to_excel(
            writer,
            sheet_name="Categories",
            index=False,
        )

    loader = DatasetLoader(Settings())
    dataset = loader.load(
        [
            csv_path,
            workbook_path,
        ]
    )

    assert dataset.table_count == 3
    assert dataset.source_count == 2

    assert [table.name for table in dataset.tables] == [
        "customers",
        "Products",
        "Categories",
    ]


def test_dataset_loader_preserves_table_provenance(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "customers.csv"
    csv_path.write_text(
        "customer_id\n1\n",
        encoding="utf-8",
    )

    workbook_path = tmp_path / "business.xlsx"

    pd.DataFrame({"order_id": [101]}).to_excel(
        workbook_path,
        sheet_name="Orders",
        index=False,
    )

    loader = DatasetLoader(Settings())
    dataset = loader.load(
        [
            csv_path,
            workbook_path,
        ]
    )

    csv_table = dataset.tables[0]
    excel_table = dataset.tables[1]

    assert csv_table.source.path == csv_path
    assert csv_table.source.sheet_name is None

    assert excel_table.source.path == workbook_path
    assert excel_table.source.sheet_name == "Orders"


def test_dataset_loader_supports_empty_input() -> None:
    loader = DatasetLoader(Settings())

    dataset = loader.load([])

    assert dataset.table_count == 0
    assert dataset.source_count == 0
    assert dataset.tables == []


def test_dataset_loader_preserves_unsupported_type_error(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "customers.txt"
    file_path.write_text("data", encoding="utf-8")

    loader = DatasetLoader(Settings())

    with pytest.raises(UnsupportedFileTypeError):
        loader.load([file_path])


def test_dataset_loader_preserves_file_validation_error(
    tmp_path: Path,
) -> None:
    loader = DatasetLoader(Settings())

    with pytest.raises(
        FileValidationError,
        match="File does not exist",
    ):
        loader.load([tmp_path / "missing.csv"])
