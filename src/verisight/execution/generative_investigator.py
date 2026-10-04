"""Generative implementation of autonomous analytical investigation."""

from verisight.execution.decisions import InvestigationDecision
from verisight.execution.generation import TextGenerationClient
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_parsing import (
    InvestigationResponseParser,
)
from verisight.execution.investigation_prompting import (
    InvestigationPromptBuilder,
)


class GenerativeInvestigator:
    """Decide investigation actions using a text-generation client."""

    def __init__(self, client: TextGenerationClient) -> None:
        """Initialize the generative investigator."""

        self._client = client
        self._prompt_builder = InvestigationPromptBuilder()
        self._response_parser = InvestigationResponseParser()

    def decide(
        self,
        state: InvestigationState,
    ) -> InvestigationDecision:
        """Generate and parse the next investigation decision."""

        prompt = self._prompt_builder.build(state)
        response = self._client.generate(prompt)

        return self._response_parser.parse(response)
