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
from verisight.execution.models import QueryScalar
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


@pytest.mark.parametrize(
    "query",
    [
        "SELECT name, value FROM duckdb_settings() LIMIT 3",
        "SELECT table_name FROM duckdb_tables() LIMIT 3",
        "SELECT * FROM information_schema.tables LIMIT 3",
    ],
)
def test_rejects_internal_metadata_access(query: str) -> None:
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
        match="Dataset access is not allowed",
    ):
        DuckDBExecutor().execute(dataset, query)


@pytest.mark.parametrize(
    "query",
    [
        """
        WITH hidden AS (
            SELECT * FROM duckdb_settings()
        )
        SELECT * FROM hidden
        """,
        """
        SELECT *
        FROM orders
        WHERE EXISTS (
            SELECT 1
            FROM information_schema.tables
        )
        """,
        """
        SELECT *
        FROM orders
        JOIN (
            SELECT * FROM duckdb_tables()
        ) AS hidden
        ON TRUE
        """,
        """
        SELECT *
        FROM (
            SELECT * FROM information_schema.tables
        ) AS hidden
        """,
    ],
)
def test_rejects_nested_internal_metadata_access(query: str) -> None:
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
        match="Dataset access is not allowed",
    ):
        DuckDBExecutor().execute(dataset, query)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT current_setting('enable_external_access')",
        "SELECT current_database()",
        "SELECT version()",
        "SELECT current_schema()",
        """
        SELECT order_id,
               current_setting('memory_limit') AS internal_setting
        FROM orders
        """,
    ],
)
def test_rejects_scalar_metadata_functions(query: str) -> None:
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
        match="Dataset access is not allowed",
    ):
        DuckDBExecutor().execute(dataset, query)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT current_catalog()",
        "SELECT current_user",
        "SELECT session_user",
        "SELECT current_catalog() FROM orders",
        "SELECT current_user FROM orders",
    ],
)
def test_rejects_additional_metadata_expressions(query: str) -> None:
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
        match="Dataset access is not allowed",
    ):
        DuckDBExecutor().execute(dataset, query)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM UNNEST([1, 2, 3]) AS t(value)",
        "SELECT * FROM (VALUES (1), (2)) AS t(value)",
    ],
)
def test_allows_safe_inline_table_expressions(query: str) -> None:
    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame({"order_id": [1, 2]}),
    )

    result = DuckDBExecutor().execute(dataset, query)

    assert result.rows


@pytest.mark.parametrize(
    "query",
    [
        """
        SELECT *
        FROM UNNEST(
            [current_setting('memory_limit')]
        ) AS t(value)
        """,
        """
        SELECT *
        FROM (
            VALUES (current_setting('memory_limit'))
        ) AS t(value)
        """,
        """
        SELECT *
        FROM UNNEST(
            (SELECT [name] FROM duckdb_settings() LIMIT 1)
        ) AS t(value)
        """,
    ],
)
def test_rejects_metadata_access_inside_inline_tables(
    query: str,
) -> None:
    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame({"order_id": [1, 2]}),
    )

    with pytest.raises(
        QueryValidationError,
        match="Dataset access is not allowed",
    ):
        DuckDBExecutor().execute(dataset, query)


def test_rejects_unsupported_inline_table_expression() -> None:
    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame({"order_id": [1, 2]}),
    )

    query = """
        SELECT *
        FROM LATERAL (
            SELECT 1 AS value
        ) AS t
    """

    with pytest.raises(
        QueryValidationError,
        match="Dataset access is not allowed: unsupported inline table",
    ):
        DuckDBExecutor().execute(dataset, query)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM main.generate_series(1, 3)",
        "SELECT * FROM memory.main.generate_series(1, 3)",
    ],
)
def test_rejects_schema_qualified_generate_series(
    query: str,
) -> None:
    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame({"order_id": [1, 2]}),
    )

    with pytest.raises(
        QueryValidationError,
        match="Dataset access is not allowed: schema-qualified table function",
    ):
        DuckDBExecutor().execute(dataset, query)


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


def test_executor_rejects_implicit_external_file_scan(
    tmp_path: Path,
) -> None:
    secret_path = tmp_path / "secret.csv"
    secret_path.write_text(
        "secret\nverisight-secret-value\n",
        encoding="utf-8",
    )

    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame({"order_id": [1, 2]}),
    )

    escaped_path = secret_path.as_posix().replace("'", "''")

    query = f"SELECT * FROM '{escaped_path}'"

    with pytest.raises(
        (QueryValidationError, QueryRuntimeError),
    ):
        DuckDBExecutor().execute(dataset, query)


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


def test_executor_connection_disables_automatic_extensions() -> None:
    dataset = _make_dataset(
        name="Orders",
        relation_name="orders",
        data=pd.DataFrame({"order_id": [1, 2]}),
    )

    executor = DuckDBExecutor()

    with executor._connection(dataset) as connection:
        settings = dict(
            connection.execute(
                """
                SELECT name, value
                FROM duckdb_settings()
                WHERE name IN (
                    'autoload_known_extensions',
                    'autoinstall_known_extensions'
                )
                """
            ).fetchall()
        )

    assert settings == {
        "autoload_known_extensions": "false",
        "autoinstall_known_extensions": "false",
    }


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


