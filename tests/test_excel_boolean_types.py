"""Preserve native Excel booleans without conflating them with numbers or text."""

from pathlib import Path

import pandas as pd
import pytest

from verisight import VeriSight
from verisight.config import Settings
from verisight.ingestion.loaders.excel import ExcelLoader
from verisight.ingestion.schema import LogicalType, SchemaInferer

Scalar = bool | int | float | str | None


def _write_workbook(path: Path, values: list[Scalar]) -> None:
    pd.DataFrame(
        {"row_id": range(len(values)), "flag": pd.Series(values, dtype=object)}
    ).to_excel(path, index=False, sheet_name="Flags")


@pytest.mark.parametrize(
    "values",
    [
        pytest.param([True, False], id="native-pair"),
        pytest.param([False, True], id="reversed-pair"),
        pytest.param([True, None, False], id="nullable-pair"),
        pytest.param([False, None, False], id="false-only"),
        pytest.param([True, None, True], id="true-only"),
        pytest.param([None, False], id="leading-blank-false"),
        pytest.param([None, True], id="leading-blank-true"),
    ],
)
def test_native_excel_booleans_have_boolean_schema(
    tmp_path: Path, values: list[Scalar]
) -> None:
    path = tmp_path / "flags.xlsx"
    _write_workbook(path, values)
    table = ExcelLoader(Settings()).load(path).tables[0]
    column = SchemaInferer().infer_table(table).columns[1]
    flags = table.data["flag"]
    missing_count = values.count(None)
    assert str(flags.dtype) == ("boolean" if missing_count else "bool")
    assert column.logical_type is LogicalType.BOOLEAN
    assert column.nullable is (missing_count > 0)
    assert column.missing_count == missing_count
    for actual, expected in zip(flags.tolist(), values, strict=True):
        if expected is None:
            assert pd.isna(actual)
        else:
            assert type(actual) is bool
            assert actual is expected


@pytest.mark.parametrize(
    "values",
    [
        pytest.param([True, 1, None], id="true-before-one"),
        pytest.param([1, True, None], id="one-before-true"),
        pytest.param([False, 0, None], id="false-before-zero"),
        pytest.param([0, False, None], id="zero-before-false"),
        pytest.param([True, 2, None], id="true-and-integer"),
        pytest.param([False, -1, None], id="false-and-negative-integer"),
        pytest.param([True, 1.5, None], id="true-and-fraction"),
        pytest.param([-0.5, False, None], id="fraction-and-false"),
        pytest.param([True, "TRUE", None], id="true-and-text"),
        pytest.param(["false", False, None], id="text-and-false"),
        pytest.param([True, "1", None], id="true-and-numeric-text"),
        pytest.param([False, "NA", None], id="false-and-na-text"),
        pytest.param([True, 1, False, 0], id="both-pairs-without-blanks"),
    ],
)
def test_mixed_boolean_columns_preserve_native_scalar_types(
    tmp_path: Path, values: list[Scalar]
) -> None:
    path = tmp_path / "mixed.xlsx"
    _write_workbook(path, values)
    table = ExcelLoader(Settings()).load(path).tables[0]
    column = SchemaInferer().infer_table(table).columns[1]
    assert table.data["flag"].dtype == object
    assert column.logical_type is LogicalType.UNKNOWN
    assert column.missing_count == values.count(None)
    for actual, expected in zip(table.data["flag"].tolist(), values, strict=True):
        if expected is None:
            assert pd.isna(actual)
        else:
            assert type(actual) is type(expected)
            assert actual == expected


@pytest.mark.parametrize("with_missing", [False, True])
def test_zero_and_one_remain_integers(tmp_path: Path, with_missing: bool) -> None:
    values: list[Scalar] = [0, 1]
    if with_missing:
        values.append(None)
    path = tmp_path / "numbers.xlsx"
    _write_workbook(path, values)
    table = ExcelLoader(Settings()).load(path).tables[0]
    column = SchemaInferer().infer_table(table).columns[1]
    assert column.logical_type is LogicalType.INTEGER
    assert str(table.data["flag"].dtype) == ("Int64" if with_missing else "int64")
    assert table.data["flag"].iloc[0] == 0
    assert table.data["flag"].iloc[1] == 1


def test_boolean_looking_text_is_not_converted(tmp_path: Path) -> None:
    path = tmp_path / "text.xlsx"
    _write_workbook(path, ["TRUE", "FALSE", None, "true", "false"])
    table = ExcelLoader(Settings()).load(path).tables[0]
    column = SchemaInferer().infer_table(table).columns[1]
    assert column.logical_type is LogicalType.STRING
    assert column.missing_count == 1
    assert table.data["flag"].dropna().tolist() == ["TRUE", "FALSE", "true", "false"]


def test_all_blank_column_does_not_infer_boolean(tmp_path: Path) -> None:
    path = tmp_path / "blank.xlsx"
    _write_workbook(path, [None, None])
    table = ExcelLoader(Settings()).load(path).tables[0]
    assert table.data.shape == (2, 2)
    assert table.data["flag"].isna().all()
    assert (
        SchemaInferer().infer_table(table).columns[1].logical_type
        is LogicalType.UNKNOWN
    )


def test_nullable_excel_booleans_survive_facade_analysis_and_sql(
    tmp_path: Path,
) -> None:
    path = tmp_path / "flags.xlsx"
    _write_workbook(path, [True, None, False])
    app = VeriSight(settings=Settings(allow_llm_data_disclosure=False))
    analysis = app.analyze(path)
    column = analysis.analysis.schema.tables[0].columns[1]
    assert column.logical_type is LogicalType.BOOLEAN
    assert column.nullable is True
    assert column.missing_count == 1
    result = app.execute(
        path, "SELECT row_id, flag, TYPEOF(flag) AS kind FROM flags ORDER BY row_id"
    )
    assert result.rows == (
        (0, True, "BOOLEAN"),
        (1, None, "BOOLEAN"),
        (2, False, "BOOLEAN"),
    )
    assert type(result.rows[0][1]) is bool
    assert type(result.rows[2][1]) is bool
