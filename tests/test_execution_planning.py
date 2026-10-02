from verisight.execution.context import QueryContext
from verisight.execution.planning import QueryPlan, QueryPlanner, QueryRequest


class StubQueryPlanner:
    """Simple planner implementation used to verify the planner contract."""

    def plan(self, request: QueryRequest) -> QueryPlan:
        return QueryPlan(
            question=request.question,
            sql="SELECT 1 AS value",
        )


def _plan_query(
    planner: QueryPlanner,
    request: QueryRequest,
) -> QueryPlan:
    return planner.plan(request)


def test_query_request_preserves_question_and_context() -> None:
    context = QueryContext(relations=())

    request = QueryRequest(
        question="What is the total revenue?",
        context=context,
    )

    assert request.question == "What is the total revenue?"
    assert request.context is context


def test_query_plan_preserves_question_and_sql() -> None:
    plan = QueryPlan(
        question="What is the total revenue?",
        sql="SELECT SUM(revenue) AS total_revenue FROM orders",
    )

    assert plan.question == "What is the total revenue?"
    assert plan.sql == "SELECT SUM(revenue) AS total_revenue FROM orders"


def test_query_planner_protocol_accepts_compatible_implementation() -> None:
    request = QueryRequest(
        question="Show one value.",
        context=QueryContext(relations=()),
    )

    result = _plan_query(
        StubQueryPlanner(),
        request,
    )

    assert result == QueryPlan(
        question="Show one value.",
        sql="SELECT 1 AS value",
    )
