"""Parsing for autonomous investigation responses."""

import json
from typing import Any

from verisight.execution.decisions import (
    InvestigationAction,
    InvestigationDecision,
)
from verisight.execution.exceptions import InvestigationError


class InvestigationResponseParser:
    """Parse model responses into validated investigation decisions."""

    def parse(self, response: str) -> InvestigationDecision:
        """Parse one investigation decision from a model response."""

        normalized = response.strip()

        if not normalized:
            raise InvestigationError("Investigator returned an empty response.")

        try:
            payload = json.loads(normalized)
        except json.JSONDecodeError as exc:
            raise InvestigationError("Investigator returned invalid JSON.") from exc

        if not isinstance(payload, dict):
            raise InvestigationError("Investigator response must be a JSON object.")

        return self._parse_payload(payload)

    @staticmethod
    def _parse_payload(
        payload: dict[str, Any],
    ) -> InvestigationDecision:
        """Parse and validate an investigation decision payload."""

        expected_fields = {
            "action",
            "reasoning",
            "question",
        }

        if set(payload) != expected_fields:
            raise InvestigationError(
                "Investigator response must contain exactly "
                "action, reasoning, and question."
            )

        action_value = payload["action"]
        reasoning = payload["reasoning"]
        question = payload["question"]

        if not isinstance(action_value, str):
            raise InvestigationError("Investigator action must be a string.")

        try:
            action = InvestigationAction(action_value)
        except ValueError as exc:
            raise InvestigationError(
                "Investigator returned an unsupported action."
            ) from exc

        if not isinstance(reasoning, str):
            raise InvestigationError("Investigator reasoning must be a string.")

        if question is not None and not isinstance(question, str):
            raise InvestigationError("Investigator question must be a string or null.")

        try:
            return InvestigationDecision(
                action=action,
                reasoning=reasoning,
                question=question,
            )
        except ValueError as exc:
            raise InvestigationError(
                f"Investigator returned an invalid decision: {exc}"
            ) from exc
