from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from verisight import VeriSight
from verisight.config import Settings
from verisight.error_reporting import ErrorCode
from verisight.ingestion.dispatcher import FileLoader
from verisight.ingestion.exceptions import (
    FileValidationError,
    UnsupportedFileTypeError,
)
from verisight.ingestion.models import LoadedTable, LoadedWorkbook
from verisight.public_api import run_public_operation


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


@pytest.mark.parametrize(
    "invalid_path", [None, 42, True, 1.5, b"private.csv", object()]
)
def test_file_loader_classifies_invalid_path_types(invalid_path: Any) -> None:
    with pytest.raises(FileValidationError, match="must be a string or path"):
        FileLoader(Settings()).load(invalid_path)


@pytest.mark.parametrize(
    "directory_name", ["private-data", "private.csv", "private.txt"]
)
def test_file_loader_rejects_directories_before_extension_dispatch(
    tmp_path: Path, directory_name: str
) -> None:
    path = tmp_path / directory_name
    path.mkdir()

    with pytest.raises(FileValidationError, match="Path is not a file"):
        FileLoader(Settings()).load(path)


@pytest.mark.parametrize("operation", ["analyze", "execute", "ask", "investigate"])
@pytest.mark.parametrize(
    "scenario", ["none_entry", "integer_entry", "directory", "directory_txt"]
)
def test_public_workflows_classify_invalid_dataset_entries(
    tmp_path: Path, operation: str, scenario: str
) -> None:
    invalid_path: Any = None
    if scenario == "integer_entry":
        invalid_path = 42
    elif scenario in {"directory", "directory_txt"}:
        name = "private-data.txt" if scenario == "directory_txt" else "private-data"
        invalid_path = tmp_path / name
        invalid_path.mkdir()

    app = VeriSight(settings=Settings(allow_llm_data_disclosure=False))
    operations: dict[str, Callable[[], object]] = {
        "analyze": lambda: app.analyze([invalid_path]),
        "execute": lambda: app.execute([invalid_path], "SELECT 1"),
        "ask": lambda: app.ask([invalid_path], "Count the rows"),
        "investigate": lambda: app.investigate([invalid_path], "Count the rows"),
    }

    result = run_public_operation(operations[operation])

    assert result.succeeded is False
    assert result.value is None
    assert result.error is not None
    assert result.error.code is ErrorCode.FILE_VALIDATION_ERROR
    assert "private-data" not in repr(result)
    assert str(tmp_path) not in repr(result)
