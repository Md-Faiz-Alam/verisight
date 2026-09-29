from pathlib import Path

import pandas as pd
import pytest

from verisight.config import Settings
from verisight.ingestion.dispatcher import FileLoader
from verisight.ingestion.exceptions import (
    FileValidationError,
    UnsupportedFileTypeError,
)
from verisight.ingestion.models import LoadedTable, LoadedWorkbook


def test_file_loader_dispatches_csv(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.csv"
    file_path.write_text(
        "customer_id,name\n1,Alice\n2,Bob\n",
        encoding="utf-8",
    )

    loader = FileLoader(Settings())
    result = loader.load(file_path)

    assert isinstance(result, LoadedTable)
    assert result.name == "customers"
    assert result.row_count == 2


def test_file_loader_dispatches_json(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.json"
    file_path.write_text(
        '[{"customer_id": 1, "name": "Alice"}]',
        encoding="utf-8",
    )

    loader = FileLoader(Settings())
    result = loader.load(file_path)

    assert isinstance(result, LoadedTable)
    assert result.name == "customers"
    assert result.row_count == 1


def test_file_loader_dispatches_excel(tmp_path: Path) -> None:
    file_path = tmp_path / "business.xlsx"

    expected = pd.DataFrame(
        {
            "customer_id": [1, 2],
            "name": ["Alice", "Bob"],
        }
    )
    expected.to_excel(
        file_path,
        sheet_name="Customers",
        index=False,
    )

    loader = FileLoader(Settings())
    result = loader.load(file_path)

    assert isinstance(result, LoadedWorkbook)
    assert result.table_count == 1
    assert result.tables[0].name == "Customers"

    pd.testing.assert_frame_equal(
        result.tables[0].data,
        expected,
    )


def test_file_loader_normalizes_uppercase_extension(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "CUSTOMERS.CSV"
    file_path.write_text(
        "customer_id,name\n1,Alice\n",
        encoding="utf-8",
    )

    loader = FileLoader(Settings())
    result = loader.load(file_path)

    assert isinstance(result, LoadedTable)
    assert result.row_count == 1


@pytest.mark.parametrize(
    "file_name",
    [
        "customers.txt",
        "customers.parquet",
        "customers",
    ],
)
def test_file_loader_rejects_unsupported_file_type(
    tmp_path: Path,
    file_name: str,
) -> None:
    file_path = tmp_path / file_name
    file_path.write_text("data", encoding="utf-8")

    loader = FileLoader(Settings())

    with pytest.raises(UnsupportedFileTypeError):
        loader.load(file_path)


def test_file_loader_preserves_validation_errors(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "missing.csv"

    loader = FileLoader(Settings())

    with pytest.raises(
        FileValidationError,
        match="File does not exist",
    ):
        loader.load(file_path)
