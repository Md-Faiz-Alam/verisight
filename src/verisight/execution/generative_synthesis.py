"""Generative implementation of evidence-grounded investigation synthesis."""

from verisight.execution.exceptions import InvestigationError
from verisight.execution.gemini import GeminiGenerationError
from verisight.execution.generation import TextGenerationClient
from verisight.execution.investigation import InvestigationState
from verisight.execution.synthesis_prompting import (
    InvestigationSynthesisPromptBuilder,
)


class GenerativeInvestigationSynthesizer:
    """Synthesize investigation conclusions using a text-generation client."""

    def __init__(self, client: TextGenerationClient) -> None:
        """Initialize the generative investigation synthesizer."""

        self._client = client
        self._prompt_builder = InvestigationSynthesisPromptBuilder()

    def synthesize(self, state: InvestigationState) -> str:
        """Generate an evidence-grounded conclusion."""

        prompt = self._prompt_builder.build(state)

        try:
            response = self._client.generate(prompt)
        except GeminiGenerationError as exc:
            raise InvestigationError(
                "Investigation synthesis text generation failed."
            ) from exc

        conclusion = response.strip()

        if not conclusion:
            raise InvestigationError(
                "Investigation synthesizer returned an empty conclusion."
            )

        return conclusion