@pytest.mark.parametrize("limit", [0, -1, True])
def test_executor_rejects_invalid_result_byte_limit(limit: int) -> None:
    with pytest.raises(ValueError, match="result bytes must be a positive integer"):
        DuckDBExecutor(max_result_bytes=limit)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT value FROM synthetic ORDER BY value",
        "SELECT 'é😀' AS \"列\", chr(10) || chr(34) || chr(92) AS escaped",
        "SELECT CAST(1.20 AS DECIMAL(4,2)) AS d, DATE '2026-01-01' AS day, NULL AS n",
        "SELECT TRUE AS b, CAST('NaN' AS DOUBLE) AS n",
        'SELECT value AS "列" FROM synthetic WHERE FALSE',
    ],
)
def test_result_byte_limit_matches_exact_compact_public_json(query: str) -> None:
    import json

    from verisight.serialization import to_jsonable

    dataset = _make_dataset(
        name="synthetic",
        relation_name="synthetic",
        data=pd.DataFrame({"value": ["é", 'quote"\n', "😀"]}),
    )
    result = DuckDBExecutor().execute(dataset, query)
    expected_bytes = len(
        json.dumps(
            to_jsonable(result),
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    )

    assert to_jsonable(
        DuckDBExecutor(max_result_bytes=expected_bytes).execute(dataset, query)
    ) == to_jsonable(result)
    with pytest.raises(QueryResultLimitError, match="bytes of compact UTF-8 JSON"):
        DuckDBExecutor(max_result_bytes=expected_bytes - 1).execute(dataset, query)


def test_default_byte_budget_rejects_one_large_cell_and_executor_recovers() -> None:
    dataset = _make_dataset(
        name="synthetic",
        relation_name="synthetic",
        data=pd.DataFrame({"value": [1]}),
    )
    executor = DuckDBExecutor(max_result_rows=1, memory_limit_mb=16)
    with pytest.raises(QueryResultLimitError, match="1048576 bytes") as caught:
        executor.execute(dataset, "SELECT repeat('private-marker', 100000) AS value")
    assert "private-marker" not in str(caught.value)
    assert executor.execute(dataset, "SELECT value FROM synthetic").rows == ((1,),)


def test_result_bytes_stop_fetching_and_close_resources() -> None:
    from unittest.mock import MagicMock, patch

    dataset = _make_dataset(
        name="synthetic",
        relation_name="synthetic",
        data=pd.DataFrame({"value": [1]}),
    )
    connection = MagicMock()
    cursor = connection.execute.return_value
    cursor.description = [("v",)]
    cursor.fetchone.side_effect = [("abcdefghij",)] * 100 + [None]
    executor = DuckDBExecutor(max_result_bytes=70)
    with (
        patch.object(executor, "_connection") as connection_context,
        patch("verisight.execution.engine.Timer") as timer,
    ):
        connection_context.return_value.__enter__.return_value = connection
        with pytest.raises(QueryResultLimitError, match="70 bytes"):
            executor.execute(dataset, "SELECT value FROM synthetic")
        assert cursor.fetchone.call_count == 3
        connection_context.return_value.__exit__.assert_called_once()
        timer.return_value.cancel.assert_called_once()
        timer.return_value.join.assert_called_once()


@pytest.mark.parametrize("limit,column", [(1, "value"), (32, "x" * 1000)])
def test_result_byte_budget_checks_structure_and_headers_before_fetching(
    limit: int,
    column: str,
) -> None:
    from unittest.mock import MagicMock, patch

    dataset = _make_dataset(
        name="synthetic",
        relation_name="synthetic",
        data=pd.DataFrame({"value": [1]}),
    )
    connection = MagicMock()
    cursor = connection.execute.return_value
    cursor.description = [(column,)]
    executor = DuckDBExecutor(max_result_bytes=limit)
    with patch.object(executor, "_connection") as connection_context:
        connection_context.return_value.__enter__.return_value = connection
        with pytest.raises(QueryResultLimitError, match="bytes of compact UTF-8 JSON"):
            executor.execute(dataset, "SELECT value FROM synthetic")
        cursor.fetchone.assert_not_called()


@pytest.mark.parametrize("operation", ["execute", "ask", "investigate"])
def test_facade_enforces_result_bytes_without_automatic_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    from unittest.mock import Mock

    from verisight import VeriSight
    from verisight.config import Settings
    from verisight.execution.decisions import InvestigationAction, InvestigationDecision
    from verisight.execution.investigation_result import InvestigationStatus
    from verisight.execution.planning import QueryPlan

    path = tmp_path / "observations.csv"
    path.write_text("value\n1\n", encoding="utf-8")
    monkeypatch.setenv("VERISIGHT_MAX_QUERY_RESULT_BYTES", "64")
    settings = Settings(allow_llm_data_disclosure=False)
    assert settings.max_query_result_bytes == 64
    sql = "SELECT repeat('x', 100) AS value FROM observations"
    planner = Mock()
    planner.plan.return_value = QueryPlan("Read values", sql)
    repairer = Mock()
    investigator = Mock()
    investigator.decide.side_effect = [
        InvestigationDecision(InvestigationAction.INVESTIGATE, "Read", "Read values"),
        InvestigationDecision(InvestigationAction.FINISH, "Attempt completed"),
    ]
    synthesizer = Mock()
    app = VeriSight(
        settings=settings,
        planner=planner,
        repairer=repairer,
        investigator=investigator,
        synthesizer=synthesizer,
    )
    if operation == "investigate":
        result = app.investigate(path, "Read values", max_steps=1)
        assert result.status is InvestigationStatus.INCOMPLETE
        assert result.observation_count == 0
        assert result.failed_attempt_count == 1
        assert result.failed_attempts[0].error_type == "QueryResultLimitError"
        synthesizer.synthesize.assert_not_called()
    else:
        with pytest.raises(QueryResultLimitError):
            if operation == "execute":
                app.execute(path, sql)
            else:
                app.ask(path, "Read values")
    repairer.repair.assert_not_called()


def test_result_byte_failure_preserves_previous_observations(tmp_path: Path) -> None:
    from unittest.mock import Mock

    from verisight import VeriSight
    from verisight.config import Settings
    from verisight.execution.decisions import InvestigationAction, InvestigationDecision
    from verisight.execution.investigation_result import InvestigationStatus
    from verisight.execution.planning import QueryPlan

    path = tmp_path / "observations.csv"
    path.write_text("value\n1\n", encoding="utf-8")
    planner = Mock()
    planner.plan.side_effect = [
        QueryPlan("Read value", "SELECT value FROM observations"),
        QueryPlan("Read text", "SELECT repeat('x', 100) AS value FROM observations"),
    ]
    investigator = Mock()
    investigator.decide.side_effect = [
        InvestigationDecision(InvestigationAction.INVESTIGATE, "Read", "Read value"),
        InvestigationDecision(InvestigationAction.INVESTIGATE, "Read", "Read text"),
        InvestigationDecision(InvestigationAction.INVESTIGATE, "Read", "Read more"),
    ]
    repairer = Mock()
    synthesizer = Mock()
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False, max_query_result_bytes=64),
        planner=planner,
        repairer=repairer,
        investigator=investigator,
        synthesizer=synthesizer,
    )

    result = app.investigate(path, "Inspect values", max_steps=2)

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == 1
    assert result.observations[0].result.rows == ((1,),)
    assert result.failed_attempt_count == 1
    assert result.failed_attempts[0].error_type == "QueryResultLimitError"
    synthesizer.synthesize.assert_not_called()
    repairer.repair.assert_not_called()


