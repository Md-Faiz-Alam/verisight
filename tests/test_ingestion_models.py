from pathlib import Path

import pandas as pd
import pytest

from verisight.ingestion.exceptions import TableValidationError
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
        path=Path("customers.csv"),
        file_name="customers.csv",
        file_extension=".csv",
        file_size_bytes=100,
    )

    table = LoadedTable(
        name="Customers 2026",
        data=pd.DataFrame({"id": [1]}),
        source=metadata,
    )

    assert table.name == "Customers 2026"
    assert table.relation_name == "Customers 2026"


def test_loaded_table_rejects_duplicate_column_names() -> None:
    metadata = SourceMetadata(
        path=Path("customers.csv"),
        file_name="customers.csv",
        file_extension=".csv",
        file_size_bytes=100,
    )

    data = pd.DataFrame(
        [
            [1, "Alice"],
            [2, "Bob"],
        ],
        columns=["customer_id", "customer_id"],
    )

    with pytest.raises(
        TableValidationError,
        match="contains duplicate column names",
    ):
        LoadedTable(
            name="customers",
            data=data,
            source=metadata,
        )


def test_duplicate_column_error_identifies_table_and_column() -> None:
    metadata = SourceMetadata(
        path=Path("customers.csv"),
        file_name="customers.csv",
        file_extension=".csv",
        file_size_bytes=100,
    )

    data = pd.DataFrame(
        [[1, 2, 3]],
        columns=["id", "value", "id"],
    )

    with pytest.raises(TableValidationError) as exc_info:
        LoadedTable(
            name="customers",
            data=data,
            source=metadata,
        )

    message = str(exc_info.value)

    assert "customers" in message
    assert "'id'" in message


def test_loaded_table_reports_each_duplicate_column_once() -> None:
    metadata = SourceMetadata(
        path=Path("customers.csv"),
        file_name="customers.csv",
        file_extension=".csv",
        file_size_bytes=100,
    )

    data = pd.DataFrame(
        [[1, 2, 3, 4]],
        columns=["id", "id", "name", "name"],
    )

    with pytest.raises(TableValidationError) as exc_info:
        LoadedTable(
            name="customers",
            data=data,
            source=metadata,
        )

    message = str(exc_info.value)

    assert message.count("'id'") == 1
    assert message.count("'name'") == 1


def test_loaded_dataset_rejects_duplicate_relation_names() -> None:
    first = LoadedTable(
        name="Sales",
        data=pd.DataFrame({"id": [1]}),
        source=SourceMetadata(
            path=Path("first.csv"),
            file_name="first.csv",
            file_extension=".csv",
            file_size_bytes=100,
        ),
    )
    first.relation_name = "sales"

    second = LoadedTable(
        name="Sales",
        data=pd.DataFrame({"id": [2]}),
        source=SourceMetadata(
            path=Path("second.csv"),
            file_name="second.csv",
            file_extension=".csv",
            file_size_bytes=100,
        ),
    )
    second.relation_name = "sales"

    with pytest.raises(
        TableValidationError,
        match="duplicate relation names",
    ):
        LoadedDataset(
            tables=[
                first,
                second,
            ]
        )


def test_loaded_dataset_duplicate_relation_error_identifies_relation() -> None:
    first = LoadedTable(
        name="First",
        data=pd.DataFrame({"id": [1]}),
        source=SourceMetadata(
            path=Path("first.csv"),
            file_name="first.csv",
            file_extension=".csv",
            file_size_bytes=100,
        ),
    )
    first.relation_name = "shared_relation"

    second = LoadedTable(
        name="Second",
        data=pd.DataFrame({"id": [2]}),
        source=SourceMetadata(
            path=Path("second.csv"),
            file_name="second.csv",
            file_extension=".csv",
            file_size_bytes=100,
        ),
    )
    second.relation_name = "shared_relation"

    with pytest.raises(TableValidationError) as exc_info:
        LoadedDataset(
            tables=[
                first,
                second,
            ]
        )

    assert "'shared_relation'" in str(exc_info.value)


def test_loaded_dataset_allows_duplicate_display_names_with_unique_relations() -> None:
    first = LoadedTable(
        name="Sales",
        data=pd.DataFrame({"id": [1]}),
        source=SourceMetadata(
            path=Path("first.csv"),
            file_name="first.csv",
            file_extension=".csv",
            file_size_bytes=100,
        ),
    )
    first.relation_name = "sales"

    second = LoadedTable(
        name="Sales",
        data=pd.DataFrame({"id": [2]}),
        source=SourceMetadata(
            path=Path("second.csv"),
            file_name="second.csv",
            file_extension=".csv",
            file_size_bytes=100,
        ),
    )
    second.relation_name = "sales_2"

    dataset = LoadedDataset(
        tables=[
            first,
            second,
        ]
    )

    assert dataset.table_count == 2
    assert [table.name for table in dataset.tables] == [
        "Sales",
        "Sales",
    ]
    assert [table.relation_name for table in dataset.tables] == [
        "sales",
        "sales_2",
    ]


def test_loaded_dataset_reports_each_duplicate_relation_once() -> None:
    tables: list[LoadedTable] = []

    for index in range(3):
        table = LoadedTable(
            name=f"Sales {index}",
            data=pd.DataFrame({"id": [index]}),
            source=SourceMetadata(
                path=Path(f"sales_{index}.csv"),
                file_name=f"sales_{index}.csv",
                file_extension=".csv",
                file_size_bytes=100,
            ),
        )
        table.relation_name = "sales"
        tables.append(table)

    with pytest.raises(TableValidationError) as exc_info:
        LoadedDataset(tables=tables)

    assert str(exc_info.value).count("'sales'") == 1
