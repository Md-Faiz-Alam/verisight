import pytest

from verisight.execution.context import QueryContext
from verisight.execution.exceptions import QueryPlanningError
from verisight.execution.gemini import GeminiGenerationError
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.planning import QueryPlan, QueryRequest
from verisight.execution.prompt_budget import PromptBudgetExceededError


class StubTextGenerationClient:
    """Deterministic text-generation client for planner tests."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def test_generative_planner_builds_query_plan() -> None:
    client = StubTextGenerationClient("SELECT COUNT(*) AS order_count FROM orders")
    planner = GenerativeQueryPlanner(client)

    request = QueryRequest(
        question="How many orders are there?",
        context=QueryContext(relations=()),
    )

    plan = planner.plan(request)

    assert plan == QueryPlan(
        question="How many orders are there?",
        sql="SELECT COUNT(*) AS order_count FROM orders",
    )


def test_generative_planner_builds_prompt_from_request() -> None:
    client = StubTextGenerationClient("SELECT 1 AS value")
    planner = GenerativeQueryPlanner(client)

    request = QueryRequest(
        question="Show one value.",
        context=QueryContext(relations=()),
    )

    planner.plan(request)

    assert len(client.prompts) == 1

    prompt = client.prompts[0]

    assert "You are an analytical SQL planner for VeriSight." in prompt
    assert "QUESTION:\nShow one value." in prompt


def test_generative_planner_parses_fenced_sql_response() -> None:
    client = StubTextGenerationClient(
        "```sql\nSELECT COUNT(*) AS order_count\nFROM orders\n```"
    )
    planner = GenerativeQueryPlanner(client)

    request = QueryRequest(
        question="How many orders are there?",
        context=QueryContext(relations=()),
    )

    plan = planner.plan(request)

    assert plan.sql == "SELECT COUNT(*) AS order_count\nFROM orders"


def test_generative_planner_does_not_call_llm_for_oversized_prompt() -> None:
    client = StubTextGenerationClient("SELECT 1")
    planner = GenerativeQueryPlanner(client)

    request = QueryRequest(
        question="X" * 60_000,
        context=QueryContext(relations=()),
    )

    with pytest.raises(PromptBudgetExceededError):
        planner.plan(request)

    assert client.prompts == []


def test_generative_planner_translates_provider_failure() -> None:
    class FailingClient:
        def generate(self, prompt: str) -> str:
            raise GeminiGenerationError("Provider unavailable.")

    planner = GenerativeQueryPlanner(FailingClient())

    request = QueryRequest(
        question="Count records.",
        context=QueryContext(relations=()),
    )

    with pytest.raises(
        QueryPlanningError,
        match="Query planner text generation failed.",
    ) as exc_info:
        planner.plan(request)

    assert isinstance(exc_info.value.__cause__, GeminiGenerationError)


def test_generative_planner_preserves_unexpected_errors() -> None:
    class FailingClient:
        def generate(self, prompt: str) -> str:
            raise RuntimeError("Unexpected programming error.")

    planner = GenerativeQueryPlanner(FailingClient())

    request = QueryRequest(
        question="Count records.",
        context=QueryContext(relations=()),
    )

    with pytest.raises(
        RuntimeError,
        match="Unexpected programming error.",
    ):
        planner.plan(request)
