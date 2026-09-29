from pathlib import Path

import pandas as pd
import pytest

from verisight.config import Settings
from verisight.ingestion.exceptions import (
    DataLoadError,
    FileValidationError,
)
from verisight.ingestion.loaders.base import BaseTableLoader
from verisight.ingestion.loaders.csv import CsvLoader


def test_csv_loader_implements_base_loader() -> None:
    loader = CsvLoader(Settings())

    assert isinstance(loader, BaseTableLoader)


def test_csv_loader_loads_valid_csv(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.csv"
    file_path.write_text(
        "customer_id,name\n1,Alice\n2,Bob\n",
        encoding="utf-8",
    )

    loader = CsvLoader(Settings())
    table = loader.load(file_path)

    assert table.name == "customers"
    assert table.row_count == 2
    assert table.column_count == 2
    assert table.source.path == file_path
    assert table.source.file_extension == ".csv"

    pd.testing.assert_frame_equal(
        table.data,
        pd.DataFrame(
            {
                "customer_id": [1, 2],
                "name": ["Alice", "Bob"],
            }
        ),
    )


def test_csv_loader_preserves_missing_values(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.csv"
    file_path.write_text(
        "customer_id,name\n1,Alice\n2,\n",
        encoding="utf-8",
    )

    loader = CsvLoader(Settings())
    table = loader.load(file_path)

    assert pd.isna(table.data.loc[1, "name"])


def test_csv_loader_supports_quoted_commas(tmp_path: Path) -> None:
    file_path = tmp_path / "companies.csv"
    file_path.write_text(
        'id,company\n1,"Smith, Jones & Co."\n',
        encoding="utf-8",
    )

    loader = CsvLoader(Settings())
    table = loader.load(file_path)

    assert table.data.loc[0, "company"] == "Smith, Jones & Co."


def test_csv_loader_rejects_non_csv_file(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.json"
    file_path.write_text(
        '[{"customer_id": 1}]',
        encoding="utf-8",
    )

    loader = CsvLoader(Settings())

    with pytest.raises(
        DataLoadError,
        match="CsvLoader cannot load file type",
    ):
        loader.load(file_path)


def test_csv_loader_rejects_empty_file(tmp_path: Path) -> None:
    file_path = tmp_path / "empty.csv"
    file_path.touch()

    loader = CsvLoader(Settings())

    with pytest.raises(FileValidationError, match="File is empty"):
        loader.load(file_path)


def test_csv_loader_wraps_parser_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "broken.csv"
    file_path.write_text("id,name\n1,Alice\n", encoding="utf-8")

    def raise_parser_error(*args: object, **kwargs: object) -> pd.DataFrame:
        raise pd.errors.ParserError("broken CSV")

    monkeypatch.setattr(pd, "read_csv", raise_parser_error)

    loader = CsvLoader(Settings())

    with pytest.raises(DataLoadError, match="Could not load CSV file"):
        loader.load(file_path)
