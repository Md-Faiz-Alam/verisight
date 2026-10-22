import json
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from verisight import VeriSight
from verisight.config import Settings
from verisight.execution.claim_verification import (
    ClaimOperation,
    EvidenceReference,
    NumericalClaim,
    NumericalClaimVerifier,
    VerificationStatus,
)
from verisight.execution.observations import QueryObservation
from verisight.ingestion.exceptions import (
    DataLoadError,
    FileValidationError,
)
from verisight.ingestion.loaders.base import BaseTableLoader
from verisight.ingestion.loaders.json import JsonLoader
from verisight.ingestion.schema import LogicalType, SchemaInferer
from verisight.serialization import to_jsonable


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
    [[1.5, None], [1, 1.5], [True, False], [None, None], ["NA", "00123"]],
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


@pytest.mark.parametrize(
    "values",
    [
        [True, None],
        [False, None],
        [None, True, False],
        [True, False, None],
        [True, False],
    ],
)
def test_json_boolean_columns_have_boolean_schema(
    tmp_path: Path, values: list[bool | None]
) -> None:
    path = tmp_path / "flags.json"
    path.write_text(
        json.dumps([{"active": value} for value in values]), encoding="utf-8"
    )

    table = JsonLoader(Settings()).load(path)
    missing_count = values.count(None)
    expected_dtype = "boolean" if missing_count else "bool"
    pd.testing.assert_series_equal(
        table.data["active"], pd.Series(values, name="active", dtype=expected_dtype)
    )
    column = SchemaInferer().infer_table(table).columns[0]
    assert column.logical_type is LogicalType.BOOLEAN
    assert column.nullable is (missing_count > 0)
    assert column.missing_count == missing_count


def test_json_missing_boolean_key_preserves_row_order(tmp_path: Path) -> None:
    data = _load_records(tmp_path, [{}, {"active": False}, {"active": True}])

    pd.testing.assert_series_equal(
        data["active"],
        pd.Series([None, False, True], name="active", dtype="boolean"),
    )


@pytest.mark.parametrize("other", [0, 1, 1.5, "false", {"nested": True}, [False]])
def test_json_mixed_boolean_column_preserves_original_types(
    tmp_path: Path, other: Any
) -> None:
    data = _load_records(tmp_path, [{"value": True}, {"value": other}, {"value": None}])

    assert data["value"].dtype == object
    assert data["value"].iloc[0] is True
    assert type(data["value"].iloc[1]) is type(other)
    assert data["value"].iloc[1] == other
    assert data["value"].iloc[2] is None


def test_json_nullable_booleans_survive_sql_execution(tmp_path: Path) -> None:
    path = tmp_path / "flags.json"
    path.write_text(
        json.dumps(
            [
                {"row_id": 1, "active": True},
                {"row_id": 2, "active": False},
                {"row_id": 3, "active": None},
                {"row_id": 4},
            ]
        ),
        encoding="utf-8",
    )
    app = VeriSight(settings=Settings(allow_llm_data_disclosure=False))

    result = app.execute([path], "SELECT active FROM flags ORDER BY row_id")

    assert result.rows == ((True,), (False,), (None,), (None,))
    assert result.rows[0][0] is True
    assert result.rows[1][0] is False

    filtered = app.execute([path], "SELECT row_id FROM flags WHERE active IS TRUE")

    assert filtered.rows == ((1,),)


