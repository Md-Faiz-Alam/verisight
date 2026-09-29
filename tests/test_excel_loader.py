from pathlib import Path

import pandas as pd
import pytest

from verisight.config import Settings
from verisight.ingestion.exceptions import (
    DataLoadError,
    FileValidationError,
)
from verisight.ingestion.loaders.excel import ExcelLoader


def test_excel_loader_loads_single_sheet_workbook(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "customers.xlsx"

    expected = pd.DataFrame(
        {
            "customer_id": [1, 2],
            "name": ["Alice", "Bob"],
        }
    )
    expected.to_excel(file_path, index=False, sheet_name="Customers")

    loader = ExcelLoader(Settings())
    workbook = loader.load(file_path)

    assert workbook.table_count == 1

    table = workbook.tables[0]

    assert table.name == "Customers"
    assert table.source.sheet_name == "Customers"

    pd.testing.assert_frame_equal(table.data, expected)


def test_excel_loader_loads_all_sheets(tmp_path: Path) -> None:
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

    loader = ExcelLoader(Settings())
    workbook = loader.load(file_path)

    assert workbook.table_count == 2
    assert [table.name for table in workbook.tables] == [
        "Customers",
        "Orders",
    ]

    pd.testing.assert_frame_equal(
        workbook.tables[0].data,
        customers,
    )
    pd.testing.assert_frame_equal(
        workbook.tables[1].data,
        orders,
    )


def test_excel_loader_preserves_sheet_provenance(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "finance.xlsx"

    data = pd.DataFrame({"amount": [100, 200]})
    data.to_excel(file_path, index=False, sheet_name="Transactions")

    loader = ExcelLoader(Settings())
    workbook = loader.load(file_path)

    table = workbook.tables[0]

    assert table.source.path == file_path
    assert table.source.file_name == "finance.xlsx"
    assert table.source.file_extension == ".xlsx"
    assert table.source.sheet_name == "Transactions"


def test_excel_loader_rejects_non_excel_file(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.csv"
    file_path.write_text("id\n1\n", encoding="utf-8")

    loader = ExcelLoader(Settings())

    with pytest.raises(
        DataLoadError,
        match="ExcelLoader cannot load file type",
    ):
        loader.load(file_path)


def test_excel_loader_rejects_empty_file(tmp_path: Path) -> None:
    file_path = tmp_path / "empty.xlsx"
    file_path.touch()

    loader = ExcelLoader(Settings())

    with pytest.raises(FileValidationError, match="File is empty"):
        loader.load(file_path)


def test_excel_loader_wraps_read_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "broken.xlsx"
    file_path.write_bytes(b"not-a-real-excel-workbook")

    def raise_read_error(
        *args: object,
        **kwargs: object,
    ) -> dict[str, pd.DataFrame]:
        raise ValueError("broken workbook")

    monkeypatch.setattr(pd, "read_excel", raise_read_error)

    loader = ExcelLoader(Settings())

    with pytest.raises(DataLoadError, match="Could not load Excel file"):
        loader.load(file_path)
