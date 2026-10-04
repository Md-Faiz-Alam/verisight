import pytest

from verisight.execution.exceptions import QueryPlanningError
from verisight.execution.parsing import QueryResponseParser


def test_parses_plain_sql() -> None:
    sql = QueryResponseParser().parse("SELECT SUM(amount) AS total_amount FROM orders")

    assert sql == "SELECT SUM(amount) AS total_amount FROM orders"


def test_strips_surrounding_whitespace() -> None:
    sql = QueryResponseParser().parse(
        "\n  SELECT COUNT(*) AS order_count FROM orders  \n"
    )

    assert sql == "SELECT COUNT(*) AS order_count FROM orders"


def test_parses_sql_markdown_fence() -> None:
    sql = QueryResponseParser().parse(
        """
        ```sql
        SELECT SUM(amount) AS total_amount
        FROM orders
        ```
        """
    )

    assert sql == ("SELECT SUM(amount) AS total_amount\n        FROM orders")


def test_parses_generic_markdown_fence() -> None:
    sql = QueryResponseParser().parse(
        """
        ```
        SELECT COUNT(*) AS order_count
        FROM orders
        ```
        """
    )

    assert sql == ("SELECT COUNT(*) AS order_count\n        FROM orders")


def test_accepts_single_statement_with_trailing_semicolon() -> None:
    sql = QueryResponseParser().parse("SELECT COUNT(*) AS order_count FROM orders;")

    assert sql == "SELECT COUNT(*) AS order_count FROM orders;"


def test_accepts_semicolon_inside_single_quoted_string() -> None:
    sql = QueryResponseParser().parse("SELECT 'alpha;beta' AS value FROM orders")

    assert sql == "SELECT 'alpha;beta' AS value FROM orders"


def test_accepts_semicolon_inside_escaped_single_quoted_string() -> None:
    sql = QueryResponseParser().parse("SELECT 'alpha'';''beta' AS value FROM orders")

    assert sql == "SELECT 'alpha'';''beta' AS value FROM orders"


def test_accepts_semicolon_inside_double_quoted_identifier() -> None:
    sql = QueryResponseParser().parse('SELECT "amount;value" FROM orders')

    assert sql == 'SELECT "amount;value" FROM orders'


def test_accepts_semicolon_inside_escaped_double_quoted_identifier() -> None:
    sql = QueryResponseParser().parse('SELECT "amount"";""value" FROM orders')

    assert sql == 'SELECT "amount"";""value" FROM orders'


@pytest.mark.parametrize(
    "response",
    [
        "",
        " ",
        "\n\t",
    ],
)
def test_rejects_empty_response(response: str) -> None:
    with pytest.raises(
        QueryPlanningError,
        match="Query planner returned an empty response.",
    ):
        QueryResponseParser().parse(response)


@pytest.mark.parametrize(
    "response",
    [
        "```sql\n```",
        "```\n```",
    ],
)
def test_rejects_empty_fenced_sql(response: str) -> None:
    with pytest.raises(
        QueryPlanningError,
        match="Query planner returned an empty SQL query.",
    ):
        QueryResponseParser().parse(response)


@pytest.mark.parametrize(
    "response",
    [
        "```python\nSELECT 1\n```",
        "Here is the query:\n```sql\nSELECT 1\n```",
        "```sql\nSELECT 1\n```\nExtra text",
    ],
)
def test_rejects_invalid_fenced_response(response: str) -> None:
    with pytest.raises(
        QueryPlanningError,
        match="Query planner returned an invalid fenced response.",
    ):
        QueryResponseParser().parse(response)


@pytest.mark.parametrize(
    "response",
    [
        "SELECT 1; SELECT 2",
        "SELECT 1;\nSELECT 2",
        "SELECT 1;\n\nSELECT 2;",
        "```sql\nSELECT 1;\nSELECT 2\n```",
        "```\nSELECT 1;\nSELECT 2\n```",
    ],
)
def test_rejects_multiple_sql_statements(response: str) -> None:
    with pytest.raises(
        QueryPlanningError,
        match="Query planner returned multiple SQL statements.",
    ):
        QueryResponseParser().parse(response)


def test_require_sql_rejects_empty_payload() -> None:
    with pytest.raises(
        QueryPlanningError,
        match="Query planner returned an empty SQL query.",
    ):
        QueryResponseParser._require_sql("   ")


def test_require_single_statement_rejects_multiple_statements() -> None:
    with pytest.raises(
        QueryPlanningError,
        match="Query planner returned multiple SQL statements.",
    ):
        QueryResponseParser._require_single_statement(
            "SELECT COUNT(*) FROM orders; SELECT 1"
        )
