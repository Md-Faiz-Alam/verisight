from verisight.execution.context import QueryContext
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.planning import QueryPlan, QueryRequest


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

    assert plan.sql == ("SELECT COUNT(*) AS order_count\nFROM orders")
