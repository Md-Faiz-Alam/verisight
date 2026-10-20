"""Generative implementation of evidence-grounded investigation synthesis."""

import json

from verisight.evidence import evidence_to_jsonable, freeze_evidence
from verisight.execution.exceptions import InvestigationError
from verisight.execution.gemini import GeminiGenerationError, GeminiTransientError
from verisight.execution.generation import TextGenerationClient
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_formatting import (
    InvestigationStateFormatter,
)
from verisight.execution.synthesis_prompting import (
    InvestigationSynthesisPromptBuilder,
)


class GenerativeInvestigationSynthesizer:
    """Synthesize investigation conclusions using a text-generation client."""

    def __init__(self, client: TextGenerationClient) -> None:
        """Initialize the generative investigation synthesizer."""

        self._client = client

    def synthesize(self, state: InvestigationState) -> str:
        """Generate a conclusion only from fully represented evidence."""

        formatter = self._full_evidence_formatter(state)

        # Use a fresh builder so the formatter is not shared across
        # concurrent calls or successive investigations.
        builder = InvestigationSynthesisPromptBuilder(state_formatter=formatter)

        prompt = builder.build(state)

        try:
            response = self._client.generate(prompt)
        except GeminiTransientError:
            raise
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

    @staticmethod
    def _full_evidence_formatter(
        state: InvestigationState,
    ) -> InvestigationStateFormatter:
        """Build a formatter whose limits cannot truncate supplied evidence."""

        insights = state.analysis.insights
        issues = state.analysis.analysis.issues
        attempts = state.failed_attempts

        messages = [insight.message for insight in insights] + [
            issue.message for issue in issues
        ]

        evidence_values = [insight.evidence for insight in insights] + [
            issue.evidence for issue in issues
        ]

        max_evidence_chars = max(
            (
                len(
                    json.dumps(
                        evidence_to_jsonable(freeze_evidence(value)),
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                for value in evidence_values
            ),
            default=1,
        )

        max_result_rows = max(
            (len(observation.result.rows) for observation in state.observations),
            default=1,
        )

        return InvestigationStateFormatter(
            max_result_rows=max(1, max_result_rows),
            max_observations=None,
            max_insights=max(1, len(insights)),
            max_quality_issues=max(1, len(issues)),
            max_failed_attempts=max(1, len(attempts)),
            max_message_chars=max(
                (len(message) for message in messages),
                default=1,
            ),
            max_evidence_chars=max(1, max_evidence_chars),
            max_error_chars=max(
                (len(attempt.message) for attempt in attempts),
                default=1,
            ),
        )
