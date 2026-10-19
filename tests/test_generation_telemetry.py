"""Offline generation telemetry checks; no provider calls or private payloads."""

import asyncio
import json
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors
from scripts.live_evaluation import CASES, run_case

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.config import Settings
from verisight.execution.gemini import (
    GeminiGenerationError,
    GeminiTextGenerationClient,
)
from verisight.execution.generation_telemetry import (
    capture_generation_calls,
    track_generation_call,
)
from verisight.execution.investigation_result import InvestigationResult
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile


@pytest.mark.parametrize(
    "schema,stage",
    [
        (None, "text_generation"),
        ({"properties": {"action": {"type": "string"}}}, "investigator"),
        ({"properties": {"claims": {"type": "array"}}}, "structured_synthesis"),
    ],
)
def test_success_records_actual_retry_count_and_safe_elapsed_time(
    schema: dict[str, object] | None,
    stage: str,
) -> None:
    sdk = MagicMock()
    sdk.models.generate_content.side_effect = [
        errors.APIError(503, {"error": {"message": "private-error"}}),
        MagicMock(text="private-response"),
    ]
    sleep = MagicMock()
    client = GeminiTextGenerationClient(
        api_key="private-key",
        model="test-model",
        client=sdk,
        max_retries=1,
        sleep=sleep,
        response_json_schema=schema,
    )

    with (
        patch(
            "verisight.execution.generation_telemetry.perf_counter",
            side_effect=[10, 13.25],
        ),
        capture_generation_calls() as calls,
    ):
        assert client.generate("private-prompt") == "private-response"

    assert [asdict(call) for call in calls] == [
        {
            "stage": stage,
            "call_number": 1,
            "attempts": 2,
            "elapsed_seconds": 3.25,
            "returned_text": True,
        }
    ]
    sleep.assert_called_once_with(1.0)
    assert sdk.models.generate_content.call_count == 2
    assert "private" not in json.dumps([asdict(call) for call in calls])


@pytest.mark.parametrize("status,attempts", [(400, 1), (429, 2), (503, 2)])
def test_failed_call_records_attempts_without_raw_errors(
    status: int, attempts: int
) -> None:
    sdk = MagicMock()
    sdk.models.generate_content.side_effect = errors.APIError(
        status, {"error": {"message": "private-error"}}
    )
    client = GeminiTextGenerationClient(
        api_key="private-key",
        model="test-model",
        client=sdk,
        max_retries=1,
        sleep=lambda _: None,
    )

    with (
        capture_generation_calls() as calls,
        pytest.raises(GeminiGenerationError) as caught,
    ):
        client.generate("private-prompt")

    assert len(calls) == 1
    assert calls[0].attempts == attempts
    assert calls[0].returned_text is False
    assert calls[0].elapsed_seconds >= 0
    assert "private" not in json.dumps(asdict(calls[0]))
    assert caught.value.__context__ is None


def test_call_numbers_and_empty_text_failures_remain_visible() -> None:
    sdk = MagicMock()
    sdk.models.generate_content.side_effect = [
        MagicMock(text="ok"),
        MagicMock(text=None),
    ]
    client = GeminiTextGenerationClient(api_key="synthetic", model="test", client=sdk)

    with capture_generation_calls() as calls:
        assert client.generate("First") == "ok"
        with pytest.raises(GeminiGenerationError):
            client.generate("Second")

    assert [call.call_number for call in calls] == [1, 2]
    assert [call.attempts for call in calls] == [1, 1]
    assert [call.returned_text for call in calls] == [True, False]


def test_scopes_restore_after_failure_and_do_not_capture_outside_calls() -> None:
    with track_generation_call("text_generation", 99):
        pass
    with capture_generation_calls() as outer:
        with track_generation_call("investigator", 1) as call:
            call.attempts = 1
            call.returned_text = True
        with (
            pytest.raises(RuntimeError, match="synthetic"),
            capture_generation_calls() as inner,
            track_generation_call("structured_synthesis", 2),
        ):
            raise RuntimeError("synthetic")
        with track_generation_call("text_generation", 3):
            pass

    assert [item.call_number for item in outer] == [1, 3]
    assert [item.call_number for item in inner] == [2]
    assert inner[0].returned_text is False
    with track_generation_call("text_generation", 100):
        pass
    assert [item.call_number for item in outer] == [1, 3]


def test_async_contexts_keep_separate_capture_lists() -> None:
    async def collect(number: int) -> list[int]:
        with capture_generation_calls() as calls:
            await asyncio.sleep(0)
            with track_generation_call("text_generation", number):
                pass
        return [item.call_number for item in calls]

    async def run() -> list[list[int]]:
        return list(await asyncio.gather(collect(1), collect(2)))

    assert asyncio.run(run()) == [[1], [2]]


def test_rejected_empty_prompt_does_not_record_a_provider_call() -> None:
    sdk = MagicMock()
    client = GeminiTextGenerationClient(api_key="synthetic", model="test", client=sdk)
    with capture_generation_calls() as calls, pytest.raises(ValueError):
        client.generate("  ")
    assert calls == []
    sdk.models.generate_content.assert_not_called()


@pytest.mark.parametrize("failed", [False, True])
def test_evaluation_keeps_generation_calls_on_success_and_failure(failed: bool) -> None:
    sdk = MagicMock()
    if failed:
        sdk.models.generate_content.side_effect = errors.APIError(
            503, {"error": {"message": "private-error"}}
        )
    else:
        sdk.models.generate_content.return_value.text = "private-response"
    client = GeminiTextGenerationClient(
        api_key="private-key",
        model="test",
        client=sdk,
        max_retries=1,
        sleep=lambda _: None,
        response_json_schema={"properties": {"action": {"type": "string"}}},
    )
    analysis = AnalysisResultBuilder().build(
        DatasetAnalysis(
            schema=DatasetSchema(tables=()),
            profile=DatasetProfile(tables=()),
            issues=(),
        )
    )
    result = InvestigationResult(
        question="Synthetic question",
        conclusion="No evidence supplied.",
        analysis=analysis,
    )

    def investigate(*args: object, **kwargs: object) -> InvestigationResult:
        client.generate("private-prompt")
        return result

    with patch("scripts.live_evaluation.VeriSight") as app:
        app.return_value.investigate.side_effect = investigate
        report = run_case(CASES["finance"], Settings(allow_llm_data_disclosure=False))

    assert report["outcome"] == ("provider_error" if failed else "no_claims")
    serialized = json.dumps(report)
    calls = json.loads(serialized)["generation_calls"]
    assert len(calls) == 1
    assert calls[0]["stage"] == "investigator"
    assert calls[0]["attempts"] == (2 if failed else 1)
    assert calls[0]["returned_text"] is (not failed)
    assert "private" not in serialized
