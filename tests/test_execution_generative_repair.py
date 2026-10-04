from verisight.execution.context import QueryContext
from verisight.execution.generative_repair import GenerativeQueryRepairer
from verisight.execution.planning import QueryPlan
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
        sql=("SELECT group_name, AVG(value) FROM observations GROUP BY group_name"),
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
