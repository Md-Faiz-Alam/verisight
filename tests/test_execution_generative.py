"""Tests for the generative analytical query planner."""

import pytest

from verisight.error_reporting import ErrorCode
from verisight.execution.context import QueryContext
from verisight.execution.exceptions import QueryPlanningError
from verisight.execution.gemini import GeminiGenerationError, GeminiTransientError
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.planning import QueryPlan, QueryRequest
from verisight.execution.prompt_budget import PromptBudgetExceededError
from verisight.public_api import run_public_operation


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


def test_generative_planner_preserves_transient_provider_failure() -> None:
    error = GeminiTransientError("Gemini is temporarily unavailable.")

    class FailingClient:
        def generate(self, prompt: str) -> str:
            raise error

    planner = GenerativeQueryPlanner(FailingClient())

    request = QueryRequest(
        question="Count records.",
        context=QueryContext(relations=()),
    )

    with pytest.raises(GeminiTransientError) as exc_info:
        planner.plan(request)

    assert exc_info.value is error
    assert exc_info.value.__cause__ is None


def test_generative_planner_reports_transient_failure_as_provider_unavailable() -> None:
    class FailingClient:
        def generate(self, prompt: str) -> str:
            raise GeminiTransientError("Sensitive Gemini provider details.")

    planner = GenerativeQueryPlanner(FailingClient())

    request = QueryRequest(
        question="Count records.",
        context=QueryContext(relations=()),
    )

    result = run_public_operation(lambda: planner.plan(request))

    assert result.succeeded is False
    assert result.value is None
    assert result.error is not None
    assert result.error.code is ErrorCode.PROVIDER_UNAVAILABLE
    assert result.error.message == "The AI provider is temporarily unavailable."
    assert "Sensitive Gemini provider details." not in repr(result)
