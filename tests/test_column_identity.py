"""Reject source columns that cannot be addressed unambiguously in SQL."""

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
