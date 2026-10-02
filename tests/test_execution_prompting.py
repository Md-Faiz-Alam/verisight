from verisight.execution.context import (
    QueryColumn,
    QueryContext,
    QueryRelation,
)
from verisight.execution.planning import QueryRequest
from verisight.execution.prompting import QueryPromptBuilder
from verisight.ingestion.schema import LogicalType


def _make_request() -> QueryRequest:
    context = QueryContext(
        relations=(
            QueryRelation(
                name="Orders",
                relation_name="orders",
                row_count=3,
                columns=(
                    QueryColumn(
                        name="order_id",
                        physical_dtype="int64",
                        logical_type=LogicalType.INTEGER,
                        nullable=False,
                    ),
                    QueryColumn(
                        name="amount",
                        physical_dtype="float64",
                        logical_type=LogicalType.FLOAT,
                        nullable=False,
                    ),
                ),
            ),
        )
    )

    return QueryRequest(
        question="What is the total amount?",
        context=context,
    )


def test_builds_query_planning_prompt() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert "analytical SQL planner for VeriSight" in prompt
    assert "QUESTION:\nWhat is the total amount?" in prompt
    assert "RELATION orders" in prompt
    assert "DISPLAY NAME: Orders" in prompt
    assert "- order_id | integer | int64 | nullable=false" in prompt
    assert "- amount | float | float64 | nullable=false" in prompt


def test_prompt_requires_read_only_select_query() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert "exactly one read-only DuckDB SELECT query" in prompt
    assert "Return SQL only." in prompt
    assert "Do not modify data or database state." in prompt


def test_prompt_restricts_external_access() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert "Do not access external files" in prompt
    assert "PRAGMA" in prompt
    assert "ATTACH" in prompt
    assert "COPY" in prompt


def test_prompt_is_deterministic() -> None:
    builder = QueryPromptBuilder()
    request = _make_request()

    first_prompt = builder.build(request)
    second_prompt = builder.build(request)

    assert first_prompt == second_prompt


def test_builds_prompt_for_empty_context() -> None:
    request = QueryRequest(
        question="What data is available?",
        context=QueryContext(relations=()),
    )

    prompt = QueryPromptBuilder().build(request)

    assert "AVAILABLE DATA:\n\n\nQUESTION:" in prompt
    assert "QUESTION:\nWhat data is available?" in prompt
