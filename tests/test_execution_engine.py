from pathlib import Path

import duckdb
import pandas as pd
import pytest

from verisight.execution.engine import DuckDBExecutor
from verisight.execution.exceptions import (
    QueryExecutionError,
    QueryResultLimitError,
    QueryRuntimeError,
    QueryTimeoutError,
    QueryValidationError,
)
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


def test_invalid_sql_raises_query_validation_error() -> None:
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
        QueryValidationError,
        match="Analytical query validation failed:",
    ):
        DuckDBExecutor().execute(
            dataset,
            "SELECT FROM",
        )


def test_unknown_relation_raises_query_runtime_error() -> None:
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
        QueryRuntimeError,
        match="Analytical query execution failed:",
    ):
        DuckDBExecutor().execute(
            dataset,
            "SELECT * FROM missing_relation",
        )


def test_validation_error_is_query_execution_error() -> None:
    error = QueryValidationError("Invalid query")

    assert isinstance(error, QueryExecutionError)


def test_runtime_error_is_query_execution_error() -> None:
    error = QueryRuntimeError("Execution failed")

    assert isinstance(error, QueryExecutionError)


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

    with pytest.raises(QueryRuntimeError):
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


def test_executor_cannot_read_external_text_file(
    tmp_path: Path,
) -> None:
    secret_path = tmp_path / "secret.txt"
    secret_path.write_text(
        "verisight-secret-value",
        encoding="utf-8",
    )

    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2],
            }
        ),
    )

    escaped_path = secret_path.as_posix().replace("'", "''")

    query = f"SELECT content FROM read_text('{escaped_path}')"

    with pytest.raises(
        (
            QueryValidationError,
            QueryRuntimeError,
        )
    ):
        DuckDBExecutor().execute(
            dataset,
            query,
        )


def test_executor_connection_disables_external_access(
    tmp_path: Path,
) -> None:
    secret_path = tmp_path / "secret.txt"
    secret_path.write_text(
        "verisight-secret-value",
        encoding="utf-8",
    )

    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2],
            }
        ),
    )

    escaped_path = secret_path.as_posix().replace("'", "''")

    executor = DuckDBExecutor()

    with executor._connection(dataset) as connection:
        result = connection.execute(
            """
            SELECT order_id
            FROM orders
            ORDER BY order_id
            """
        ).fetchall()

        assert result == [
            (1,),
            (2,),
        ]

        with pytest.raises(
            duckdb.PermissionException,
            match="file system operations are disabled by configuration",
        ):
            connection.execute(
                f"SELECT content FROM read_text('{escaped_path}')"
            ).fetchall()


def test_executor_rejects_non_positive_result_limit() -> None:
    with pytest.raises(
        ValueError,
        match="Maximum query result rows must be positive.",
    ):
        DuckDBExecutor(max_result_rows=0)


def test_executor_allows_result_exactly_at_row_limit() -> None:
    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2, 3],
            }
        ),
    )

    result = DuckDBExecutor(
        max_result_rows=3,
    ).execute(
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
        (3,),
    )


def test_executor_rejects_result_exceeding_row_limit() -> None:
    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2, 3],
            }
        ),
    )

    with pytest.raises(
        QueryResultLimitError,
        match="Analytical query result exceeded the maximum of 2 rows.",
    ):
        DuckDBExecutor(
            max_result_rows=2,
        ).execute(
            dataset,
            """
            SELECT order_id
            FROM orders
            ORDER BY order_id
            """,
        )


def test_result_limit_error_is_query_execution_error() -> None:
    error = QueryResultLimitError("Result exceeded configured limit.")

    assert isinstance(error, QueryExecutionError)


def test_result_limit_error_is_not_query_runtime_error() -> None:
    error = QueryResultLimitError("Result exceeded configured limit.")

    assert not isinstance(error, QueryRuntimeError)


def test_executor_rejects_non_positive_memory_limit() -> None:
    with pytest.raises(
        ValueError,
        match="Query memory limit must be positive.",
    ):
        DuckDBExecutor(memory_limit_mb=0)


