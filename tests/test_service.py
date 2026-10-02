from pathlib import Path

import pandas as pd
import pytest

from verisight.analysis.result import DatasetAnalysisResult
from verisight.config import Settings
from verisight.execution.exceptions import QueryExecutionError, QueryPlanningError
from verisight.execution.planning import QueryPlan, QueryRequest
from verisight.service import VeriSight


class StubQueryPlanner:
    """Query planner used by public service integration tests."""

    def plan(self, request: QueryRequest) -> QueryPlan:
        return QueryPlan(
            question=request.question,
            sql="""
            SELECT
                COUNT(*) AS order_count,
                SUM(amount) AS total_amount
            FROM orders
            """,
        )


def test_analyzes_single_csv_file(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [10.0, 20.0, 30.0],
        }
    ).to_csv(path, index=False)

    result = VeriSight().analyze([path])

    assert isinstance(result, DatasetAnalysisResult)
    assert result.analysis.schema.table_count == 1
    assert result.analysis.profile.table_count == 1

    table_schema = result.analysis.schema.tables[0]
    table_profile = result.analysis.profile.tables[0]

    assert table_schema.name == "orders"
    assert table_profile.name == "orders"
    assert table_schema.relation_name == "orders"
    assert table_profile.relation_name == "orders"


def test_analyzes_multiple_files(tmp_path: Path) -> None:
    customers_path = tmp_path / "customers.csv"
    orders_path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "customer_id": [1, 2],
            "name": ["Alice", "Bob"],
        }
    ).to_csv(customers_path, index=False)

    pd.DataFrame(
        {
            "order_id": [10, 20],
            "customer_id": [1, 2],
        }
    ).to_csv(orders_path, index=False)

    result = VeriSight().analyze(
        [
            customers_path,
            orders_path,
        ]
    )

    assert result.analysis.schema.table_count == 2
    assert result.analysis.profile.table_count == 2

    assert tuple(table.relation_name for table in result.analysis.schema.tables) == (
        "customers",
        "orders",
    )

    assert tuple(table.relation_name for table in result.analysis.profile.tables) == (
        "customers",
        "orders",
    )


def test_analyze_builds_summary_and_insights(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "status": ["open", "open", "closed"],
        }
    ).to_csv(path, index=False)

    result = VeriSight().analyze([path])

    assert result.summary.table_count == 1
    assert result.insight_count == len(result.insights)


def test_analyze_preserves_quality_issues(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [10.0, None, 30.0],
        }
    ).to_csv(path, index=False)

    result = VeriSight().analyze([path])

    assert result.issue_count > 0
    assert result.issue_count == len(result.analysis.issues)


def test_analyzes_with_explicit_settings(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
        }
    ).to_csv(path, index=False)

    service = VeriSight(Settings())

    result = service.analyze([path])

    assert result.analysis.schema.table_count == 1
    assert result.analysis.profile.table_count == 1


def test_empty_input_produces_empty_analysis_result() -> None:
    result = VeriSight().analyze([])

    assert result.analysis.schema.table_count == 0
    assert result.analysis.profile.table_count == 0
    assert result.issue_count == 0
    assert result.insight_count == len(result.insights)


def test_verisight_is_available_from_package_root() -> None:
    from verisight import VeriSight as PublicVeriSight

    assert PublicVeriSight is VeriSight


def test_executes_query_against_single_csv_file(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [10.0, 20.0, 30.0],
        }
    ).to_csv(path, index=False)

    result = VeriSight().execute(
        [path],
        """
        SELECT order_id, amount
        FROM orders
        WHERE amount >= 20
        ORDER BY order_id
        """,
    )

    assert result.columns == (
        "order_id",
        "amount",
    )
    assert result.rows == (
        (2, 20.0),
        (3, 30.0),
    )


def test_executes_query_across_multiple_files(tmp_path: Path) -> None:
    customers_path = tmp_path / "customers.csv"
    orders_path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "customer_id": [1, 2],
            "name": ["Alice", "Bob"],
        }
    ).to_csv(customers_path, index=False)

    pd.DataFrame(
        {
            "order_id": [10, 20, 30],
            "customer_id": [1, 1, 2],
            "amount": [10.0, 20.0, 50.0],
        }
    ).to_csv(orders_path, index=False)

    result = VeriSight().execute(
        [
            customers_path,
            orders_path,
        ],
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


def test_asks_natural_language_question_against_csv_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [10.0, 20.0, 30.0],
        }
    ).to_csv(path, index=False)

    result = VeriSight(planner=StubQueryPlanner()).ask(
        [path],
        "How many orders are there and what is the total amount?",
    )

    assert result.columns == (
        "order_count",
        "total_amount",
    )
    assert result.rows == ((3, 60.0),)


def test_ask_requires_configured_query_planner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
        }
    ).to_csv(path, index=False)

    with pytest.raises(
        QueryPlanningError,
        match="No query planner is configured.",
    ):
        VeriSight().ask(
            [path],
            "How many orders are there?",
        )


def test_public_ask_preserves_safe_execution_validation(
    tmp_path: Path,
) -> None:
    class UnsafeQueryPlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql="DROP TABLE orders",
            )

    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
        }
    ).to_csv(path, index=False)

    with pytest.raises(
        QueryExecutionError,
        match="Only read-only analytical SELECT queries are allowed.",
    ):
        VeriSight(planner=UnsafeQueryPlanner()).ask(
            [path],
            "Delete the orders table.",
        )
