import re
import struct
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import pytest

from verisight import VeriSight
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
    pd.DataFrame({"id": [1]}).to_excel(file_path, index=False)

    def raise_read_error(
        *args: object,
        **kwargs: object,
    ) -> dict[str, pd.DataFrame]:
        raise ValueError("broken workbook")

    monkeypatch.setattr(pd, "ExcelFile", raise_read_error)

    loader = ExcelLoader(Settings())

    with pytest.raises(DataLoadError, match="Could not load Excel file"):
        loader.load(file_path)


def test_excel_loader_wraps_sheet_parse_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "broken.xlsx"
    pd.DataFrame({"id": [1]}).to_excel(file_path, index=False)

    class FailingWorkbook:
        sheet_names = ["Customers"]

        def __enter__(self) -> "FailingWorkbook":
            return self

        def __exit__(
            self,
            exc_type: object,
            exc_value: object,
            traceback: object,
        ) -> None:
            return None

        def parse(self, sheet_name: str, **kwargs: object) -> pd.DataFrame:
            raise ValueError(f"Could not parse {sheet_name}")

    monkeypatch.setattr(
        pd,
        "ExcelFile",
        lambda *args, **kwargs: FailingWorkbook(),
    )

    with pytest.raises(
        DataLoadError,
        match="Could not load Excel file",
    ):
        ExcelLoader(Settings()).load(file_path)


def test_excel_loader_closes_workbook_after_loading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = tmp_path / "workbook.xlsx"
    pd.DataFrame({"id": [1]}).to_excel(file_path, index=False)

    closed = False

    class TrackingWorkbook:
        sheet_names = ["Customers"]

        def __enter__(self) -> "TrackingWorkbook":
            return self

        def __exit__(
            self,
            exc_type: object,
            exc_value: object,
            traceback: object,
        ) -> None:
            nonlocal closed
            closed = True

        def parse(self, sheet_name: str, **kwargs: object) -> pd.DataFrame:
            return pd.DataFrame({"id": [1, 2]})

    monkeypatch.setattr(
        pd,
        "ExcelFile",
        lambda *args, **kwargs: TrackingWorkbook(),
    )

    workbook = ExcelLoader(Settings()).load(file_path)

    assert closed is True
    assert workbook.table_count == 1
    assert workbook.tables[0].name == "Customers"


