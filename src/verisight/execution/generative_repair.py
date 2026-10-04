"""Generative implementation of analytical query repair."""

from verisight.execution.generation import TextGenerationClient
from verisight.execution.parsing import QueryResponseParser
from verisight.execution.planning import QueryPlan
from verisight.execution.repair import QueryRepairRequest
from verisight.execution.repair_prompting import QueryRepairPromptBuilder


class GenerativeQueryRepairer:
    """Repair analytical SQL using a text-generation client."""

    def __init__(self, client: TextGenerationClient) -> None:
        """Initialize the generative query repairer."""

        self._client = client
        self._prompt_builder = QueryRepairPromptBuilder()
        self._response_parser = QueryResponseParser()

    def repair(self, request: QueryRepairRequest) -> QueryPlan:
        """Generate and parse a replacement analytical SQL query."""

        prompt = self._prompt_builder.build(request)
        response = self._client.generate(prompt)
        sql = self._response_parser.parse(response)

        return QueryPlan(
            question=request.question,
            sql=sql,
        )
