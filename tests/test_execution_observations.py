from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation


def test_query_observation_preserves_execution_provenance() -> None:
    result = QueryResult(
        columns=("customer", "total_amount"),
        rows=(
            ("Alice", 320.5),
            ("Bob", 150.0),
        ),
    )

    observation = QueryObservation(
        question="Which customers generated the most completed revenue?",
        sql=(
            "SELECT customer, SUM(amount) AS total_amount "
            "FROM orders "
            "WHERE status = 'completed' "
            "GROUP BY customer "
            "ORDER BY total_amount DESC"
        ),
        result=result,
    )

    assert observation.question == (
        "Which customers generated the most completed revenue?"
    )
    assert observation.sql == (
        "SELECT customer, SUM(amount) AS total_amount "
        "FROM orders "
        "WHERE status = 'completed' "
        "GROUP BY customer "
        "ORDER BY total_amount DESC"
    )
    assert observation.result is result
    assert observation.result.columns == (
        "customer",
        "total_amount",
    )
    assert observation.result.rows == (
        ("Alice", 320.5),
        ("Bob", 150.0),
    )
