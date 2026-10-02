from pathlib import Path

import pandas as pd
import pytest

from verisight.execution.engine import DuckDBExecutor
from verisight.execution.exceptions import QueryExecutionError
from verisight.ingestion.models import (
    LoadedDataset,
    LoadedTable,
    SourceMetadata,
)


def _make_dataset(
    *,
    name: str,
    relation_name: str,
    data: pd.DataFrame,
) -> LoadedDataset:
    source = SourceMetadata(
        path=Path(f"{name}.csv"),
        file_name=f"{name}.csv",
        file_extension=".csv",
        file_size_bytes=1,
    )

    table = LoadedTable(
        name=name,
        data=data,
        source=source,
    )
    table.relation_name = relation_name

    return LoadedDataset(tables=[table])


def test_executes_select_against_registered_relation() -> None:
    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2, 3],
                "amount": [10.0, 20.0, 30.0],
            }
        ),
    )

    result = DuckDBExecutor().execute(
        dataset,
        """
        SELECT order_id, amount
        FROM orders
        ORDER BY order_id
        """,
    )

    assert result.columns == (
        "order_id",
        "amount",
    )
    assert result.rows == (
        (1, 10.0),
        (2, 20.0),
        (3, 30.0),
    )
    assert result.row_count == 3


def test_executes_aggregation() -> None:
    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame(
            {
                "amount": [10.0, 20.0, 30.0],
            }
        ),
    )

    result = DuckDBExecutor().execute(
        dataset,
        """
        SELECT
            COUNT(*) AS order_count,
            SUM(amount) AS total_amount
        FROM orders
        """,
    )

    assert result.columns == (
        "order_count",
        "total_amount",
    )
    assert result.rows == ((3, 60.0),)


def test_executes_filter() -> None:
    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2, 3],
                "amount": [10.0, 20.0, 30.0],
            }
        ),
    )

    result = DuckDBExecutor().execute(
        dataset,
        """
        SELECT order_id
        FROM orders
        WHERE amount >= 20
        ORDER BY order_id
        """,
    )

    assert result.columns == ("order_id",)
    assert result.rows == (
        (2,),
        (3,),
    )


def test_uses_relation_name_instead_of_display_name() -> None:
    dataset = _make_dataset(
        name="Order History",
        relation_name="order_history",
        data=pd.DataFrame(
            {
                "order_id": [1, 2],
            }
        ),
    )

    result = DuckDBExecutor().execute(
        dataset,
        """
        SELECT order_id
        FROM order_history
        ORDER BY order_id
        """,
    )

    assert result.rows == (
        (1,),
        (2,),
    )


def test_executes_query_against_multiple_relations() -> None:
    source = SourceMetadata(
        path=Path("dataset.csv"),
        file_name="dataset.csv",
        file_extension=".csv",
        file_size_bytes=1,
    )

    customers = LoadedTable(
        name="Customers",
        data=pd.DataFrame(
            {
                "customer_id": [1, 2],
                "name": ["Alice", "Bob"],
            }
        ),
        source=source,
    )
    customers.relation_name = "customers"

    orders = LoadedTable(
        name="Orders",
        data=pd.DataFrame(
            {
                "order_id": [100, 200, 300],
                "customer_id": [1, 1, 2],
                "amount": [10.0, 20.0, 50.0],
            }
        ),
        source=source,
    )
    orders.relation_name = "orders"

    dataset = LoadedDataset(
        tables=[
            customers,
            orders,
        ]
    )

    result = DuckDBExecutor().execute(
        dataset,
        """
        SELECT
            customers.name,
            SUM(orders.amount) AS total_amount
        FROM customers
        JOIN orders
            ON customers.customer_id = orders.customer_id
        GROUP BY customers.name
        ORDER BY customers.name
        """,
    )

    assert result.columns == (
        "name",
        "total_amount",
    )
    assert result.rows == (
        ("Alice", 30.0),
        ("Bob", 50.0),
    )


def test_query_can_return_no_rows() -> None:
    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2],
            }
        ),
    )

    result = DuckDBExecutor().execute(
        dataset,
        """
        SELECT order_id
        FROM orders
        WHERE order_id > 100
        """,
    )

    assert result.columns == ("order_id",)
    assert result.rows == ()
    assert result.is_empty is True


def test_invalid_sql_raises_query_execution_error() -> None:
    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2],
            }
        ),
    )

    with pytest.raises(
        QueryExecutionError,
        match="Analytical query validation failed:",
    ):
        DuckDBExecutor().execute(
            dataset,
            "SELECT FROM",
        )


def test_unknown_relation_raises_query_execution_error() -> None:
    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2],
            }
        ),
    )

    with pytest.raises(
        QueryExecutionError,
        match="Analytical query execution failed:",
    ):
        DuckDBExecutor().execute(
            dataset,
            "SELECT * FROM missing_relation",
        )


def test_executor_remains_usable_after_failed_query() -> None:
    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2],
            }
        ),
    )

    executor = DuckDBExecutor()

    with pytest.raises(QueryExecutionError):
        executor.execute(
            dataset,
            "SELECT * FROM missing_relation",
        )

    result = executor.execute(
        dataset,
        """
        SELECT order_id
        FROM orders
        ORDER BY order_id
        """,
    )

    assert result.rows == (
        (1,),
        (2,),
    )
