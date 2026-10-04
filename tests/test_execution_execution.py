from verisight.execution.execution import QueryExecution
from verisight.execution.models import QueryResult
from verisight.execution.planning import QueryPlan


def test_query_execution_preserves_successful_plan_and_result() -> None:
    plan = QueryPlan(
        question="What is the total amount?",
        sql="SELECT SUM(amount) AS total_amount FROM orders",
    )

    result = QueryResult(
        columns=("total_amount",),
        rows=((60.0,),),
    )

    execution = QueryExecution(
        plan=plan,
        result=result,
    )

    assert execution.plan is plan
    assert execution.result is result
    assert execution.plan.question == "What is the total amount?"
    assert execution.plan.sql == ("SELECT SUM(amount) AS total_amount FROM orders")
    assert execution.result.rows == ((60.0,),)
