import pytest

from verisight.execution.context import QueryContext
from verisight.execution.exceptions import QueryPlanningError
from verisight.execution.gemini import GeminiGenerationError
from verisight.execution.generative_repair import GenerativeQueryRepairer
from verisight.execution.planning import QueryPlan
from verisight.execution.prompt_budget import PromptBudgetExceededError
from verisight.execution.repair import QueryRepairRequest


class StubTextGenerationClient:
    """Deterministic text-generation client for repair tests."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def _make_request() -> QueryRepairRequest:
    return QueryRepairRequest(
        question="Compare values across groups.",
        failed_sql="SELECT missing_column FROM observations",
        error='Binder Error: Referenced column "missing_column" not found',
        context=QueryContext(relations=()),
    )


def test_generative_repairer_builds_query_plan() -> None:
    client = StubTextGenerationClient(
        "SELECT group_name, AVG(value) FROM observations GROUP BY group_name"
    )
    repairer = GenerativeQueryRepairer(client)

    plan = repairer.repair(_make_request())

    assert plan == QueryPlan(
        question="Compare values across groups.",
        sql="SELECT group_name, AVG(value) FROM observations GROUP BY group_name",
    )


def test_generative_repairer_builds_prompt_from_request() -> None:
    client = StubTextGenerationClient("SELECT 1")
    repairer = GenerativeQueryRepairer(client)

    repairer.repair(_make_request())

    assert len(client.prompts) == 1

    prompt = client.prompts[0]

    assert "ORIGINAL QUESTION:\nCompare values across groups." in prompt
    assert "FAILED SQL:\nSELECT missing_column FROM observations" in prompt
    assert 'Referenced column "missing_column"' in prompt


def test_generative_repairer_parses_fenced_sql_response() -> None:
    client = StubTextGenerationClient(
        "```sql\n"
        "SELECT group_name, AVG(value)\n"
        "FROM observations\n"
        "GROUP BY group_name\n"
        "```"
    )
    repairer = GenerativeQueryRepairer(client)

    plan = repairer.repair(_make_request())

    assert plan.sql == (
        "SELECT group_name, AVG(value)\nFROM observations\nGROUP BY group_name"
    )


def test_generative_repairer_does_not_call_llm_for_oversized_prompt() -> None:
    client = StubTextGenerationClient("SELECT 1")
    repairer = GenerativeQueryRepairer(client)

    original = _make_request()

    request = QueryRepairRequest(
        question=original.question,
        failed_sql="SELECT " + "X" * 60_000,
        error=original.error,
        context=original.context,
    )

    with pytest.raises(PromptBudgetExceededError):
        repairer.repair(request)

    assert client.prompts == []


def test_generative_repairer_translates_provider_failure() -> None:
    class FailingClient:
        def generate(self, prompt: str) -> str:
            raise GeminiGenerationError("Provider unavailable.")

    repairer = GenerativeQueryRepairer(FailingClient())

    with pytest.raises(
        QueryPlanningError,
        match="Query repairer text generation failed.",
    ) as exc_info:
        repairer.repair(_make_request())

    assert isinstance(exc_info.value.__cause__, GeminiGenerationError)


def test_generative_repairer_preserves_unexpected_errors() -> None:
    class FailingClient:
        def generate(self, prompt: str) -> str:
            raise RuntimeError("Unexpected programming error.")

    repairer = GenerativeQueryRepairer(FailingClient())

    with pytest.raises(
        RuntimeError,
        match="Unexpected programming error.",
    ):
        repairer.repair(_make_request())