@pytest.mark.parametrize(
    "payload",
    [
        '{"value":1,"value":9}',
        '[{"value":1,"value":9}]',
        '[{"nested":{"value":1,"value":9}}]',
        '[{"nested":[{"value":1,"value":9}]}]',
        '{"value":1,"\\u0076alue":9}',
    ],
)
def test_json_loader_rejects_duplicate_keys(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "records.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(DataLoadError, match="Could not load JSON file"):
        JsonLoader(Settings()).load(path)


def test_json_loader_allows_same_key_in_different_objects(tmp_path: Path) -> None:
    data = _load_records(tmp_path, [{"value": 1}, {"value": 9}])
    assert data["value"].tolist() == [1, 9]


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity"])
def test_json_loader_rejects_nonstandard_numbers(tmp_path: Path, token: str) -> None:
    path = tmp_path / "records.json"
    path.write_text('[{"value":' + token + "}]", encoding="utf-8")
    with pytest.raises(DataLoadError, match="Could not load JSON file"):
        JsonLoader(Settings()).load(path)


@pytest.mark.parametrize(
    "token",
    [
        "9007199254740993.0",
        "12345678901234567.89",
        "0.1234567890123456789012345",
        "1.234567890123456789e-9",
        "1e-400",
        "1e400",
    ],
)
def test_json_loader_preserves_decimal_tokens(tmp_path: Path, token: str) -> None:
    path = tmp_path / "records.json"
    path.write_text(
        '[{"value":' + token + '},{"value":0.5},{"value":null}]', encoding="utf-8"
    )
    table = JsonLoader(Settings()).load(path)
    assert table.data["value"].dtype == object
    assert type(table.data["value"].iloc[0]) is Decimal
    assert table.data["value"].iloc[0] == Decimal(token)
    assert table.data["value"].iloc[1] == 0.5
    assert table.data["value"].iloc[2] is None
    # Existing schema inference deliberately does not label Decimal objects
    # as native floating-point data or compute approximate float statistics.
    assert (
        SchemaInferer().infer_table(table).columns[0].logical_type
        is LogicalType.UNKNOWN
    )


def test_json_loader_preserves_nested_decimals(tmp_path: Path) -> None:
    path = tmp_path / "records.json"
    path.write_text(
        '[{"nested":{"value":9007199254740993.0,"items":[1e-400,0.5]}}]',
        encoding="utf-8",
    )
    table = JsonLoader(Settings()).load(path)
    nested = table.data["nested"].iloc[0]
    assert nested["value"] == Decimal("9007199254740993.0")
    assert nested["items"] == [Decimal("1e-400"), 0.5]
    assert to_jsonable(nested) == {
        "value": "9007199254740993.0",
        "items": ["1E-400", 0.5],
    }


@pytest.mark.parametrize(
    "token",
    [
        "9007199254740993.0",
        "12345678901234567.89",
        "0.1234567890123456789012345",
        "1.234567890123456789e-9",
    ],
)
def test_json_decimal_survives_analysis_sql_and_verification(
    tmp_path: Path, token: str
) -> None:
    path = tmp_path / "records.json"
    path.write_text('[{"value":' + token + "}]", encoding="utf-8")
    app = VeriSight(settings=Settings(allow_llm_data_disclosure=False))
    assert app.analyze(path).analysis.schema.tables[0].row_count == 1
    sql = 'SELECT "value" FROM records'
    result = app.execute(path, sql)
    expected = Decimal(token)
    assert result.rows == ((expected,),)
    assert type(result.rows[0][0]) is Decimal
    claim = NumericalClaim(
        operation=ClaimOperation.VALUE,
        expected=expected,
        left=EvidenceReference(0, 0, "value"),
    )
    verdict = NumericalClaimVerifier().verify(
        claim, (QueryObservation("Get value", sql, result),)
    )
    assert verdict.status is VerificationStatus.SUPPORTED
    assert verdict.actual == expected
    payload = to_jsonable(result)
    assert isinstance(payload, dict)
    assert payload["rows"] == [[str(result.rows[0][0])]]


def test_json_loader_wraps_excessive_nesting(tmp_path: Path) -> None:
    path = tmp_path / "records.json"
    path.write_text("[" * 10000 + "0" + "]" * 10000, encoding="utf-8")
    with pytest.raises(DataLoadError, match="Could not load JSON file"):
        JsonLoader(Settings()).load(path)


def test_json_loader_wraps_unrepresentable_decimal_exponent(tmp_path: Path) -> None:
    path = tmp_path / "records.json"
    path.write_text('[{"value":1e' + "9" * 100 + "}]", encoding="utf-8")
    with pytest.raises(DataLoadError, match="Could not load JSON file"):
        JsonLoader(Settings()).load(path)
