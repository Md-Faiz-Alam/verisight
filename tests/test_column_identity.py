"""Reject source columns that cannot be addressed unambiguously in SQL."""

import csv
import json
from pathlib import Path
from typing import Literal
from unittest.mock import Mock

import pandas as pd
import pytest

from verisight import VeriSight
from verisight.config import Settings
from verisight.error_reporting import ErrorCode
from verisight.ingestion.exceptions import DataLoadError, TableValidationError
from verisight.ingestion.models import LoadedTable, SourceMetadata
from verisight.public_api import run_public_operation


def _settings() -> Settings:
    return Settings(
        gemini_api_key=None,
        allow_llm_data_disclosure=False,
    )


@pytest.mark.parametrize(
    "columns",
    [
        ("Amount", "amount"),
        ("Gross Amount", "GROSS AMOUNT"),
        ('gross"Amount', 'gross"amount'),
        (1, "1"),
    ],
)
def test_loaded_table_rejects_sql_identifier_collisions(
    columns: tuple[object, object],
) -> None:
    data = pd.DataFrame([[10, 900]], columns=list(columns))
    original = data.copy(deep=True)
    source = SourceMetadata(Path("source.csv"), "source.csv", ".csv", 1)

    with pytest.raises(TableValidationError, match="ambiguous SQL column names"):
        LoadedTable(name="source", data=data, source=source)

    pd.testing.assert_frame_equal(data, original)


@pytest.mark.parametrize("extension", ["csv", "json", "xlsx"])
@pytest.mark.parametrize("operation", ["analyze", "execute", "ask", "investigate"])
def test_public_workflows_reject_ambiguous_columns_before_generation(
    tmp_path: Path,
    extension: str,
    operation: Literal["analyze", "execute", "ask", "investigate"],
) -> None:
    path = tmp_path / f"measurements.{extension}"
    if extension == "csv":
        path.write_text("Amount,amount\n10,900\n", encoding="utf-8")
    elif extension == "json":
        path.write_text(json.dumps([{"Amount": 10, "amount": 900}]), encoding="utf-8")
    else:
        pd.DataFrame({"Amount": [10], "amount": [900]}).to_excel(path, index=False)

    planner = Mock()
    investigator = Mock()
    synthesizer = Mock()
    app = VeriSight(
        settings=_settings(),
        planner=planner,
        investigator=investigator,
        synthesizer=synthesizer,
    )
    with pytest.raises((DataLoadError, TableValidationError)) as caught:
        if operation == "analyze":
            app.analyze(path)
        elif operation == "execute":
            app.execute(path, 'SELECT "amount" AS metric FROM measurements')
        elif operation == "ask":
            app.ask(path, "Return the lowercase amount column.")
        else:
            app.investigate(path, "Return the lowercase amount column.", max_steps=1)

    failure = caught.value.__cause__ if extension == "xlsx" else caught.value
    assert isinstance(failure, TableValidationError)
    assert "ambiguous SQL column names" in str(failure)
    assert planner.mock_calls == []
    assert investigator.mock_calls == []
    assert synthesizer.mock_calls == []


@pytest.mark.parametrize("columns", [("Ä", "ä"), ("Straße", "STRASSE")])
def test_distinct_unicode_identifiers_remain_queryable(
    tmp_path: Path, columns: tuple[str, str]
) -> None:
    path = tmp_path / "measurements.json"
    path.write_text(json.dumps([{columns[0]: 10, columns[1]: 900}]), encoding="utf-8")

    result = VeriSight(settings=_settings()).execute(
        path, f'SELECT "{columns[0]}", "{columns[1]}" FROM measurements'
    )

    assert result.columns == columns
    assert result.rows == ((10, 900),)


