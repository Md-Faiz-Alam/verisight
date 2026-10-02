from pathlib import Path

import pandas as pd
import pytest

from verisight.execution.exceptions import (
    QueryExecutionError,
    QueryPlanningError,
)
from verisight.execution.planning import QueryPlan, QueryRequest
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

    assert service.formatted_context == (
        "RELATION orders\n"
        "DISPLAY NAME: Orders\n"
        "ROWS: 3\n"
        "COLUMNS:\n"
        "- order_id | integer | int64 | nullable=false\n"
        "- amount | float | float64 | nullable=false"
    )


def test_service_reuses_formatted_query_context() -> None:
    service = AnalyticalExecutionService(_make_dataset())

    first_context = service.formatted_context
    second_context = service.formatted_context

    assert first_context is second_context


def test_service_plans_natural_language_question() -> None:
    class StubPlanner:
        def __init__(self) -> None:
            self.request: QueryRequest | None = None

        def plan(self, request: QueryRequest) -> QueryPlan:
            self.request = request

            return QueryPlan(
                question=request.question,
                sql="SELECT SUM(amount) AS total_amount FROM orders",
            )

    planner = StubPlanner()
    service = AnalyticalExecutionService(
        _make_dataset(),
        planner=planner,
    )

    plan = service.plan("What is the total amount?")

    assert plan.question == "What is the total amount?"
    assert plan.sql == "SELECT SUM(amount) AS total_amount FROM orders"

    assert planner.request is not None
    assert planner.request.question == "What is the total amount?"
    assert planner.request.context is service.context


def test_service_requires_planner_for_planning() -> None:
    service = AnalyticalExecutionService(_make_dataset())

    with pytest.raises(
        QueryPlanningError,
        match="No query planner is configured.",
    ):
        service.plan("What is the total amount?")


def test_service_plans_and_executes_natural_language_question() -> None:
    class StubPlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql="SELECT SUM(amount) AS total_amount FROM orders",
            )

    service = AnalyticalExecutionService(
        _make_dataset(),
        planner=StubPlanner(),
    )

    result = service.ask("What is the total amount?")

    assert result.columns == ("total_amount",)
    assert result.rows == ((60.0,),)


def test_planned_query_still_passes_through_execution_validation() -> None:
    class UnsafePlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql="DROP TABLE orders",
            )

    service = AnalyticalExecutionService(
        _make_dataset(),
        planner=UnsafePlanner(),
    )

    with pytest.raises(
        QueryExecutionError,
        match="Only read-only analytical SELECT queries are allowed.",
    ):
        service.ask("Delete the orders table")


@pytest.mark.parametrize(
    "question",
    [
        "",
        " ",
        "\n\t",
    ],
)
def test_service_rejects_empty_planning_question(question: str) -> None:
    service = AnalyticalExecutionService(_make_dataset())

    with pytest.raises(
        QueryPlanningError,
        match="Analytical question must not be empty.",
    ):
        service.plan(question)


def test_service_rejects_empty_sql_from_planner() -> None:
    class EmptyPlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql=" ",
            )

    service = AnalyticalExecutionService(
        _make_dataset(),
        planner=EmptyPlanner(),
    )

    with pytest.raises(
        QueryPlanningError,
        match="Query planner returned an empty SQL query.",
    ):
        service.plan("What is the total order amount?")


def test_service_rejects_plan_for_different_question() -> None:
    class MismatchedPlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question="A different question",
                sql="SELECT 1",
            )

    service = AnalyticalExecutionService(
        _make_dataset(),
        planner=MismatchedPlanner(),
    )

    with pytest.raises(
        QueryPlanningError,
        match="Query planner returned a plan for a different question.",
    ):
        service.plan("What is the total order amount?")
