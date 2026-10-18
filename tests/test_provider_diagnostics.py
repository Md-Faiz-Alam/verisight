"""Offline checks for safe provider diagnostics and evaluation reporting."""

import json
from dataclasses import asdict
from unittest.mock import MagicMock

import pytest
from google.genai import errors
from scripts.live_evaluation import failure_report

from verisight.execution.exceptions import InvestigationError
from verisight.execution.gemini import (
    GeminiGenerationError,
    GeminiTextGenerationClient,
    GeminiTransientError,
)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 429, 500, 503, 504])
def test_status_retryability_and_attempt_count_are_preserved(status: int) -> None:
    secret = "synthetic-private-key-and-prompt"
    sdk = MagicMock()
    sdk.models.generate_content.side_effect = errors.APIError(
        status, {"error": {"message": secret}}
    )
    delays: list[float] = []
    client = GeminiTextGenerationClient(
        api_key=secret,
        model="test-model",
        client=sdk,
        max_retries=1,
        sleep=delays.append,
        response_json_schema={
            "type": "object",
            "properties": {"action": {"type": "string"}},
        },
    )
    with pytest.raises(GeminiGenerationError) as caught:
        client.generate(secret)

    error = caught.value
    retryable = status == 429 or status >= 500
    assert isinstance(error, GeminiTransientError) is retryable
    assert error.diagnostics is not None
    assert asdict(error.diagnostics) == {
        "http_status": status,
        "retryable": retryable,
        "attempts": 2 if retryable else 1,
        "stage": "investigator",
        "call_number": 1,
    }
    assert sdk.models.generate_content.call_count == (2 if retryable else 1)
    assert delays == ([1.0] if retryable else [])
    assert error.__cause__ is None
    assert error.__context__ is None
    wrapped = InvestigationError("Safe application wrapper.")
    wrapped.__cause__ = error
    report = failure_report(wrapped)
    assert report == {
        "outcome": "provider_error",
        "diagnostics": asdict(error.diagnostics),
    }
    assert secret not in json.dumps(report)
    assert secret not in repr(vars(error))
    assert secret not in str(error)


@pytest.mark.parametrize(
    "schema,stage",
    [
        (None, "text_generation"),
        ({"type": "object"}, "text_generation"),
        ({"type": "object", "properties": {}}, "text_generation"),
        (
            {"type": "object", "properties": {"claims": {"type": "array"}}},
            "structured_synthesis",
        ),
    ],
)
def test_stage_inference_and_second_call_number(
    schema: dict[str, object] | None, stage: str
) -> None:
    sdk = MagicMock()
    response = MagicMock()
    response.text = "First response."
    sdk.models.generate_content.side_effect = [
        response,
        TimeoutError("private-timeout"),
    ]
    client = GeminiTextGenerationClient(
        api_key="synthetic",
        model="test-model",
        client=sdk,
        response_json_schema=schema,
        max_retries=0,
    )
    assert client.generate("First prompt.") == "First response."
    with pytest.raises(GeminiTransientError) as caught:
        client.generate("Second prompt.")
    details = caught.value.diagnostics
    assert details is not None
    assert details.http_status is None
    assert details.retryable is True
    assert details.attempts == 1
    assert details.stage == stage
    assert details.call_number == 2


def test_empty_response_has_safe_non_retryable_diagnostics() -> None:
    sdk = MagicMock()
    sdk.models.generate_content.return_value.text = None
    client = GeminiTextGenerationClient(
        api_key="synthetic", model="test-model", client=sdk
    )
    with pytest.raises(GeminiGenerationError) as caught:
        client.generate("Synthetic prompt.")
    details = caught.value.diagnostics
    assert details is not None
    assert details.http_status is None
    assert details.retryable is False
    assert details.attempts == 1
    assert caught.value.__context__ is None
