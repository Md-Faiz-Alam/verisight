from pathlib import Path

import pandas as pd
import pytest

from verisight.execution.exceptions import (
    QueryExecutionError,
    QueryPlanningError,
    QueryResultLimitError,
    QueryRuntimeError,
    QueryValidationError,
)
from verisight.execution.execution import QueryExecution
from verisight.execution.planning import QueryPlan, QueryRequest
from verisight.execution.repair import QueryRepairRequest
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


def test_service_repairs_runtime_failure_once() -> None:
    class BrokenPlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql="SELECT SUM(missing_amount) AS total_amount FROM orders",
            )

    class StubRepairer:
        def __init__(self) -> None:
            self.requests: list[QueryRepairRequest] = []

        def repair(self, request: QueryRepairRequest) -> QueryPlan:
            self.requests.append(request)

            return QueryPlan(
                question=request.question,
                sql="SELECT SUM(amount) AS total_amount FROM orders",
            )

    repairer = StubRepairer()

    service = AnalyticalExecutionService(
        _make_dataset(),
        planner=BrokenPlanner(),
        repairer=repairer,
    )

    result = service.ask("What is the total amount?")

    assert result.columns == ("total_amount",)
    assert result.rows == ((60.0,),)

    assert len(repairer.requests) == 1

    repair_request = repairer.requests[0]

    assert repair_request.question == "What is the total amount?"
    assert repair_request.failed_sql == (
        "SELECT SUM(missing_amount) AS total_amount FROM orders"
    )
    assert "missing_amount" in repair_request.error
    assert repair_request.context is service.context


def test_service_does_not_repair_validation_failure() -> None:
    class UnsafePlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql="DROP TABLE orders",
            )

    class FailingRepairer:
        def repair(self, request: QueryRepairRequest) -> QueryPlan:
            raise AssertionError("Repairer must not be called.")

    service = AnalyticalExecutionService(
        _make_dataset(),
        planner=UnsafePlanner(),
        repairer=FailingRepairer(),
    )

    with pytest.raises(
        QueryValidationError,
        match="Only read-only analytical SELECT queries are allowed.",
    ):
        service.ask("Delete the orders table")


def test_service_propagates_runtime_failure_without_repairer() -> None:
    class BrokenPlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql="SELECT missing_amount FROM orders",
            )

    service = AnalyticalExecutionService(
        _make_dataset(),
        planner=BrokenPlanner(),
    )

    with pytest.raises(
        QueryRuntimeError,
        match="Analytical query execution failed:",
    ):
        service.ask("Show the amount.")


def test_service_does_not_retry_failed_repair() -> None:
    class BrokenPlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql="SELECT missing_amount FROM orders",
            )

    class BrokenRepairer:
        def __init__(self) -> None:
            self.call_count = 0

        def repair(self, request: QueryRepairRequest) -> QueryPlan:
            self.call_count += 1

            return QueryPlan(
                question=request.question,
                sql="SELECT still_missing FROM orders",
            )

    repairer = BrokenRepairer()

    service = AnalyticalExecutionService(
        _make_dataset(),
        planner=BrokenPlanner(),
        repairer=repairer,
    )

    with pytest.raises(
        QueryRuntimeError,
        match="Analytical query execution failed:",
    ):
        service.ask("Show the amount.")

    assert repairer.call_count == 1


def test_repaired_query_still_passes_through_execution_validation() -> None:
    class BrokenPlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql="SELECT missing_amount FROM orders",
            )

    class UnsafeRepairer:
        def repair(self, request: QueryRepairRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql="DROP TABLE orders",
            )

    service = AnalyticalExecutionService(
        _make_dataset(),
        planner=BrokenPlanner(),
        repairer=UnsafeRepairer(),
    )

    with pytest.raises(
        QueryValidationError,
        match="Only read-only analytical SELECT queries are allowed.",
    ):
        service.ask("Show the amount.")


