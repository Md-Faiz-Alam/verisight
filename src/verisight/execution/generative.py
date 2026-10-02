"""Generative implementation of analytical query planning."""

from verisight.execution.generation import TextGenerationClient
from verisight.execution.parsing import QueryResponseParser
from verisight.execution.planning import QueryPlan, QueryRequest
from verisight.execution.prompting import QueryPromptBuilder


class GenerativeQueryPlanner:
    """Plan analytical SQL using a text-generation client."""

    def __init__(self, client: TextGenerationClient) -> None:
        """Initialize the planner with a text-generation client."""

        self._client = client
        self._prompt_builder = QueryPromptBuilder()
        self._response_parser = QueryResponseParser()

    def plan(self, request: QueryRequest) -> QueryPlan:
        """Generate and parse an analytical SQL query."""

        prompt = self._prompt_builder.build(request)
        response = self._client.generate(prompt)
        sql = self._response_parser.parse(response)

        return QueryPlan(
            question=request.question,
            sql=sql,
        )