def test_ambiguous_column_failure_has_a_safe_public_error(tmp_path: Path) -> None:
    path = tmp_path / "private_source.csv"
    path.write_text("PrivateAmount,privateamount\n10,900\n", encoding="utf-8")
    app = VeriSight(settings=_settings())

    outcome = run_public_operation(lambda: app.analyze(path))

    assert not outcome.succeeded
    assert outcome.value is None
    assert outcome.error is not None
    assert outcome.error.code is ErrorCode.TABLE_VALIDATION_ERROR
    assert "PrivateAmount" not in outcome.error.message
    assert "private_source" not in outcome.error.message


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
@pytest.mark.parametrize(
    "headers",
    [
        ("amount", "amount"),
        ("", "amount"),
        ("amount", ""),
        ("amount", "   "),
    ],
    ids=["duplicate", "blank-first", "blank-last", "whitespace"],
)
def test_raw_headers_are_rejected_before_generation(
    tmp_path: Path, extension: str, headers: tuple[str, str]
) -> None:
    path = tmp_path / f"private_measurements.{extension}"
    if extension == "csv":
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(headers)
            writer.writerow([10, 900])
    else:
        pd.DataFrame([[10, 900]], columns=list(headers)).to_excel(path, index=False)
    planner = Mock()
    investigator = Mock()
    synthesizer = Mock()
    app = VeriSight(
        settings=_settings(),
        planner=planner,
        investigator=investigator,
        synthesizer=synthesizer,
    )
    for operation in (
        lambda: app.analyze(path),
        lambda: app.execute(path, "SELECT * FROM private_measurements"),
        lambda: app.ask(path, "Get the amount"),
        lambda: app.investigate(path, "Get the amount", max_steps=1),
    ):
        public = run_public_operation(operation)
        assert not public.succeeded
        assert public.value is None
        assert public.error is not None
        assert public.error.code is ErrorCode.DATA_LOAD_ERROR
        assert "private_measurements" not in public.error.message
    assert planner.mock_calls == []
    assert investigator.mock_calls == []
    assert synthesizer.mock_calls == []


@pytest.mark.parametrize("extension", ["csv", "xlsx"])
@pytest.mark.parametrize(
    "headers",
    [
        ("amount", "amount.1"),
        ("Unnamed: 0", "NA"),
        ("00123", "value"),
        ("Gross, amount", 'note"label'),
        ("Gross\nAmount", "value"),
        ("Ä", "ä"),
    ],
    ids=["suffix", "literal-names", "leading-zero", "quoted", "multiline", "unicode"],
)
def test_valid_source_headers_remain_exact_and_queryable(
    tmp_path: Path, extension: str, headers: tuple[str, str]
) -> None:
    path = tmp_path / f"measurements.{extension}"
    if extension == "csv":
        with path.open("w", encoding="utf-8", newline="") as file:
            writer = csv.writer(file, lineterminator="\n")
            writer.writerow(headers)
            writer.writerow([10, 900])
    else:
        pd.DataFrame([[10, 900]], columns=list(headers)).to_excel(
            path, sheet_name="measurements", index=False
        )
    quoted = ['"' + name.replace('"', '""') + '"' for name in headers]
    result = VeriSight(settings=_settings()).execute(
        path, f"SELECT {', '.join(quoted)} FROM measurements"
    )
    assert result.columns == headers
    assert result.rows == ((10, 900),)


def test_excel_checks_headers_on_every_sheet(tmp_path: Path) -> None:
    path = tmp_path / "measurements.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"value": [10]}).to_excel(writer, sheet_name="valid", index=False)
        pd.DataFrame([[10, 900]], columns=["value", "value"]).to_excel(
            writer, sheet_name="invalid", index=False
        )
    with pytest.raises(DataLoadError, match="duplicate source column headers"):
        VeriSight(settings=_settings()).analyze(path)


def test_excel_empty_sheet_remains_supported(tmp_path: Path) -> None:
    path = tmp_path / "empty.xlsx"
    pd.DataFrame().to_excel(path, index=False)
    result = VeriSight(settings=_settings()).analyze(path)
    table = result.analysis.schema.tables[0]
    assert table.row_count == 0
    assert table.column_count == 0


def test_excel_rejects_later_values_without_source_headers(tmp_path: Path) -> None:
    path = tmp_path / "measurements.xlsx"
    pd.DataFrame([["value", None], [10, None], [20, 900]], dtype=object).to_excel(
        path, index=False, header=False
    )
    with pytest.raises(DataLoadError, match="fields without source headers"):
        VeriSight(settings=_settings()).analyze(path)
