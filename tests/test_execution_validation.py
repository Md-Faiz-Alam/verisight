from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from sqlglot.errors import ParseError

from verisight.error_reporting import ErrorCode
from verisight.execution.engine import DuckDBExecutor
from verisight.execution.exceptions import (
    QueryExecutionError,
    QueryValidationError,
)
from verisight.execution.validation import (
    AnalyticalQueryValidator,
    _mask_sql_literals_and_comments,
    validate_dataset_relations,
)
from verisight.ingestion.models import LoadedDataset, LoadedTable, SourceMetadata
from verisight.public_api import run_public_operation


@pytest.mark.parametrize(
    "query",
    [
        "SELECT 1",
        "SELECT 1 + 2 AS value",
        """
        WITH values_cte AS (
            SELECT 1 AS value
        )
        SELECT value
        FROM values_cte
        """,
        """
        SELECT customer_id, SUM(amount)
        FROM orders
        GROUP BY customer_id
        """,
        """
        SELECT *
        FROM customers
        JOIN orders
            ON customers.customer_id = orders.customer_id
        """,
        """
        SELECT
            customer_id,
            ROW_NUMBER() OVER (
                ORDER BY customer_id
            ) AS row_number
        FROM customers
        """,
        """
        SELECT customer_id
        FROM customers
        UNION
        SELECT customer_id
        FROM orders
        """,
    ],
)
def test_accepts_analytical_select_queries(query: str) -> None:
    AnalyticalQueryValidator().validate(query)


@pytest.mark.parametrize(
    "query",
    [
        "CREATE TABLE example AS SELECT 1",
        "INSERT INTO example VALUES (1)",
        "UPDATE example SET value = 2",
        "DELETE FROM example",
        "DROP TABLE example",
        "COPY (SELECT 1) TO 'output.csv'",
        "ATTACH 'database.db' AS external_db",
        "DETACH external_db",
        "INSTALL httpfs",
        "LOAD httpfs",
        "CALL checkpoint()",
        "EXPORT DATABASE 'export_dir'",
        "SET threads = 1",
        "RESET threads",
        "VACUUM",
    ],
)
def test_rejects_non_select_statements(query: str) -> None:
    with pytest.raises(
        QueryValidationError,
        match="Only read-only analytical SELECT queries are allowed.",
    ):
        AnalyticalQueryValidator().validate(query)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM read_csv_auto('data.csv')",
        "SELECT * FROM read_csv('data.csv')",
        "SELECT * FROM read_parquet('data.parquet')",
        "SELECT * FROM read_json_auto('data.json')",
        "SELECT * FROM read_json('data.json')",
        "SELECT read_blob('data.txt')",
        "SELECT * FROM glob('*')",
        "SELECT getenv('PATH')",
        "SELECT * FROM read_text('data.txt')",
        "SELECT * FROM read_ndjson('data.ndjson')",
        "SELECT * FROM read_ndjson_auto('data.ndjson')",
        "SELECT * FROM read_csv/**/('data.csv')",
    ],
)
def test_rejects_external_access_from_select(query: str) -> None:
    with pytest.raises(
        QueryValidationError,
        match="External data access is not allowed",
    ):
        AnalyticalQueryValidator().validate(query)


@pytest.mark.parametrize(
    "query",
    [
        "PRAGMA version",
        "PRAGMA database_list",
    ],
)
def test_rejects_pragma_queries(query: str) -> None:
    with pytest.raises(
        QueryValidationError,
        match="PRAGMA statements are not allowed",
    ):
        AnalyticalQueryValidator().validate(query)


def test_rejects_multiple_statements() -> None:
    with pytest.raises(
        QueryValidationError,
        match="requires exactly one SQL statement",
    ):
        AnalyticalQueryValidator().validate("SELECT 1; SELECT 2")


@pytest.mark.parametrize(
    "query",
    [
        "",
        " ",
        "\n\t",
    ],
)
def test_rejects_empty_query(query: str) -> None:
    with pytest.raises(
        QueryValidationError,
        match="Analytical query must not be empty.",
    ):
        AnalyticalQueryValidator().validate(query)


def test_invalid_sql_raises_validation_error() -> None:
    with pytest.raises(
        QueryValidationError,
        match="Analytical query validation failed:",
    ):
        AnalyticalQueryValidator().validate("SELECT FROM")


def test_validation_error_is_query_execution_error() -> None:
    error = QueryValidationError("Invalid query")

    assert isinstance(error, QueryExecutionError)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT 'read_csv(' AS value",
        "SELECT 'read_parquet(' AS value",
        "SELECT 'getenv(' AS value",
        "SELECT 'it''s read_csv(' AS value",
        "SELECT 1 -- read_csv('data.csv')",
        """
        SELECT 1
        /* read_parquet('data.parquet') */
        """,
    ],
)
def test_external_access_names_inside_literals_and_comments_are_allowed(
    query: str,
) -> None:
    AnalyticalQueryValidator().validate(query)


def test_masks_unterminated_single_quoted_literal_preserving_newline() -> None:
    query = "SELECT 'external\nread_csv("

    masked = _mask_sql_literals_and_comments(query)

    assert masked == "SELECT          \n         "


def test_nested_block_comment_does_not_trigger_external_access_block() -> None:
    query = "SELECT 1 /* outer /* inner */ read_csv('data.csv') */"

    AnalyticalQueryValidator().validate(query)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT 1 /* outer /* inner */ outer */",
        "SELECT 1 /* outer\n/* inner */\nouter */",
        "SELECT 1 /* outer /* inner */",
    ],
)
def test_masks_nested_block_comments(query: str) -> None:
    masked = _mask_sql_literals_and_comments(query)

    expected = "SELECT 1" + "".join(
        character if character in "\r\n" else " "
        for character in query[len("SELECT 1") :]
    )

    assert masked == expected
    assert len(masked) == len(query)


