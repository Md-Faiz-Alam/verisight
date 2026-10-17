import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from verisight import VeriSight
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


def test_json_loader_wraps_dataframe_value_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "customers.json"
    file_path.write_text(
        '[{"customer_id": 1}]',
        encoding="utf-8",
    )

    def raise_conversion_error(
        *args: object,
        **kwargs: object,
    ) -> pd.DataFrame:
        raise ValueError("conversion failed")

    monkeypatch.setattr(pd, "DataFrame", raise_conversion_error)

    with pytest.raises(
        DataLoadError,
        match="Could not convert JSON data into a table",
    ):
        JsonLoader(Settings()).load(file_path)


def test_json_loader_preserves_structure_errors(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "invalid.json"
    file_path.write_text(
        '[{"id": 1}, 42]',
        encoding="utf-8",
    )

    with pytest.raises(
        DataLoadError,
        match="JSON array must contain objects",
    ):
        JsonLoader(Settings()).load(file_path)


def _load_records(tmp_path: Path, records: list[dict[str, Any]]) -> pd.DataFrame:
    path = tmp_path / "records.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    return JsonLoader(Settings()).load(path).data


@pytest.mark.parametrize(
    ("values", "expected_dtype"),
    [
        ([1, 2], "int64"),
        ([1, None], "Int64"),
        ([2**53 + 1, None], "Int64"),
        ([-(2**53 + 1), None], "Int64"),
        ([-(2**63), 2**63 - 1], "int64"),
        ([-(2**63), None, 2**63 - 1], "Int64"),
        ([2**63, 2**64 - 1], "uint64"),
        ([2**63, None, 2**64 - 1], "UInt64"),
        ([2**64, None], "object"),
        ([-(2**63) - 1, None], "object"),
        ([-1, 2**63], "object"),
        ([10**100, None], "object"),
    ],
)
def test_exact_integer_columns(
    tmp_path: Path,
    values: list[int | None],
    expected_dtype: str,
) -> None:
    data = _load_records(tmp_path, [{"id": value} for value in values])

    assert str(data["id"].dtype) == expected_dtype
    for index, expected in enumerate(values):
        actual = data["id"].iloc[index]
        if expected is None:
            assert pd.isna(actual)
        else:
            assert int(actual) == expected


def test_missing_key_preserves_integer_and_record_order(tmp_path: Path) -> None:
    data = _load_records(tmp_path, [{}, {"id": 2**53 + 1}, {"id": None}])

    assert len(data) == 3
    assert str(data["id"].dtype) == "Int64"
    assert data["id"].isna().tolist() == [True, False, True]
    assert int(data["id"].iloc[1]) == 2**53 + 1


@pytest.mark.parametrize("other", [1.5, True, "00123", {"nested": 1}, [1, 2]])
def test_mixed_columns_preserve_large_integer(tmp_path: Path, other: Any) -> None:
    data = _load_records(
        tmp_path,
        [{"value": 2**53 + 1}, {"value": other}, {"value": None}],
    )

    assert str(data["value"].dtype) == "object"
    assert type(data["value"].iloc[0]) is int
    assert data["value"].iloc[0] == 2**53 + 1
    assert data["value"].iloc[1] == other
    assert data["value"].iloc[2] is None


@pytest.mark.parametrize(
    "values",
    [[1.5, None], [1, 1.5], [True, False], [True, None], [None, None], ["NA", "00123"]],
)
def test_other_column_inference_remains_compatible(
    tmp_path: Path, values: list[Any]
) -> None:
    records = [{"value": value} for value in values]
    pd.testing.assert_frame_equal(
        _load_records(tmp_path, records), pd.DataFrame(records)
    )


def test_empty_objects_keep_their_rows(tmp_path: Path) -> None:
    data = _load_records(tmp_path, [{}, {}])
    assert data.shape == (2, 0)


def test_nullable_large_integer_remains_exact_through_sql(tmp_path: Path) -> None:
    path = tmp_path / "records.json"
    path.write_text('[{"id":9007199254740993},{"id":null}]', encoding="utf-8")
    app = VeriSight(settings=Settings(allow_llm_data_disclosure=False))

    result = app.execute(
        [path],
        "SELECT id FROM records WHERE id IS NOT NULL",
    )

    assert result.rows == ((9007199254740993,),)