def test_executor_connection_applies_memory_limit() -> None:
    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2],
            }
        ),
    )

    executor = DuckDBExecutor(
        memory_limit_mb=64,
    )

    with executor._connection(dataset) as connection:
        result = connection.execute(
            """
            SELECT value
            FROM duckdb_settings()
            WHERE name = 'memory_limit'
            """
        ).fetchone()

    assert result is not None

    memory_limit = str(result[0])

    assert memory_limit
    assert memory_limit != "unlimited"


def test_executor_rejects_non_positive_execution_timeout() -> None:
    with pytest.raises(
        ValueError,
        match="Query execution timeout must be positive.",
    ):
        DuckDBExecutor(
            execution_timeout_seconds=0,
        )


def test_timeout_error_is_query_execution_error() -> None:
    error = QueryTimeoutError("Query exceeded configured timeout.")

    assert isinstance(error, QueryExecutionError)


def test_timeout_error_is_not_query_runtime_error() -> None:
    error = QueryTimeoutError("Query exceeded configured timeout.")

    assert not isinstance(error, QueryRuntimeError)


def test_executor_interrupts_query_after_execution_timeout() -> None:
    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2],
            }
        ),
    )

    executor = DuckDBExecutor(
        execution_timeout_seconds=0.05,
    )

    with pytest.raises(
        QueryTimeoutError,
        match="Analytical query exceeded the execution timeout",
    ):
        executor.execute(
            dataset,
            """
            SELECT SUM(a.range * b.range)
            FROM range(1000000000) AS a
            CROSS JOIN range(1000000000) AS b
            """,
        )


def test_executor_allows_query_within_execution_timeout() -> None:
    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2, 3],
            }
        ),
    )

    result = DuckDBExecutor(
        execution_timeout_seconds=1.0,
    ).execute(
        dataset,
        """
        SELECT SUM(order_id) AS total
        FROM orders
        """,
    )

    assert result.columns == ("total",)
    assert result.rows == ((6,),)


@pytest.mark.parametrize("limit", [0, -1])
def test_executor_rejects_non_positive_temp_storage_limit(limit: int) -> None:
    with pytest.raises(
        ValueError,
        match="Query temporary storage limit must be positive.",
    ):
        DuckDBExecutor(temp_storage_limit_mb=limit)


def test_executor_connection_applies_temp_storage_limit() -> None:
    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame({"order_id": [1, 2]}),
    )
    executor = DuckDBExecutor(temp_storage_limit_mb=128)

    with executor._connection(dataset) as connection:
        result = connection.execute(
            """
            SELECT value
            FROM duckdb_settings()
            WHERE name = 'max_temp_directory_size'
            """
        ).fetchone()

    assert result is not None
    assert str(result[0]) == "122.0 MiB"


def test_executor_closes_connection_after_query_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame({"order_id": [1, 2]}),
    )

    executor = DuckDBExecutor(
        execution_timeout_seconds=0.05,
        memory_limit_mb=64,
        temp_storage_limit_mb=32,
    )

    original_connection = executor._connection
    captured_connections: list[duckdb.DuckDBPyConnection] = []

    from collections.abc import Iterator
    from contextlib import contextmanager

    @contextmanager
    def tracked_connection() -> Iterator[duckdb.DuckDBPyConnection]:
        with original_connection(dataset) as connection:
            captured_connections.append(connection)
            yield connection

    # Track the connection created during execution.
    # The wrapper uses the same dataset as the original call.
    monkeypatch.setattr(
        executor,
        "_connection",
        lambda _dataset: tracked_connection(),
    )

    with pytest.raises(QueryTimeoutError):
        executor.execute(
            dataset,
            """
            SELECT SUM(a.range * b.range)
            FROM range(1000000000) AS a
            CROSS JOIN range(1000000000) AS b
            """,
        )

    assert len(captured_connections) == 1

    with pytest.raises(duckdb.ConnectionException):
        captured_connections[0].execute("SELECT 1")
