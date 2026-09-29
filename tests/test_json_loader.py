import json
from pathlib import Path

import pandas as pd
import pytest

from verisight.config import Settings
from verisight.ingestion.exceptions import (
    DataLoadError,
    FileValidationError,
)
from verisight.ingestion.loaders.base import BaseTableLoader
from verisight.ingestion.loaders.json import JsonLoader


def test_json_loader_implements_base_loader() -> None:
    loader = JsonLoader(Settings())

    assert isinstance(loader, BaseTableLoader)


def test_json_loader_loads_array_of_records(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.json"

    payload = [
        {"customer_id": 1, "name": "Alice"},
        {"customer_id": 2, "name": "Bob"},
    ]

    file_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    loader = JsonLoader(Settings())
    table = loader.load(file_path)

    assert table.name == "customers"
    assert table.row_count == 2
    assert table.column_count == 2
    assert table.source.path == file_path
    assert table.source.file_extension == ".json"

    pd.testing.assert_frame_equal(
        table.data,
        pd.DataFrame(payload),
    )


def test_json_loader_loads_single_object(tmp_path: Path) -> None:
    file_path = tmp_path / "customer.json"

    payload = {
        "customer_id": 1,
        "name": "Alice",
    }

    file_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    loader = JsonLoader(Settings())
    table = loader.load(file_path)

    assert table.row_count == 1

    pd.testing.assert_frame_equal(
        table.data,
        pd.DataFrame([payload]),
    )


def test_json_loader_preserves_nested_values(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.json"

    payload = [
        {
            "customer_id": 1,
            "address": {
                "city": "Patna",
                "country": "India",
            },
        }
    ]

    file_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    loader = JsonLoader(Settings())
    table = loader.load(file_path)

    assert table.data.loc[0, "address"] == {
        "city": "Patna",
        "country": "India",
    }


def test_json_loader_supports_utf8_bom(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.json"

    file_path.write_text(
        '[{"customer_id": 1}]',
        encoding="utf-8-sig",
    )

    loader = JsonLoader(Settings())
    table = loader.load(file_path)

    assert table.row_count == 1


def test_json_loader_returns_empty_table_for_empty_array(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "empty-array.json"
    file_path.write_text("[]", encoding="utf-8")

    loader = JsonLoader(Settings())
    table = loader.load(file_path)

    assert table.row_count == 0
    assert table.column_count == 0


def test_json_loader_rejects_array_of_non_objects(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "values.json"
    file_path.write_text("[1, 2, 3]", encoding="utf-8")

    loader = JsonLoader(Settings())

    with pytest.raises(
        DataLoadError,
        match="JSON array must contain objects",
    ):
        loader.load(file_path)


def test_json_loader_rejects_scalar_root(tmp_path: Path) -> None:
    file_path = tmp_path / "value.json"
    file_path.write_text("42", encoding="utf-8")

    loader = JsonLoader(Settings())

    with pytest.raises(
        DataLoadError,
        match="JSON root must be an object or array of objects",
    ):
        loader.load(file_path)


def test_json_loader_rejects_malformed_json(tmp_path: Path) -> None:
    file_path = tmp_path / "broken.json"
    file_path.write_text(
        '{"customer_id": 1',
        encoding="utf-8",
    )

    loader = JsonLoader(Settings())

    with pytest.raises(
        DataLoadError,
        match="Could not load JSON file",
    ):
        loader.load(file_path)


def test_json_loader_rejects_non_json_file(tmp_path: Path) -> None:
    file_path = tmp_path / "customers.csv"
    file_path.write_text("id\n1\n", encoding="utf-8")

    loader = JsonLoader(Settings())

    with pytest.raises(
        DataLoadError,
        match="JsonLoader cannot load file type",
    ):
        loader.load(file_path)


def test_json_loader_rejects_empty_file(tmp_path: Path) -> None:
    file_path = tmp_path / "empty.json"
    file_path.touch()

    loader = JsonLoader(Settings())

    with pytest.raises(FileValidationError, match="File is empty"):
        loader.load(file_path)
