"""Parsing for autonomous investigation responses."""

import json
from typing import Any

from verisight.execution.decisions import (
    InvestigationAction,
    InvestigationDecision,
)
from verisight.execution.exceptions import InvestigationError


def _reject_duplicate_fields(
    pairs: list[tuple[str, Any]],
) -> dict[str, Any]:
    """Build a JSON object without allowing duplicate field names."""

    payload: dict[str, Any] = {}

    for key, value in pairs:
        if key in payload:
            raise ValueError("Duplicate JSON field.")
        payload[key] = value

    return payload


def _reject_nonstandard_constant(value: str) -> None:
    """Reject NaN and Infinity, which are not valid JSON constants."""

    raise ValueError(f"Nonstandard JSON constant: {value}")


class InvestigationResponseParser:
    """Parse model responses into validated investigation decisions."""

    def parse(self, response: str) -> InvestigationDecision:
        """Parse one investigation decision from a model response."""

        normalized = response.strip()

        if not normalized:
            raise InvestigationError("Investigator returned an empty response.")

        try:
            payload = json.loads(
                normalized,
                object_pairs_hook=_reject_duplicate_fields,
                parse_constant=_reject_nonstandard_constant,
            )
        except (json.JSONDecodeError, ValueError) as exc:
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