def test_masks_unterminated_block_comment_preserving_newline() -> None:
    query = "SELECT 1 /* external\nread_csv("

    masked = _mask_sql_literals_and_comments(query)

    assert masked == "SELECT 1            \n         "


@pytest.mark.parametrize(
    "query",
    [
        """SELECT * FROM "read_csv"('data.csv')""",
        """SELECT * FROM "read_csv_auto"('data.csv')""",
        """SELECT * FROM "read_parquet"('data.parquet')""",
        """SELECT * FROM "read_json"('data.json')""",
        """SELECT * FROM "read_json_auto"('data.json')""",
        """SELECT * FROM "read_text"('data.txt')""",
        """SELECT * FROM "read_ndjson"('data.ndjson')""",
        """SELECT * FROM "read_ndjson_auto"('data.ndjson')""",
        """SELECT "read_blob"('data.txt')""",
        """SELECT * FROM "glob"('*')""",
        """SELECT "getenv"('PATH')""",
    ],
)
def test_rejects_quoted_external_access_functions(
    query: str,
) -> None:
    with pytest.raises(
        QueryValidationError,
        match="External data access is not allowed",
    ):
        AnalyticalQueryValidator().validate(query)


@pytest.mark.parametrize(
    "error",
    [
        ParseError("SQL parsing failed"),
        ValueError("SQL scope analysis failed"),
    ],
)
def test_dataset_relation_validation_rejects_sql_analysis_errors(
    error: Exception,
) -> None:
    with (
        patch(
            "verisight.execution.validation.sqlglot.parse_one",
            side_effect=error,
        ),
        pytest.raises(
            QueryValidationError,
            match="Dataset access is not allowed: SQL analysis failed",
        ),
    ):
        validate_dataset_relations(
            "SELECT * FROM orders",
            frozenset({"orders"}),
        )


def test_dataset_relation_validation_rejects_unresolved_scopes() -> None:
    with (
        patch(
            "verisight.execution.validation.traverse_scope",
            return_value=[],
        ),
        pytest.raises(
            QueryValidationError,
            match="Dataset access is not allowed: SQL scopes could not be resolved",
        ),
    ):
        validate_dataset_relations(
            "SELECT * FROM orders",
            frozenset({"orders"}),
        )


def test_dataset_relation_validation_rejects_unsupported_source() -> None:
    class UnsupportedScope:
        selected_sources = {"unsupported": (None, object())}

    with (
        patch(
            "verisight.execution.validation.traverse_scope",
            return_value=[UnsupportedScope()],
        ),
        pytest.raises(
            QueryValidationError,
            match="Dataset access is not allowed: unsupported SQL source",
        ),
    ):
        validate_dataset_relations(
            "SELECT * FROM orders",
            frozenset({"orders"}),
        )


@pytest.mark.parametrize(
    "query",
    [
        "SELECT CAST(current_schemas(true) AS VARCHAR)",
        "SELECT CAST(CuRrEnT_ScHeMaS/* comment */(false) AS VARCHAR)",
        'SELECT CAST("CURRENT_SCHEMAS"(true) AS VARCHAR)',
        "SELECT CAST(main.current_schemas(true) AS VARCHAR)",
        'SELECT CAST(main."CURRENT_SCHEMAS"(true) AS VARCHAR)',
        "SELECT (SELECT CAST(current_schemas(true) AS VARCHAR))",
        "WITH unused AS (SELECT current_schemas(true)) SELECT 1",
        "SELECT name FROM UNNEST(current_schemas(true)) AS schemas(name)",
        "SELECT CASE WHEN false THEN CAST(current_schemas(true) AS VARCHAR) "
        "ELSE 'unused' END",
    ],
    ids=[
        "cast-to-scalar",
        "mixed-case-comment",
        "quoted",
        "qualified",
        "qualified-quoted",
        "nested-select",
        "unused-cte",
        "unnest",
        "unreachable-expression",
    ],
)
def test_schema_list_functions_are_rejected_before_connection(query: str) -> None:
    dataset = LoadedDataset(tables=[])
    executor = DuckDBExecutor(
        memory_limit_mb=64, execution_timeout_seconds=1, max_result_rows=20
    )
    with patch("verisight.execution.engine.duckdb.connect") as connect:
        with pytest.raises(QueryValidationError, match="internal metadata function"):
            executor.execute(dataset, query)
        outcome = run_public_operation(lambda: executor.execute(dataset, query))
        connect.assert_not_called()
    assert not outcome.succeeded
    assert outcome.value is None
    assert outcome.error is not None
    assert outcome.error.code is ErrorCode.QUERY_VALIDATION_ERROR
    assert query not in outcome.error.message


def test_schema_function_names_in_data_literals_and_comments_remain_queryable() -> None:
    data = pd.DataFrame({"current_schemas": [7]})
    original = data.copy(deep=True)
    dataset = LoadedDataset(
        tables=[
            LoadedTable(
                name="orders",
                data=data,
                source=SourceMetadata(Path("orders.csv"), "orders.csv", ".csv", 1),
            )
        ]
    )
    result = DuckDBExecutor(
        memory_limit_mb=64, execution_timeout_seconds=1, max_result_rows=20
    ).execute(
        dataset,
        "SELECT \"current_schemas\", 'current_schemas(true)' AS note FROM orders "
        "/* current_schemas(true) */",
    )
    assert result.columns == ("current_schemas", "note")
    assert result.rows == ((7, "current_schemas(true)"),)
    pd.testing.assert_frame_equal(data, original)
