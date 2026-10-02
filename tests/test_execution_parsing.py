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


def test_require_sql_rejects_empty_payload() -> None:
    with pytest.raises(
        QueryPlanningError,
        match="Query planner returned an empty SQL query.",
    ):
        QueryResponseParser._require_sql("   ")