def test_excel_loader_rejects_non_string_sheet_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject unexpected worksheet names without silently converting them."""

    file_path = tmp_path / "invalid.xlsx"
    pd.DataFrame({"id": [1]}).to_excel(file_path, index=False)

    class InvalidWorkbook:
        sheet_names = [123]

        def __enter__(self) -> "InvalidWorkbook":
            return self

        def __exit__(
            self,
            exc_type: object,
            exc_value: object,
            traceback: object,
        ) -> None:
            return None

        def parse(self, sheet_name: str, **kwargs: object) -> pd.DataFrame:
            pytest.fail("Invalid worksheet name must not be parsed.")

    monkeypatch.setattr(
        pd,
        "ExcelFile",
        lambda *args, **kwargs: InvalidWorkbook(),
    )

    with pytest.raises(
        DataLoadError,
        match="Excel workbook contains a non-string sheet name",
    ):
        ExcelLoader(Settings()).load(file_path)


@pytest.mark.parametrize(
    "values",
    [
        ["00123", "00456"],
        ["NA", "N/A", "NULL", "null", "NaN", "None"],
        ["true", "false", "TRUE", "FALSE"],
        ["1.50", "2.00", "1e3"],
        ["9007199254740993", "123456789012345678901234567890"],
    ],
)
def test_excel_loader_preserves_text_cells(tmp_path: Path, values: list[str]) -> None:
    path = tmp_path / "text.xlsx"
    pd.DataFrame({"value": values}).to_excel(path, index=False)

    data = ExcelLoader(Settings()).load(path).tables[0].data

    assert data["value"].tolist() == values
    assert all(isinstance(value, str) for value in data["value"])
    assert data["value"].isna().sum() == 0


def test_excel_loader_preserves_native_cell_types(tmp_path: Path) -> None:
    path = tmp_path / "typed.xlsx"
    expected = pd.DataFrame(
        {
            "count": [1, 2],
            "amount": [1.5, 2.75],
            "active": [True, False],
            "date": [datetime(2026, 1, 1), datetime(2026, 1, 2)],
        }
    )
    expected.to_excel(path, index=False)

    data = ExcelLoader(Settings()).load(path).tables[0].data

    pd.testing.assert_frame_equal(data, expected)


def test_excel_loader_distinguishes_blank_cells_from_na_text(tmp_path: Path) -> None:
    path = tmp_path / "missing.xlsx"
    pd.DataFrame(
        {
            "row_id": [1, 2, 3],
            "label": ["NA", None, "00123"],
            "amount": [1.5, None, 2.5],
            "date": [datetime(2026, 1, 1), None, datetime(2026, 1, 3)],
        }
    ).to_excel(path, index=False)

    data = ExcelLoader(Settings()).load(path).tables[0].data

    assert data["label"].iloc[0] == "NA"
    assert data["label"].iloc[2] == "00123"
    for column in ("label", "amount", "date"):
        assert data[column].isna().tolist() == [False, True, False]
    assert data["amount"].iloc[0] == 1.5
    assert data["amount"].iloc[2] == 2.5
    assert data["date"].iloc[0] == pd.Timestamp("2026-01-01")
    assert data["date"].iloc[2] == pd.Timestamp("2026-01-03")


def test_excel_loader_preserves_mixed_numeric_and_text_cells(tmp_path: Path) -> None:
    path = tmp_path / "mixed.xlsx"
    pd.DataFrame({"value": [123, "00123", "123"]}).to_excel(path, index=False)

    data = ExcelLoader(Settings()).load(path).tables[0].data

    assert data["value"].tolist() == [123, "00123", "123"]
    assert isinstance(data["value"].iloc[0], int)
    assert isinstance(data["value"].iloc[2], str)


def test_excel_text_values_survive_sql_execution(tmp_path: Path) -> None:
    path = tmp_path / "customers.xlsx"
    pd.DataFrame(
        {"customer_id": ["00123", "00456"], "label": ["NA", "active"]}
    ).to_excel(path, index=False, sheet_name="Customers")
    app = VeriSight(settings=Settings(allow_llm_data_disclosure=False))

    result = app.execute(
        [path],
        "SELECT customer_id, label FROM customers ORDER BY customer_id",
    )

    assert result.rows == (("00123", "NA"), ("00456", "active"))


def _write_exact_numeric_workbook(path: Path, literals: list[str | None]) -> None:
    """Write exact worksheet numbers without Excel-writer float rounding."""
    pd.DataFrame(
        {"value": [1] * len(literals), "row_id": range(len(literals))}
    ).to_excel(path, index=False, sheet_name="Numbers")
    original = path.read_bytes()
    with ZipFile(BytesIO(original)) as source, ZipFile(path, "w") as target:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename == "xl/worksheets/sheet1.xml":
                for row, literal in enumerate(literals, start=2):
                    pattern = rb'<c r="A' + str(row).encode() + rb'"[^>]*>.*?</c>'
                    replacement = (
                        b""
                        if literal is None
                        else f'<c r="A{row}" t="n"><v>{literal}</v></c>'.encode()
                    )
                    content, count = re.subn(pattern, replacement, content)
                    assert count == 1
            target.writestr(entry, content)


@pytest.mark.parametrize(
    ("number", "dtype"),
    [
        (42, "int64"),
        (9007199254740993, "int64"),
        (-9007199254740993, "int64"),
        (-(2**63), "int64"),
        (2**63 - 1, "int64"),
        (2**63, "uint64"),
        (2**64 - 1, "uint64"),
        (-(2**63) - 1, "object"),
        (2**64, "object"),
    ],
)
@pytest.mark.parametrize("with_missing", [False, True])
def test_excel_loader_preserves_exact_numeric_cells(
    tmp_path: Path, number: int, dtype: str, with_missing: bool
) -> None:
    path = tmp_path / "numbers.xlsx"
    literals: list[str | None] = [str(number), "0"]
    if with_missing:
        literals.append(None)
    _write_exact_numeric_workbook(path, literals)

    data = ExcelLoader(Settings()).load(path).tables[0].data

    assert int(data["value"].iloc[0]) == number
    assert data["value"].iloc[1] == 0
    expected_dtype = dtype
    if with_missing and dtype != "object":
        expected_dtype = "UInt64" if dtype == "uint64" else "Int64"
    assert str(data["value"].dtype) == expected_dtype
    if with_missing:
        assert pd.isna(data["value"].iloc[2])


@pytest.mark.parametrize("number", [9007199254740993, -9007199254740993])
def test_excel_loader_preserves_large_integer_beside_fraction(
    tmp_path: Path, number: int
) -> None:
    path = tmp_path / "mixed-numbers.xlsx"
    _write_exact_numeric_workbook(path, [str(number), "1.5", None])

    values = ExcelLoader(Settings()).load(path).tables[0].data["value"]

    assert values.dtype == object
    assert type(values.iloc[0]) is int
    assert values.iloc[0] == number
    assert values.iloc[1] == 1.5
    assert pd.isna(values.iloc[2])


def test_excel_loader_preserves_all_blank_column(tmp_path: Path) -> None:
    path = tmp_path / "blanks.xlsx"
    _write_exact_numeric_workbook(path, [None, None])

    data = ExcelLoader(Settings()).load(path).tables[0].data

    assert data.shape == (2, 2)
    assert data["value"].isna().all()


@pytest.mark.parametrize("number", [9007199254740993, -(2**63), 2**64 - 1])
def test_excel_nullable_integer_survives_sql_execution(
    tmp_path: Path, number: int
) -> None:
    path = tmp_path / "numbers.xlsx"
    _write_exact_numeric_workbook(path, [str(number), None])
    app = VeriSight(settings=Settings(allow_llm_data_disclosure=False))

    result = app.execute([path], "SELECT value FROM numbers ORDER BY row_id")

    assert result.rows == ((number,), (None,))
    assert type(result.rows[0][0]) is int


@pytest.mark.parametrize(
    ("cell", "expected"),
    [
        ('<c r="A2"><f>1+1</f><v>2</v></c>', 2),
        ('<c r="A2"><f>1-1</f><v>0</v></c>', 0),
        ('<c r="A2" t="b"><f>FALSE()</f><v>0</v></c>', False),
        ('<c r="A2" t="str"><f>"NA"</f><v>NA</v></c>', "NA"),
        ('<c r="A2" t="str"><f>""</f><v></v></c>', None),
        ('<c r="A2" t="inlineStr"><is><t>#DIV/0!</t></is></c>', "#DIV/0!"),
    ],
    ids=["number", "zero", "boolean", "text", "empty-text", "literal-error-text"],
)
def test_excel_saved_formula_values_and_literal_text_survive_sql(
    tmp_path: Path, cell: str, expected: object
) -> None:
    path = tmp_path / "numbers.xlsx"
    _write_exact_numeric_workbook(path, ["1"])
    _replace_source_cell(path, cell)
    app = VeriSight(settings=Settings(allow_llm_data_disclosure=False))

    result = app.execute(path, "SELECT value FROM numbers")

    assert result.rows == ((expected,),)
    assert type(result.rows[0][0]) is type(expected)


@pytest.mark.parametrize(
    ("cell", "message"),
    [
        ('<c r="A2"><f>1+1</f></c>', "formula has no saved result"),
        ('<c r="A2"><f>1+1</f><v></v></c>', "formula has no saved result"),
        ('<c r="A2" t="e"><v>#DIV/0!</v></c>', "contains error cells"),
        ('<c r="A2" t="e"><f>1/0</f><v>#DIV/0!</v></c>', "contains error cells"),
    ],
    ids=["missing-cache", "empty-numeric-cache", "error", "formula-error"],
)
def test_excel_rejects_missing_formula_results_and_errors_before_sql(
    tmp_path: Path, cell: str, message: str
) -> None:
    path = tmp_path / "numbers.xlsx"
    _write_exact_numeric_workbook(path, ["1"])
    _replace_source_cell(path, cell)
    app = VeriSight(settings=Settings(allow_llm_data_disclosure=False))

    with pytest.raises(DataLoadError, match=message):
        app.execute(path, "SELECT SUM(value) FROM numbers")


def _replace_source_cell(path: Path, cell: str) -> None:
    """Write formula/cache metadata without depending on Excel recalculation."""
    original = path.read_bytes()
    with ZipFile(BytesIO(original)) as source, ZipFile(path, "w") as target:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename == "xl/worksheets/sheet1.xml":
                content, count = re.subn(
                    rb'<c r="A2"[^>]*>.*?</c>', cell.encode(), content
                )
                assert count == 1
            target.writestr(entry, content)


@pytest.mark.parametrize("with_error", [False, True], ids=["saved-value", "error"])
def test_legacy_excel_uses_saved_formula_values_and_rejects_errors(
    tmp_path: Path, with_error: bool
) -> None:
    """Exercise real xlrd parsing with a minimal synthetic BIFF2 workbook."""
    path = tmp_path / "legacy.xls"

    def record(code: int, payload: bytes) -> bytes:
        return struct.pack("<HH", code, len(payload)) + payload

    end = record(0x000A, b"")
    sheet = record(0x0009, struct.pack("<HH", 7, 0x10))
    sheet += record(0x0042, struct.pack("<H", 1252))
    attributes = b"\x00" * 3
    sheet += record(0x0004, struct.pack("<HH3sB", 0, 0, attributes, 5) + b"value")
    tokens = b"\x1e\x01\x00\x1e\x01\x00\x03"
    sheet += record(
        0x0006,
        struct.pack("<HH3sdBB", 1, 0, attributes, 2.0, 0, len(tokens)) + tokens,
    )
    if with_error:
        sheet += record(0x0005, struct.pack("<HH3sBB", 2, 0, attributes, 7, 1))
    path.write_bytes(sheet + end)
    app = VeriSight(settings=Settings(allow_llm_data_disclosure=False))

    if with_error:
        with pytest.raises(DataLoadError, match="contains error cells"):
            app.execute(path, "SELECT SUM(value) FROM sheet_1")
    else:
        result = app.execute(path, "SELECT value FROM sheet_1")
        assert result.rows == ((2,),)


def test_excel_validation_ignores_binary_package_parts(tmp_path: Path) -> None:
    path = tmp_path / "numbers.xlsx"
    _write_exact_numeric_workbook(path, ["42"])
    with ZipFile(path, "a") as archive:
        archive.writestr("xl/media/synthetic.bin", b"\x89PNG\r\n\x1a\n")

    data = ExcelLoader(Settings()).load(path).tables[0].data

    assert data["value"].tolist() == [42]


def test_excel_formula_validation_does_not_depend_on_part_suffix(
    tmp_path: Path,
) -> None:
    path = tmp_path / "numbers.xlsx"
    _write_exact_numeric_workbook(path, ["1"])
    _replace_source_cell(path, '<c r="A2"><f>1+1</f></c>')
    original = path.read_bytes()
    old_name = "xl/worksheets/sheet1.xml"
    new_name = "xl/worksheets/sheet1.data"
    with ZipFile(BytesIO(original)) as source, ZipFile(path, "w") as target:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename in ("[Content_Types].xml", "xl/_rels/workbook.xml.rels"):
                content = content.replace(b"sheet1.xml", b"sheet1.data")
            target.writestr(new_name if entry.filename == old_name else entry, content)

    with pytest.raises(DataLoadError, match="formula has no saved result"):
        ExcelLoader(Settings()).load(path)
