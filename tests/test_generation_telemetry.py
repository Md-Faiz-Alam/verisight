"""Offline generation telemetry checks; no provider calls or private payloads."""

import asyncio
import json
from dataclasses import asdict
from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors
from pydantic import SecretStr
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
            "model": "test-model",
            "temperature": None,
            "seed": None,
            "prompt_tokens": None,
            "output_tokens": None,
            "thinking_tokens": None,
            "total_tokens": None,
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


def test_model_sampling_and_token_counts_are_recorded() -> None:
    sdk = MagicMock()
    usage = MagicMock(
        prompt_token_count=1200,
        candidates_token_count=80,
        thoughts_token_count=None,
        total_token_count=1280,
    )
    sdk.models.generate_content.return_value = MagicMock(
        text="private-response", usage_metadata=usage
    )
    client = GeminiTextGenerationClient(
        api_key="private-key",
        model="test-model",
        client=sdk,
        temperature=0.5,
        seed=7,
    )

    with capture_generation_calls() as calls:
        client.generate("private-prompt")

    report = asdict(calls[0])
    assert {key: report[key] for key in ("model", "temperature", "seed")} == {
        "model": "test-model",
        "temperature": 0.5,
        "seed": 7,
    }
    assert (
        report["prompt_tokens"],
        report["output_tokens"],
        report["thinking_tokens"],
        report["total_tokens"],
    ) == (1200, 80, None, 1280)
    config = sdk.models.generate_content.call_args.kwargs["config"]
    assert (config.temperature, config.seed) == (0.5, 7)


@pytest.mark.parametrize(
    "response",
    [
        MagicMock(text="ok", usage_metadata=None),
        MagicMock(
            text="ok",
            usage_metadata=MagicMock(
                prompt_token_count=-1,
                candidates_token_count="5",
                thoughts_token_count=True,
                total_token_count=1.5,
            ),
        ),
    ],
)
def test_missing_or_invalid_token_counts_stay_unknown(response: MagicMock) -> None:
    sdk = MagicMock()
    sdk.models.generate_content.return_value = response
    client = GeminiTextGenerationClient(api_key="k", model="m", client=sdk)

    with capture_generation_calls() as calls:
        client.generate("prompt")

    report = calls[0]
    assert (report.temperature, report.seed) == (None, None)
    assert (
        report.prompt_tokens,
        report.output_tokens,
        report.thinking_tokens,
        report.total_tokens,
    ) == (None, None, None, None)


@pytest.mark.parametrize("temperature", [-0.1, 2.1])
def test_temperature_outside_the_provider_range_is_refused(
    temperature: float,
) -> None:
    with pytest.raises(ValueError, match="temperature"):
        GeminiTextGenerationClient(api_key="k", model="m", temperature=temperature)


def test_settings_pass_sampling_to_every_client() -> None:
    from verisight.execution.structured_synthesis import (
        StructuredInvestigationSynthesizer,
    )
    from verisight.service import VeriSight

    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        gemini_api_key=SecretStr("k"),
        allow_llm_data_disclosure=True,
        gemini_temperature=0.2,
        gemini_seed=11,
    )

    planner_client = VeriSight._build_generation_client(settings)
    synthesizer = StructuredInvestigationSynthesizer.from_settings(settings)

    assert planner_client is not None
    for client in (planner_client, synthesizer._client):
        assert isinstance(client, GeminiTextGenerationClient)
        assert (client._temperature, client._seed) == (0.2, 11)
