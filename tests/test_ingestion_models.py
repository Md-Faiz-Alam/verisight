from pathlib import Path

import pandas as pd

from verisight.ingestion.models import (
    LoadedDataset,
    LoadedTable,
    LoadedWorkbook,
    SourceMetadata,
)


def test_source_metadata_stores_file_information() -> None:
    metadata = SourceMetadata(
        path=Path("data/customers.csv"),
        file_name="customers.csv",
        file_extension=".csv",
        file_size_bytes=1024,
    )

    assert metadata.path == Path("data/customers.csv")
    assert metadata.file_name == "customers.csv"
    assert metadata.file_extension == ".csv"
    assert metadata.file_size_bytes == 1024


def test_loaded_table_reports_shape() -> None:
    data = pd.DataFrame(
        {
            "customer_id": [1, 2, 3],
            "segment": ["A", "B", "A"],
        }
    )

    metadata = SourceMetadata(
        path=Path("customers.csv"),
        file_name="customers.csv",
        file_extension=".csv",
        file_size_bytes=100,
    )

    table = LoadedTable(
        name="customers",
        data=data,
        source=metadata,
    )

    assert table.row_count == 3
    assert table.column_count == 2


def test_loaded_table_supports_empty_dataframe() -> None:
    data = pd.DataFrame()

    metadata = SourceMetadata(
        path=Path("empty.csv"),
        file_name="empty.csv",
        file_extension=".csv",
        file_size_bytes=0,
    )

    table = LoadedTable(
        name="empty",
        data=data,
        source=metadata,
    )

    assert table.row_count == 0
    assert table.column_count == 0


def test_source_metadata_defaults_sheet_name_to_none() -> None:
    metadata = SourceMetadata(
        path=Path("customers.csv"),
        file_name="customers.csv",
        file_extension=".csv",
        file_size_bytes=100,
    )

    assert metadata.sheet_name is None


def test_loaded_workbook_reports_table_count() -> None:
    metadata = SourceMetadata(
        path=Path("business.xlsx"),
        file_name="business.xlsx",
        file_extension=".xlsx",
        file_size_bytes=100,
    )

    workbook = LoadedWorkbook(
        source=metadata,
        tables=[],
    )

    assert workbook.table_count == 0


def test_loaded_dataset_reports_table_and_source_counts() -> None:
    first_source = SourceMetadata(
        path=Path("customers.csv"),
        file_name="customers.csv",
        file_extension=".csv",
        file_size_bytes=100,
    )

    second_source = SourceMetadata(
        path=Path("business.xlsx"),
        file_name="business.xlsx",
        file_extension=".xlsx",
        file_size_bytes=200,
        sheet_name="Orders",
    )

    tables = [
        LoadedTable(
            name="customers",
            data=pd.DataFrame({"id": [1]}),
            source=first_source,
        ),
        LoadedTable(
            name="orders",
            data=pd.DataFrame({"id": [10]}),
            source=second_source,
        ),
    ]

    dataset = LoadedDataset(tables=tables)

    assert dataset.table_count == 2
    assert dataset.source_count == 2


def test_loaded_dataset_counts_workbook_sheets_as_one_source() -> None:
    first_sheet = LoadedTable(
        name="Customers",
        data=pd.DataFrame({"id": [1]}),
        source=SourceMetadata(
            path=Path("business.xlsx"),
            file_name="business.xlsx",
            file_extension=".xlsx",
            file_size_bytes=200,
            sheet_name="Customers",
        ),
    )

    second_sheet = LoadedTable(
        name="Orders",
        data=pd.DataFrame({"id": [10]}),
        source=SourceMetadata(
            path=Path("business.xlsx"),
            file_name="business.xlsx",
            file_extension=".xlsx",
            file_size_bytes=200,
            sheet_name="Orders",
        ),
    )

    dataset = LoadedDataset(
        tables=[
            first_sheet,
            second_sheet,
        ]
    )

    assert dataset.table_count == 2
    assert dataset.source_count == 1


def test_loaded_table_initializes_relation_name_from_name() -> None:
    metadata = SourceMetadata(
        path=Path("Sales Data.csv"),
        file_name="Sales Data.csv",
        file_extension=".csv",
        file_size_bytes=100,
    )

    table = LoadedTable(
        name="Sales Data",
        data=pd.DataFrame({"id": [1]}),
        source=metadata,
    )

    assert table.name == "Sales Data"
    assert table.relation_name == "Sales Data"
