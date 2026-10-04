from verisight.execution.context import QueryContext
from verisight.execution.planning import QueryPlan
from verisight.execution.repair import (
    QueryRepairer,
    QueryRepairRequest,
)


class StubQueryRepairer:
    """Simple implementation used to verify the repair contract."""

    def repair(self, request: QueryRepairRequest) -> QueryPlan:
        return QueryPlan(
            question=request.question,
            sql="SELECT 1",
        )


def _repair(
    repairer: QueryRepairer,
    request: QueryRepairRequest,
) -> QueryPlan:
    return repairer.repair(request)


def test_query_repair_request_preserves_failure_context() -> None:
    context = QueryContext(relations=())

    request = QueryRepairRequest(
        question="Compare assessment performance across courses.",
        failed_sql="SELECT missing_column FROM assessments",
        error='Binder Error: Referenced column "missing_column" not found',
        context=context,
    )

    assert request.question == "Compare assessment performance across courses."
    assert request.failed_sql == "SELECT missing_column FROM assessments"
    assert request.error == (
        'Binder Error: Referenced column "missing_column" not found'
    )
    assert request.context is context


def test_query_repairer_accepts_compatible_implementation() -> None:
    request = QueryRepairRequest(
        question="Compare values across groups.",
        failed_sql="SELECT missing_column FROM observations",
        error='Binder Error: Referenced column "missing_column" not found',
        context=QueryContext(relations=()),
    )

    plan = _repair(
        StubQueryRepairer(),
        request,
    )

    assert plan == QueryPlan(
        question="Compare values across groups.",
        sql="SELECT 1",
    )
