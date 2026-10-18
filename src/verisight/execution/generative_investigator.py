"""Generative implementation of autonomous analytical investigation."""

from verisight.execution.decisions import (
    InvestigationAction,
    InvestigationDecision,
)
from verisight.execution.exceptions import InvestigationError
from verisight.execution.gemini import (
    GeminiGenerationError,
    GeminiTransientError,
)
from verisight.execution.generation import TextGenerationClient
from verisight.execution.incomplete_evidence import (
    IncompleteEvidenceError,
)
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_compaction import (
    InvestigationCompaction,
)
from verisight.execution.investigation_parsing import (
    InvestigationResponseParser,
)
from verisight.execution.investigation_prompting import (
    InvestigationPromptBuilder,
)
from verisight.execution.prompt_budget import PromptBudgetExceededError


class GenerativeInvestigator:
    """Decide investigation actions using a text-generation client."""

    def __init__(self, client: TextGenerationClient) -> None:
        """Initialize the generative investigator."""

        self._client = client
        self._prompt_builder = InvestigationPromptBuilder()
        self._compaction = InvestigationCompaction()
        self._response_parser = InvestigationResponseParser()

    def decide(
        self,
        state: InvestigationState,
    ) -> InvestigationDecision:
        """Generate and parse the next investigation decision."""

        compacted = False

        try:
            prompt = self._prompt_builder.build(state)
        except PromptBudgetExceededError:
            prompt = self._compaction.investigator_prompt(state)
            compacted = True

        try:
            response = self._client.generate(prompt)
        except GeminiTransientError:
            raise
        except GeminiGenerationError as exc:
            raise InvestigationError("Investigator text generation failed.") from exc

        decision = self._response_parser.parse(response)

        if compacted and decision.action is InvestigationAction.FINISH:
            raise IncompleteEvidenceError(
                "The investigator requested completion using compacted "
                "evidence. The full investigation context was not "
                "available for its decision."
            )

        return decision
