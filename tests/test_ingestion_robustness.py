from pathlib import Path

import pandas as pd

from verisight.config import Settings
from verisight.ingestion.loaders.csv import CsvLoader
from verisight.ingestion.loaders.excel import ExcelLoader
from verisight.ingestion.loaders.json import JsonLoader
from verisight.ingestion.schema import LogicalType, SchemaInferer
from verisight.ingestion.service import DatasetLoader


def test_csv_preserves_unicode_text(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.csv"
    file_path.write_text(
        "name,city\nJosé,São Paulo\n李明,北京\nFaiz,पटना\n",
        encoding="utf-8",
    )

    table = CsvLoader(Settings()).load(file_path)

    assert table.row_count == 3
    assert table.data["name"].tolist() == ["José", "李明", "Faiz"]
    assert table.data["city"].tolist() == ["São Paulo", "北京", "पटना"]


def test_csv_handles_utf8_bom(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.csv"
    file_path.write_text(
        "customer_id,name\n1,Alice\n2,Bob\n",
        encoding="utf-8-sig",
    )

    table = CsvLoader(Settings()).load(file_path)

    assert list(table.data.columns) == ["customer_id", "name"]
    assert table.row_count == 2


def test_csv_preserves_quoted_commas_and_newlines(tmp_path: Path) -> None:
    file_path = tmp_path / "notes.csv"
    file_path.write_bytes(b'id,note\n1,"Hello, world"\n2,"First line\nSecond line"\n')

    table = CsvLoader(Settings()).load(file_path)

    assert table.row_count == 2
    assert table.data.loc[0, "note"] == "Hello, world"
    assert table.data.loc[1, "note"] == "First line\nSecond line"


def test_csv_preserves_missing_values(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.csv"
    file_path.write_text(
        "customer_id,name,score\n1,Alice,10\n2,,20\n3,Charlie,\n",
        encoding="utf-8",
    )

    table = CsvLoader(Settings()).load(file_path)
    schema = SchemaInferer().infer_table(table)

    columns = {column.name: column for column in schema.columns}

    assert table.row_count == 3
    assert columns["name"].missing_count == 1
    assert columns["name"].nullable is True
    assert columns["score"].missing_count == 1
    assert columns["score"].nullable is True


def test_csv_preserves_duplicate_rows(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.csv"
    file_path.write_text(
        "customer_id,name\n1,Alice\n1,Alice\n",
        encoding="utf-8",
    )

    table = CsvLoader(Settings()).load(file_path)

    assert table.row_count == 2
    assert table.data.iloc[0].equals(table.data.iloc[1])


def test_csv_preserves_mixed_type_column_without_coercion(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "mixed.csv"
    file_path.write_text(
        "id,value\n1,100\n2,unknown\n3,300\n",
        encoding="utf-8",
    )

    table = CsvLoader(Settings()).load(file_path)
    schema = SchemaInferer().infer_table(table)

    value_column = next(column for column in schema.columns if column.name == "value")

    assert table.data["value"].tolist() == ["100", "unknown", "300"]
    assert value_column.logical_type is LogicalType.STRING


def test_excel_preserves_unicode_and_missing_values(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.xlsx"

    source = pd.DataFrame(
        {
            "name": ["José", "李明", "Faiz"],
            "city": ["São Paulo", "北京", None],
        }
    )
    source.to_excel(file_path, index=False)

    workbook = ExcelLoader(Settings()).load(file_path)

    assert workbook.table_count == 1

    table = workbook.tables[0]
    schema = SchemaInferer().infer_table(table)
    columns = {column.name: column for column in schema.columns}

    assert table.data["name"].tolist() == ["José", "李明", "Faiz"]
    assert table.data.loc[0, "city"] == "São Paulo"
    assert table.data.loc[1, "city"] == "北京"
    assert pd.isna(table.data.loc[2, "city"])
    assert columns["city"].missing_count == 1


def test_excel_preserves_duplicate_rows(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.xlsx"

    pd.DataFrame(
        {
            "customer_id": [1, 1],
            "name": ["Alice", "Alice"],
        }
    ).to_excel(file_path, index=False)

    workbook = ExcelLoader(Settings()).load(file_path)
    table = workbook.tables[0]

    assert table.row_count == 2
    assert table.data.iloc[0].equals(table.data.iloc[1])


def test_excel_preserves_multiple_sheets_and_empty_sheet(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "business.xlsx"

    with pd.ExcelWriter(file_path) as writer:
        pd.DataFrame(
            {
                "customer_id": [1, 2],
            }
        ).to_excel(
            writer,
            sheet_name="Customers",
            index=False,
        )

        pd.DataFrame().to_excel(
            writer,
            sheet_name="Empty",
            index=False,
        )

        pd.DataFrame(
            {
                "order_id": [101],
            }
        ).to_excel(
            writer,
            sheet_name="Orders",
            index=False,
        )

    workbook = ExcelLoader(Settings()).load(file_path)

    assert workbook.table_count == 3
    assert [table.name for table in workbook.tables] == [
        "Customers",
        "Empty",
        "Orders",
    ]

    empty_table = workbook.tables[1]

    assert empty_table.row_count == 0
    assert empty_table.column_count == 0
    assert empty_table.source.sheet_name == "Empty"


def test_excel_preserves_mixed_type_column(tmp_path: Path) -> None:
    file_path = tmp_path / "mixed.xlsx"

    pd.DataFrame(
        {
            "value": [100, "unknown", 300],
        }
    ).to_excel(file_path, index=False)

    workbook = ExcelLoader(Settings()).load(file_path)
    table = workbook.tables[0]
    schema = SchemaInferer().infer_table(table)

    value_column = schema.columns[0]

    assert table.data["value"].tolist() == [100, "unknown", 300]
    assert value_column.logical_type is LogicalType.UNKNOWN


def test_json_preserves_unicode_text(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.json"
    file_path.write_text(
        '[{"name": "José", "city": "São Paulo"}, '
        '{"name": "李明", "city": "北京"}, '
        '{"name": "Faiz", "city": "पटना"}]',
        encoding="utf-8",
    )

    table = JsonLoader(Settings()).load(file_path)

    assert table.row_count == 3
    assert table.data["name"].tolist() == ["José", "李明", "Faiz"]
    assert table.data["city"].tolist() == ["São Paulo", "北京", "पटना"]


def test_json_preserves_null_and_missing_fields(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.json"
    file_path.write_text(
        '[{"id": 1, "name": "Alice"}, {"id": 2, "name": null}, {"id": 3}]',
        encoding="utf-8",
    )

    table = JsonLoader(Settings()).load(file_path)
    schema = SchemaInferer().infer_table(table)

    columns = {column.name: column for column in schema.columns}

    assert table.row_count == 3
    assert columns["name"].nullable is True
    assert columns["name"].missing_count == 2


def test_json_preserves_nested_values(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.json"
    file_path.write_text(
        '[{"id": 1, "profile": {"city": "Patna"}}, '
        '{"id": 2, "profile": {"city": "Delhi"}}]',
        encoding="utf-8",
    )

    table = JsonLoader(Settings()).load(file_path)
    schema = SchemaInferer().infer_table(table)

    profile_column = next(
        column for column in schema.columns if column.name == "profile"
    )

    assert table.data.loc[0, "profile"] == {"city": "Patna"}
    assert table.data.loc[1, "profile"] == {"city": "Delhi"}
    assert profile_column.logical_type is LogicalType.UNKNOWN


def test_json_preserves_heterogeneous_object_keys(tmp_path: Path) -> None:
    file_path = tmp_path / "events.json"
    file_path.write_text(
        '[{"id": 1, "name": "Alice"}, {"id": 2, "score": 95}]',
        encoding="utf-8",
    )

    table = JsonLoader(Settings()).load(file_path)

    assert table.row_count == 2
    assert list(table.data.columns) == ["id", "name", "score"]
    assert table.data.loc[0, "name"] == "Alice"
    assert pd.isna(table.data.loc[1, "name"])
    assert pd.isna(table.data.loc[0, "score"])
    assert table.data.loc[1, "score"] == 95


def test_json_preserves_duplicate_objects(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.json"
    file_path.write_text(
        '[{"id": 1, "name": "Alice"}, {"id": 1, "name": "Alice"}]',
        encoding="utf-8",
    )

    table = JsonLoader(Settings()).load(file_path)

    assert table.row_count == 2
    assert table.data.iloc[0].equals(table.data.iloc[1])


def test_json_preserves_empty_array_as_empty_table(tmp_path: Path) -> None:
    file_path = tmp_path / "empty.json"
    file_path.write_text("[]", encoding="utf-8")

    table = JsonLoader(Settings()).load(file_path)
    schema = SchemaInferer().infer_table(table)

    assert table.row_count == 0
    assert table.column_count == 0
    assert schema.row_count == 0
    assert schema.column_count == 0
    assert schema.columns == ()


def test_messy_multi_file_dataset_preserves_data_and_schema(
    tmp_path: Path,
) -> None:
    csv_path = tmp_path / "customers.csv"
    csv_path.write_text(
        "customer_id,name,segment\n1,José,A\n2,,B\n3,李明,A\n",
        encoding="utf-8",
    )

    json_path = tmp_path / "events.json"
    json_path.write_text(
        '[{"event_id": 101, "metadata": {"source": "web"}}, '
        '{"event_id": 102, "metadata": {"source": "mobile"}}]',
        encoding="utf-8",
    )

    excel_path = tmp_path / "business.xlsx"

    with pd.ExcelWriter(excel_path) as writer:
        pd.DataFrame(
            {
                "order_id": [1001, 1002],
                "amount": [99.5, None],
            }
        ).to_excel(
            writer,
            sheet_name="Orders",
            index=False,
        )

        pd.DataFrame().to_excel(
            writer,
            sheet_name="Empty",
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
        "Empty",
    ]

    schema = SchemaInferer().infer_dataset(dataset)

    assert schema.table_count == 4

    schemas = {table.name: table for table in schema.tables}

    customers_schema = schemas["customers"]
    customer_columns = {column.name: column for column in customers_schema.columns}

    assert customers_schema.row_count == 3
    assert customer_columns["name"].missing_count == 1
    assert customer_columns["name"].nullable is True

    events_schema = schemas["events"]
    event_columns = {column.name: column for column in events_schema.columns}

    assert events_schema.row_count == 2
    assert event_columns["metadata"].logical_type is LogicalType.UNKNOWN

    orders_schema = schemas["Orders"]
    order_columns = {column.name: column for column in orders_schema.columns}

    assert orders_schema.row_count == 2
    assert order_columns["amount"].missing_count == 1
    assert order_columns["amount"].nullable is True

    empty_schema = schemas["Empty"]

    assert empty_schema.row_count == 0
    assert empty_schema.column_count == 0
    assert empty_schema.columns == ()

    assert dataset.tables[0].source.path == csv_path
    assert dataset.tables[1].source.path == json_path
    assert dataset.tables[2].source.path == excel_path
    assert dataset.tables[2].source.sheet_name == "Orders"
    assert dataset.tables[3].source.path == excel_path
    assert dataset.tables[3].source.sheet_name == "Empty"
