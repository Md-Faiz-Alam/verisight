import pytest

from verisight.execution.exceptions import (
    QueryExecutionError,
    QueryValidationError,
)
from verisight.execution.validation import (
    AnalyticalQueryValidator,
    _mask_sql_literals_and_comments,
)


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


def test_masks_unterminated_block_comment_preserving_newline() -> None:
    query = "SELECT 1 /* external\nread_csv("

    masked = _mask_sql_literals_and_comments(query)

    assert masked == "SELECT 1            \n         "