@pytest.mark.parametrize("phase", ["dispatch", "execute", "fetch", "completion"])
def test_expired_query_never_returns_success(phase: str) -> None:
    """Cover lost interrupts and delayed timer scheduling without timing sleeps."""
    from threading import Event
    from unittest.mock import MagicMock, patch

    dataset = LoadedDataset(tables=[])
    executor = DuckDBExecutor(execution_timeout_seconds=1)
    connection = MagicMock()
    cursor = connection.execute.return_value
    cursor.description = [("value",)]
    cursor.fetchone.side_effect = [(1,), None]
    clock = [0.0]
    finished = MagicMock()
    # Force a second interrupt, then let the synthetic callback return.
    finished.wait.side_effect = [False, True]
    add_bytes = executor._add_result_bytes

    def encode(used: int, value: QueryScalar) -> int:
        result = add_bytes(used, value)
        if phase == "completion" and value == 1:
            # Expire during row encoding, after the successful fetch checks.
            clock[0] = 2.0
        return result

    with (
        patch.object(executor, "_connection") as context,
        patch.object(executor, "_add_result_bytes", side_effect=encode),
        patch("verisight.execution.engine.Timer") as timer,
        patch("verisight.execution.engine.Event", side_effect=[Event(), finished]),
        patch("verisight.execution.engine.monotonic", lambda: clock[0]),
    ):
        context.return_value.__enter__.return_value = connection

        def expire() -> None:
            timer.call_args.args[1]()

        def execute(_query: str) -> object:
            # Expiry within execute models the gap after the dispatch check.
            clock[0] = 2.0
            return cursor

        def fetch() -> tuple[int]:
            clock[0] = 2.0
            return (1,)

        if phase == "dispatch":
            timer.return_value.start.side_effect = expire
        elif phase == "execute":
            connection.execute.side_effect = execute
        elif phase == "fetch":
            cursor.fetchone.side_effect = fetch

        with pytest.raises(QueryTimeoutError, match="1 seconds"):
            executor.execute(dataset, "SELECT 1 AS value")
        if phase == "dispatch":
            connection.execute.assert_not_called()
            assert connection.interrupt.call_count == 2
        else:
            connection.execute.assert_called_once()
        finished.set.assert_called_once_with()
        timer.return_value.cancel.assert_called_once_with()
        timer.return_value.join.assert_called_once_with()
        context.return_value.__exit__.assert_called_once()
