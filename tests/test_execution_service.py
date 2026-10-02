from pathlib import Path

import pandas as pd
import pytest

from verisight.execution.exceptions import QueryExecutionError
from verisight.execution.service import AnalyticalExecutionService
from verisight.ingestion.models import (
    LoadedDataset,
    LoadedTable,
    SourceMetadata,
)


def _make_dataset() -> LoadedDataset:
    source = SourceMetadata(
        path=Path("orders.csv"),
        file_name="orders.csv",
        file_extension=".csv",
        file_size_bytes=1,
    )

    table = LoadedTable(
        name="Orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2, 3],
                "amount": [10.0, 20.0, 30.0],
            }
        ),
        source=source,
    )
    table.relation_name = "orders"

    return LoadedDataset(tables=[table])


def test_executes_query_against_service_dataset() -> None:
    service = AnalyticalExecutionService(_make_dataset())

    result = service.execute(
        """
        SELECT
            COUNT(*) AS order_count,
            SUM(amount) AS total_amount
        FROM orders
        """
    )

    assert result.columns == (
        "order_count",
        "total_amount",
    )
    assert result.rows == ((3, 60.0),)


def test_service_reuses_loaded_dataset_across_queries() -> None:
    service = AnalyticalExecutionService(_make_dataset())

    count_result = service.execute(
        """
        SELECT COUNT(*) AS order_count
        FROM orders
        """
    )

    total_result = service.execute(
        """
        SELECT SUM(amount) AS total_amount
        FROM orders
        """
    )

    assert count_result.rows == ((3,),)
    assert total_result.rows == ((60.0,),)


def test_service_preserves_execution_validation() -> None:
    service = AnalyticalExecutionService(_make_dataset())

    with pytest.raises(
        QueryExecutionError,
        match="Only read-only analytical SELECT queries are allowed.",
    ):
        service.execute("DROP TABLE orders")
