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


def test_service_exposes_query_context() -> None:
    service = AnalyticalExecutionService(_make_dataset())

    context = service.context

    assert context.relation_count == 1

    relation = context.relations[0]

    assert relation.name == "Orders"
    assert relation.relation_name == "orders"
    assert relation.row_count == 3

    assert tuple(column.name for column in relation.columns) == (
        "order_id",
        "amount",
    )


def test_service_context_describes_column_types() -> None:
    service = AnalyticalExecutionService(_make_dataset())

    relation = service.context.relations[0]

    order_id = relation.columns[0]
    amount = relation.columns[1]

    assert order_id.physical_dtype == "int64"
    assert order_id.logical_type.value == "integer"
    assert order_id.nullable is False

    assert amount.physical_dtype == "float64"
    assert amount.logical_type.value == "float"
    assert amount.nullable is False


def test_service_reuses_query_context() -> None:
    service = AnalyticalExecutionService(_make_dataset())

    first_context = service.context
    second_context = service.context

    assert first_context is second_context


def test_service_exposes_formatted_query_context() -> None:
    service = AnalyticalExecutionService(_make_dataset())

    formatted_context = service.formatted_context

    assert "Orders" in formatted_context
    assert "orders" in formatted_context
    assert "order_id" in formatted_context
    assert "amount" in formatted_context
    assert "integer" in formatted_context
    assert "float" in formatted_context


def test_service_reuses_formatted_query_context() -> None:
    service = AnalyticalExecutionService(_make_dataset())

    first_context = service.formatted_context
    second_context = service.formatted_context

    assert first_context is second_context
