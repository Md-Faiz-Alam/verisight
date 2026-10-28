import codecs
from pathlib import Path

import pandas as pd
import pytest

from verisight import VeriSight
from verisight.config import Settings
from verisight.ingestion.exceptions import (
    DataLoadError,
    FileValidationError,
)
from verisight.ingestion.loaders.base import BaseTableLoader
from verisight.ingestion.loaders.csv import CsvLoader
from verisight.ingestion.models import CsvReadOptions


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


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_csv_loader_supports_quoted_commas(tmp_path: Path, newline: str) -> None:
    file_path = tmp_path / "companies.csv"
    content = 'id,company\n1,"Smith, Jones & Co."\n'
    file_path.write_bytes(content.replace("\n", newline).encode("utf-8"))

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


def test_csv_loader_preserves_significant_leading_zeros(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "identifiers.csv"
    file_path.write_text(
        "zip_code,phone\n02134,0091234\n10001,0012345\n",
        encoding="utf-8",
    )

    loader = CsvLoader(Settings())
    table = loader.load(file_path)

    assert table.data["zip_code"].tolist() == ["02134", "10001"]
    assert table.data["phone"].tolist() == ["0091234", "0012345"]


def test_csv_loader_preserves_long_integer_identifiers_with_missing_values(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "identifiers.csv"
    file_path.write_text(
        "account_id,name\n12345678901234567,Alice\n,Bob\n12345678901234569,Charlie\n",
        encoding="utf-8",
    )

    loader = CsvLoader(Settings())
    table = loader.load(file_path)

    assert table.data.loc[0, "account_id"] == "12345678901234567"
    assert pd.isna(table.data.loc[1, "account_id"])
    assert table.data.loc[2, "account_id"] == "12345678901234569"


def test_csv_loader_keeps_ordinary_numeric_columns_numeric(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "measurements.csv"
    file_path.write_text(
        "quantity,price\n10,19.95\n20,25.50\n",
        encoding="utf-8",
    )

    loader = CsvLoader(Settings())
    table = loader.load(file_path)

    assert table.data["quantity"].tolist() == [10, 20]
    assert table.data["price"].tolist() == [19.95, 25.50]
    assert pd.api.types.is_integer_dtype(table.data["quantity"])
    assert pd.api.types.is_float_dtype(table.data["price"])


def test_csv_loader_infers_boolean_columns(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "flags.csv"
    file_path.write_text(
        "active\ntrue\nfalse\nTRUE\n",
        encoding="utf-8",
    )

    loader = CsvLoader(Settings())
    table = loader.load(file_path)

    assert table.data["active"].tolist() == [True, False, True]
    assert pd.api.types.is_bool_dtype(table.data["active"])


def test_csv_loader_preserves_ambiguous_boolean_like_values_as_strings(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "flags.csv"
    file_path.write_text(
        "flag\nyes\nno\n",
        encoding="utf-8",
    )

    loader = CsvLoader(Settings())
    table = loader.load(file_path)

    assert table.data["flag"].tolist() == ["yes", "no"]
    assert pd.api.types.is_object_dtype(table.data["flag"])


def test_csv_loader_infers_nullable_boolean_columns(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "flags.csv"
    file_path.write_text(
        "active,name\ntrue,Alice\n,Bob\nfalse,Charlie\n",
        encoding="utf-8",
    )

    loader = CsvLoader(Settings())
    table = loader.load(file_path)

    assert bool(table.data.loc[0, "active"]) is True
    assert pd.isna(table.data.loc[1, "active"])
    assert bool(table.data.loc[2, "active"]) is False
    assert str(table.data["active"].dtype) == "boolean"


def test_csv_loader_preserves_entirely_missing_column(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "missing.csv"
    file_path.write_text(
        "id,notes\n1,\n2,\n",
        encoding="utf-8",
    )

    loader = CsvLoader(Settings())
    table = loader.load(file_path)

    assert table.data["notes"].isna().all()


def test_csv_loader_converts_signed_integer_columns(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "measurements.csv"
    file_path.write_text(
        "change\n-10\n+20\n30\n",
        encoding="utf-8",
    )

    loader = CsvLoader(Settings())
    table = loader.load(file_path)

    assert table.data["change"].tolist() == [-10, 20, 30]
    assert pd.api.types.is_integer_dtype(table.data["change"])


def test_csv_loader_preserves_signed_integers_with_leading_zeros(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "identifiers.csv"
    file_path.write_text(
        "code\n-0012\n+0034\n",
        encoding="utf-8",
    )

    loader = CsvLoader(Settings())
    table = loader.load(file_path)

    assert table.data["code"].tolist() == ["-0012", "+0034"]


def test_csv_loader_preserves_default_na_literals_as_strings(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "literal_values.csv"
    file_path.write_text(
        "value\nNA\nN/A\nNone\nnull\n",
        encoding="utf-8",
    )

    table = CsvLoader(Settings()).load(file_path)

    assert table.data["value"].tolist() == [
        "NA",
        "N/A",
        "None",
        "null",
    ]
    assert not table.data["value"].isna().any()


def test_csv_loader_treats_only_empty_fields_as_missing(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "notes.csv"
    file_path.write_text(
        "id,note\n1,NA\n2,\n3,None\n4,null\n",
        encoding="utf-8",
    )

    table = CsvLoader(Settings()).load(file_path)

    assert table.data.loc[0, "note"] == "NA"
    assert pd.isna(table.data.loc[1, "note"])
    assert table.data.loc[2, "note"] == "None"
    assert table.data.loc[3, "note"] == "null"
    assert table.data["note"].isna().sum() == 1


@pytest.mark.parametrize(
    "literal",
    [
        "1_000",
        "١٢٣",
    ],
)
def test_csv_loader_preserves_non_ascii_or_decorated_numeric_like_values(
    tmp_path: Path,
    literal: str,
) -> None:
    file_path = tmp_path / "values.csv"
    file_path.write_text(
        f"value\n{literal}\n",
        encoding="utf-8",
    )

    table = CsvLoader(Settings()).load(file_path)

    assert table.data["value"].tolist() == [literal]
    assert pd.api.types.is_object_dtype(table.data["value"])


def test_csv_loader_infers_nullable_integer_columns(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "quantities.csv"
    file_path.write_text(
        "quantity,name\n5,Alice\n,Bob\n7,Charlie\n",
        encoding="utf-8",
    )

    table = CsvLoader(Settings()).load(file_path)

    assert table.data.loc[0, "quantity"] == 5
    assert pd.isna(table.data.loc[1, "quantity"])
    assert table.data.loc[2, "quantity"] == 7
    assert str(table.data["quantity"].dtype) == "Int64"


def test_csv_loader_preserves_mixed_numeric_and_numeric_like_values(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "values.csv"
    file_path.write_text(
        "value\n1000\n1_000\n2000\n",
        encoding="utf-8",
    )

    table = CsvLoader(Settings()).load(file_path)

    assert table.data["value"].tolist() == [
        "1000",
        "1_000",
        "2000",
    ]
    assert pd.api.types.is_object_dtype(table.data["value"])


def test_csv_loader_supports_semicolon_delimiter(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "customers.csv"
    file_path.write_text(
        "customer_id;name\n1;Alice\n2;Bob\n",
        encoding="utf-8",
    )

    table = CsvLoader(Settings()).load(file_path)

    assert table.column_count == 2
    assert table.data.columns.tolist() == [
        "customer_id",
        "name",
    ]
    assert table.data["customer_id"].tolist() == [1, 2]
    assert table.data["name"].tolist() == ["Alice", "Bob"]


def test_csv_loader_supports_cp1252_encoding(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "customers.csv"
    file_path.write_bytes(
        "customer_id,name,city\n1,André,Montréal\n2,José,São Paulo\n".encode("cp1252")
    )

    with pytest.raises(DataLoadError, match="no legacy fallback"):
        CsvLoader(Settings()).load(file_path)
    table = CsvLoader(Settings()).load(
        file_path, options=CsvReadOptions(encoding="cp1252")
    )

    assert table.column_count == 3
    assert table.row_count == 2
    assert table.data["customer_id"].tolist() == [1, 2]
    assert table.data["name"].tolist() == ["André", "José"]
    assert table.data["city"].tolist() == ["Montréal", "São Paulo"]


def test_csv_loader_supports_utf8_bom(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "customers.csv"
    file_path.write_bytes("customer_id,name\n1,Alice\n2,Bob\n".encode("utf-8-sig"))

    table = CsvLoader(Settings()).load(file_path)

    assert table.column_count == 2
    assert table.row_count == 2
    assert table.data.columns.tolist() == ["customer_id", "name"]
    assert table.data["customer_id"].tolist() == [1, 2]
    assert table.data["name"].tolist() == ["Alice", "Bob"]


def test_csv_loader_supports_utf16_little_endian_bom(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "customers.csv"
    file_path.write_bytes("customer_id,name\n1,Alice\n2,Bob\n".encode("utf-16"))

    table = CsvLoader(Settings()).load(file_path)

    assert table.column_count == 2
    assert table.row_count == 2
    assert table.data.columns.tolist() == ["customer_id", "name"]
    assert table.data["customer_id"].tolist() == [1, 2]
    assert table.data["name"].tolist() == ["Alice", "Bob"]


def test_csv_loader_supports_utf16_big_endian_bom(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "customers.csv"

    content = "customer_id,name\n1,Alice\n2,Bob\n"
    file_path.write_bytes(b"\xfe\xff" + content.encode("utf-16-be"))

    table = CsvLoader(Settings()).load(file_path)

    assert table.column_count == 2
    assert table.row_count == 2
    assert table.data.columns.tolist() == ["customer_id", "name"]
    assert table.data["customer_id"].tolist() == [1, 2]
    assert table.data["name"].tolist() == ["Alice", "Bob"]


def test_csv_loader_detects_delimiter_in_utf16_csv(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "customers.csv"
    file_path.write_bytes("customer_id;name\n1;Alice\n2;Bob\n".encode("utf-16"))

    table = CsvLoader(Settings()).load(file_path)

    assert table.column_count == 2
    assert table.row_count == 2
    assert table.data.columns.tolist() == ["customer_id", "name"]
    assert table.data["customer_id"].tolist() == [1, 2]
    assert table.data["name"].tolist() == ["Alice", "Bob"]


def test_csv_loader_rejects_bomless_utf16(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "customers.csv"

    content = "customer_id,name\n1,Alice\n2,Bob\n"
    file_path.write_bytes(content.encode("utf-16-le"))

    with pytest.raises(
        DataLoadError,
        match="CSV file contains NUL bytes",
    ):
        CsvLoader(Settings()).load(file_path)


@pytest.mark.parametrize(
    "encoding",
    [
        "utf-32-le",
        "utf-32-be",
    ],
)
def test_csv_loader_rejects_utf32(
    tmp_path: Path,
    encoding: str,
) -> None:
    file_path = tmp_path / "customers.csv"

    content = "customer_id,name\n1,Alice\n2,Bob\n"

    if encoding == "utf-32-le":
        encoded = codecs.BOM_UTF32_LE + content.encode(encoding)
    else:
        encoded = codecs.BOM_UTF32_BE + content.encode(encoding)

    file_path.write_bytes(encoded)

    with pytest.raises(
        DataLoadError,
        match="CSV file uses UTF-32 encoding, which is not supported.",
    ):
        CsvLoader(Settings()).load(file_path)


def test_csv_loader_supports_explicit_latin1(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "customers.csv"

    file_path.write_bytes(b"customer_id,name\n1,Alice\x81\n2,Bob\n")

    with pytest.raises(DataLoadError, match="no legacy fallback"):
        CsvLoader(Settings()).load(file_path)
    table = CsvLoader(Settings()).load(
        file_path, options=CsvReadOptions(encoding="latin-1")
    )

    assert table.column_count == 2
    assert table.row_count == 2
    assert table.data["customer_id"].tolist() == [1, 2]
    assert table.data["name"].tolist() == [
        "Alice\x81",
        "Bob",
    ]


def test_csv_encoding_detection_handles_split_utf8_sequence(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "split.csv"
    prefix = b"name\n"
    padding = b"a" * (65536 - len(prefix) - 1)

    file_path.write_bytes(prefix + padding + "é".encode() + b"\n")

    assert CsvLoader._detect_encoding(file_path) == "utf-8"


@pytest.mark.parametrize(
    ("encoding", "bom"),
    [
        ("utf-8", b""),
        ("utf-8", codecs.BOM_UTF8),
        ("utf-16-le", codecs.BOM_UTF16_LE),
        ("utf-16-be", codecs.BOM_UTF16_BE),
    ],
    ids=["utf8", "utf8-bom", "utf16-le", "utf16-be"],
)
@pytest.mark.parametrize("late_nul", [False, True], ids=["early", "later-chunk"])
def test_csv_loader_rejects_nul_in_supported_unicode_encodings(
    tmp_path: Path, encoding: str, bom: bytes, late_nul: bool
) -> None:
    file_path = tmp_path / "late_nul.csv"
    padding = "a" * 65536 if late_nul else ""
    file_path.write_bytes(bom + ("name\n" + padding + "ab\x00cd\n").encode(encoding))

    with pytest.raises(
        DataLoadError,
        match="CSV file contains NUL",
    ):
        CsvLoader(Settings()).load(file_path)


def test_csv_encoding_detection_checks_invalid_utf8_after_first_chunk(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "late_invalid.csv"
    file_path.write_bytes(b"name\n" + b"a" * 65536 + b"\xe9\n")

    with pytest.raises(DataLoadError, match="no legacy fallback"):
        CsvLoader._detect_encoding(file_path)


def test_csv_encoding_detection_rejects_legacy_bytes_after_first_chunk(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "late_latin1.csv"
    file_path.write_bytes(b"name\n" + b"a" * 65536 + b"\x81\n")

    with pytest.raises(DataLoadError, match="no legacy fallback"):
        CsvLoader._detect_encoding(file_path)


def test_csv_encoding_detection_handles_incomplete_utf8_at_eof(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "incomplete.csv"
    file_path.write_bytes(b"name\nAlice\xe2\x82")

    with pytest.raises(DataLoadError, match="no legacy fallback"):
        CsvLoader._detect_encoding(file_path)


def test_csv_encoding_detection_continues_after_invalid_utf8(
    tmp_path: Path,
) -> None:
    """Continue scanning after invalid UTF-8 before rejecting the encoding."""

    file_path = tmp_path / "multiple_chunks.csv"

    chunk_size = 64 * 1024

    file_path.write_bytes(b"a" * chunk_size + b"\x81" + b"b" * (chunk_size - 1) + b"c")

    with pytest.raises(DataLoadError, match="no legacy fallback"):
        CsvLoader._detect_encoding(file_path)


def test_csv_type_inference_updates_input_dataframe_in_place() -> None:
    data = pd.DataFrame(
        {
            "quantity": ["1", "2"],
            "code": ["001", "002"],
        }
    )

    converted = CsvLoader._infer_safe_column_types(data)

    assert converted is data
    assert data["quantity"].tolist() == [1, 2]
    assert data["code"].tolist() == ["001", "002"]


@pytest.mark.parametrize(
    "identifier",
    [
        "123456789012345678901234567890",
        "+123456789012345678901234567890",
        "-123456789012345678901234567890",
        "18446744073709551616",
        "-9223372036854775808",
        "9007199254740992",
        "-9007199254740992",
        pytest.param("9" * 5000, id="5000-digit-identifier"),
    ],
)
def test_csv_loader_preserves_oversized_integer_identifiers(
    tmp_path: Path,
    identifier: str,
) -> None:
    path = tmp_path / "identifiers.csv"
    path.write_text(
        f"account_id,name\n{identifier},Alice\n,Bob\n42,Charlie\n",
        encoding="utf-8",
    )

    table = CsvLoader(Settings()).load(path)

    assert table.row_count == 3
    assert table.data.loc[0, "account_id"] == identifier
    assert isinstance(table.data.loc[0, "account_id"], str)
    assert pd.isna(table.data.loc[1, "account_id"])
    assert table.data.loc[2, "account_id"] == "42"


@pytest.mark.parametrize("with_missing", [False, True])
def test_csv_loader_keeps_safe_boundary_integers_exact(
    tmp_path: Path,
    with_missing: bool,
) -> None:
    path = tmp_path / "measurements.csv"
    content = (
        "value,label\n"
        "9007199254740991,maximum\n"
        "-9007199254740991,minimum\n"
        "+9007199254740991,positive\n"
        "99,small\n"
        "0,zero\n"
    )
    if with_missing:
        content += ",missing\n"
    path.write_text(content, encoding="utf-8")

    table = CsvLoader(Settings()).load(path)

    assert table.data["value"].iloc[:5].tolist() == [
        9007199254740991,
        -9007199254740991,
        9007199254740991,
        99,
        0,
    ]
    assert pd.api.types.is_integer_dtype(table.data["value"])
    if with_missing:
        assert str(table.data["value"].dtype) == "Int64"
        assert pd.isna(table.data.loc[5, "value"])


def test_csv_oversized_identifier_survives_sql_execution(tmp_path: Path) -> None:
    path = tmp_path / "accounts.csv"
    identifier = "123456789012345678901234567890"
    path.write_text(
        f"account_id,name\n{identifier},Alice\n,Bob\n",
        encoding="utf-8",
    )
    app = VeriSight(settings=Settings(allow_llm_data_disclosure=False))

    result = app.execute(
        [path],
        "SELECT account_id FROM accounts WHERE account_id IS NOT NULL",
    )

    assert result.rows == ((identifier,),)


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("kind", ["long-value", "long-header", "multiline-value"])
def test_inconclusive_delimiter_requires_explicit_selection(
    tmp_path: Path, kind: str, newline: str
) -> None:
    header = "x" * 9000 if kind == "long-header" else "name"
    value = "x\n" * 5000 if kind == "multiline-value" else "x" * 9000
    path = tmp_path / "sample.csv"
    content = header + ';amount\n"' + value + '";1\n'
    path.write_bytes(content.replace("\n", newline).encode("utf-8"))
    with pytest.raises(DataLoadError, match="delimiter detection was inconclusive"):
        CsvLoader(Settings()).load(path)
    table = CsvLoader(Settings()).load(path, options=CsvReadOptions(delimiter=";"))
    assert table.data.columns.tolist() == [header, "amount"]
    assert table.data[header].tolist() == [value.replace("\n", newline)]
    assert table.data["amount"].tolist() == [1]
    assert table.source.csv_encoding == "utf-8"
    assert table.source.csv_delimiter == ";"


def test_explicit_encoding_preserves_shift_jis_text(tmp_path: Path) -> None:
    path = tmp_path / "names.csv"
    path.write_bytes("name,value\n東京,1\n".encode("shift_jis"))
    with pytest.raises(DataLoadError, match="no legacy fallback"):
        CsvLoader(Settings()).load(path)
    table = CsvLoader(Settings()).load(
        path, options=CsvReadOptions(encoding="shift_jis")
    )
    assert table.data["name"].tolist() == ["東京"]
    assert table.source.csv_encoding == "shift_jis"
    assert table.source.csv_delimiter == ","


@pytest.mark.parametrize("payload", [b"name\nJos\xc3\n", b"name\nAlice\xe2\x82"])
def test_truncated_utf8_is_not_reinterpreted_as_legacy_text(
    tmp_path: Path, payload: bytes
) -> None:
    path = tmp_path / "truncated.csv"
    path.write_bytes(payload)
    with pytest.raises(DataLoadError, match="no legacy fallback"):
        CsvLoader(Settings()).load(path)


@pytest.mark.parametrize(
    "options",
    [
        {"encoding": ""},
        {"encoding": "unknown-csv-codec"},
        {"encoding": 3},
        {"delimiter": ""},
        {"delimiter": ";;"},
        {"delimiter": "\n"},
        {"delimiter": "\r"},
        {"delimiter": "\x00"},
        {"delimiter": '"'},
        {"delimiter": 3},
    ],
)
def test_invalid_csv_choices_are_rejected(options: dict[str, object]) -> None:
    with pytest.raises(DataLoadError):
        CsvReadOptions(**options)  # type: ignore[arg-type]


def test_explicit_decoder_rejects_invalid_bytes_and_nul(tmp_path: Path) -> None:
    path = tmp_path / "invalid.csv"
    path.write_bytes(b"name\n\xff\n")
    with pytest.raises(DataLoadError, match="Could not load CSV"):
        CsvLoader(Settings()).load(path, options=CsvReadOptions(encoding="utf-8"))
    path.write_bytes(b"name\nA\x00B\n")
    with pytest.raises(DataLoadError, match="NUL"):
        CsvLoader(Settings()).load(path, options=CsvReadOptions(encoding="cp1252"))


def test_loader_rejects_invalid_options_object(tmp_path: Path) -> None:
    path = tmp_path / "sample.csv"
    path.write_text("name\nAlice\n", encoding="utf-8")
    with pytest.raises(DataLoadError, match="CsvReadOptions object"):
        CsvLoader(Settings()).load(path, options={})  # type: ignore[arg-type]
