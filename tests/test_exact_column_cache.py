"""Exact-decimal columns are converted once per executor, never served stale."""

from decimal import Decimal
from pathlib import Path
from typing import Any, cast

import pandas as pd

from verisight.config import Settings
from verisight.execution import engine
from verisight.execution.engine import DuckDBExecutor
from verisight.ingestion.models import LoadedDataset
from verisight.ingestion.service import DatasetLoader

SQL = "SELECT SUM(amount) AS total FROM amounts"


def _dataset(tmp_path: Path) -> LoadedDataset:
    path = tmp_path / "amounts.csv"
    # More digits than a double holds, so the column loads as exact decimals.
    path.write_text("amount\n12345678901234.123456\n1.5\n\n", encoding="utf-8")
    dataset = DatasetLoader(Settings(_env_file=None)).load((path,))  # type: ignore[call-arg]
    assert dataset.tables[0].data["amount"].dtype == object
    return dataset


def test_a_column_is_converted_once_and_its_source_is_untouched(tmp_path: Path) -> None:
    dataset = _dataset(tmp_path)
    before = dataset.tables[0].data.copy(deep=True)
    executor = DuckDBExecutor()

    first = executor.execute(dataset, SQL)
    cached = dict(executor._exact_columns)
    second = executor.execute(dataset, SQL)

    assert first == second
    assert first.rows == ((Decimal("12345678901235.623456"),),)
    assert executor._exact_columns == cached
    assert next(iter(cached.values())) is next(iter(executor._exact_columns.values()))
    pd.testing.assert_frame_equal(dataset.tables[0].data, before)


def test_editing_a_cell_in_place_is_never_answered_from_the_cache(
    tmp_path: Path,
) -> None:
    dataset = _dataset(tmp_path)
    executor = DuckDBExecutor()
    executor.execute(dataset, SQL)

    # The stubs do not list Decimal as a cell value, though pandas stores it.
    cast(Any, dataset.tables[0].data).at[1, "amount"] = Decimal("2.5")

    assert executor.execute(dataset, SQL).rows == ((Decimal("12345678901236.623456"),),)


def test_the_cache_keeps_a_bounded_number_of_columns(monkeypatch: object) -> None:
    executor = DuckDBExecutor()
    original = engine._MAX_EXACT_COLUMNS
    engine._MAX_EXACT_COLUMNS = 2
    try:
        for name in ("a", "b", "c"):
            series = pd.Series([Decimal("1.25"), None], name=name, dtype=object)
            assert executor._exact_column(series) is not None
    finally:
        engine._MAX_EXACT_COLUMNS = original

    assert [key[0] for key in executor._exact_columns] == ["b", "c"]