def test_service_rejects_empty_sql_from_repairer() -> None:
    class BrokenPlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql="SELECT missing_amount FROM orders",
            )

    class EmptyRepairer:
        def repair(self, request: QueryRepairRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql=" ",
            )

    service = AnalyticalExecutionService(
        _make_dataset(),
        planner=BrokenPlanner(),
        repairer=EmptyRepairer(),
    )

    with pytest.raises(
        QueryPlanningError,
        match="Query repairer returned an empty SQL query.",
    ):
        service.ask("Show the amount.")


def test_service_rejects_repair_plan_for_different_question() -> None:
    class BrokenPlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql="SELECT missing_amount FROM orders",
            )

    class MismatchedRepairer:
        def repair(self, request: QueryRepairRequest) -> QueryPlan:
            return QueryPlan(
                question="A different question",
                sql="SELECT amount FROM orders",
            )

    service = AnalyticalExecutionService(
        _make_dataset(),
        planner=BrokenPlanner(),
        repairer=MismatchedRepairer(),
    )

    with pytest.raises(
        QueryPlanningError,
        match="Query repairer returned a plan for a different question.",
    ):
        service.ask("Show the amount.")


def test_service_run_preserves_successful_plan_and_result() -> None:
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

    execution = service.run("What is the total amount?")

    assert isinstance(execution, QueryExecution)
    assert execution.plan == QueryPlan(
        question="What is the total amount?",
        sql="SELECT SUM(amount) AS total_amount FROM orders",
    )
    assert execution.result.columns == ("total_amount",)
    assert execution.result.rows == ((60.0,),)


def test_service_run_preserves_repaired_plan_and_result() -> None:
    class BrokenPlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql="SELECT SUM(missing_amount) AS total_amount FROM orders",
            )

    class StubRepairer:
        def repair(self, request: QueryRepairRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql="SELECT SUM(amount) AS total_amount FROM orders",
            )

    service = AnalyticalExecutionService(
        _make_dataset(),
        planner=BrokenPlanner(),
        repairer=StubRepairer(),
    )

    execution = service.run("What is the total amount?")

    assert execution.plan == QueryPlan(
        question="What is the total amount?",
        sql="SELECT SUM(amount) AS total_amount FROM orders",
    )
    assert execution.result.columns == ("total_amount",)
    assert execution.result.rows == ((60.0,),)


def test_service_ask_returns_result_from_execution() -> None:
    class StubPlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql="SELECT COUNT(*) AS order_count FROM orders",
            )

    service = AnalyticalExecutionService(
        _make_dataset(),
        planner=StubPlanner(),
    )

    result = service.ask("How many orders are there?")

    assert result.columns == ("order_count",)
    assert result.rows == ((3,),)


def test_service_enforces_result_row_limit() -> None:
    service = AnalyticalExecutionService(
        _make_dataset(),
        max_result_rows=2,
    )

    with pytest.raises(
        QueryResultLimitError,
        match="Analytical query result exceeded the maximum of 2 rows.",
    ):
        service.execute(
            """
            SELECT order_id
            FROM orders
            ORDER BY order_id
            """
        )


def test_service_does_not_repair_result_limit_failure() -> None:
    class StubPlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql=("SELECT order_id FROM orders ORDER BY order_id"),
            )

    class FailingRepairer:
        def repair(self, request: QueryRepairRequest) -> QueryPlan:
            raise AssertionError(
                "Repairer must not be called for result-limit failures."
            )

    service = AnalyticalExecutionService(
        _make_dataset(),
        planner=StubPlanner(),
        repairer=FailingRepairer(),
        max_result_rows=2,
    )

    with pytest.raises(
        QueryResultLimitError,
        match="Analytical query result exceeded the maximum of 2 rows.",
    ):
        service.ask("Show all order IDs.")


def test_service_enforces_query_memory_limit() -> None:
    service = AnalyticalExecutionService(
        _make_dataset(),
        memory_limit_mb=64,
    )

    with service._executor._connection(service._dataset) as connection:
        result = connection.execute(
            """
            SELECT value
            FROM duckdb_settings()
            WHERE name = 'memory_limit'
            """
        ).fetchone()

    assert result is not None
    assert str(result[0]) != "unlimited"
