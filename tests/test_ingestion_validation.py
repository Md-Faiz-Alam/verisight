from pathlib import Path

import pytest

from verisight.ingestion.exceptions import (
    FileValidationError,
    UnsupportedFileTypeError,
)
from verisight.ingestion.validation import (
    SUPPORTED_FILE_EXTENSIONS,
    validate_file,
)


def test_validate_file_returns_source_metadata(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.csv"
    file_path.write_text("id,name\n1,Alice\n", encoding="utf-8")

    metadata = validate_file(file_path, max_size_mb=10)

    assert metadata.path == file_path
    assert metadata.file_name == "customers.csv"
    assert metadata.file_extension == ".csv"
    assert metadata.file_size_bytes == file_path.stat().st_size


def test_validate_file_accepts_string_path(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.csv"
    file_path.write_text("id\n1\n", encoding="utf-8")

    metadata = validate_file(str(file_path), max_size_mb=10)

    assert metadata.path == file_path


def test_validate_file_normalizes_extension_case(tmp_path: Path) -> None:
    file_path = tmp_path / "CUSTOMERS.CSV"
    file_path.write_text("id\n1\n", encoding="utf-8")

    metadata = validate_file(file_path, max_size_mb=10)

    assert metadata.file_extension == ".csv"


def test_validate_file_rejects_missing_file(tmp_path: Path) -> None:
    file_path = tmp_path / "missing.csv"

    with pytest.raises(FileValidationError, match="File does not exist"):
        validate_file(file_path, max_size_mb=10)


def test_validate_file_rejects_directory(tmp_path: Path) -> None:
    with pytest.raises(FileValidationError, match="Path is not a file"):
        validate_file(tmp_path, max_size_mb=10)


@pytest.mark.parametrize(
    "file_name",
    [
        "dataset.txt",
        "dataset.parquet",
        "dataset",
    ],
)
def test_validate_file_rejects_unsupported_file_type(
    tmp_path: Path,
    file_name: str,
) -> None:
    file_path = tmp_path / file_name
    file_path.write_text("data", encoding="utf-8")

    with pytest.raises(UnsupportedFileTypeError, match="Unsupported file type"):
        validate_file(file_path, max_size_mb=10)


def test_validate_file_rejects_empty_file(tmp_path: Path) -> None:
    file_path = tmp_path / "empty.csv"
    file_path.touch()

    with pytest.raises(FileValidationError, match="File is empty"):
        validate_file(file_path, max_size_mb=10)


def test_validate_file_rejects_file_above_size_limit(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "large.csv"
    file_path.write_bytes(b"x" * (1024 * 1024 + 1))

    with pytest.raises(
        FileValidationError,
        match="File exceeds maximum size",
    ):
        validate_file(file_path, max_size_mb=1)


def test_supported_file_extensions_are_expected() -> None:
    assert (
        frozenset(
            {
                ".csv",
                ".json",
                ".xls",
                ".xlsx",
            }
        )
        == SUPPORTED_FILE_EXTENSIONS
    )
