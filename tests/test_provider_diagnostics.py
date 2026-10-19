"""Offline checks for safe provider diagnostics and evaluation reporting."""

import json
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from google.genai import errors
from scripts.live_evaluation import failure_report, score_result

from verisight import VeriSight
from verisight.config import Settings
from verisight.execution.decisions import InvestigationAction, InvestigationDecision
from verisight.execution.exceptions import InvestigationError
from verisight.execution.gemini import (
    GeminiGenerationError,
    GeminiTextGenerationClient,
    GeminiTransientError,
    ProviderFailureDiagnostics,
)
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_result import (
    InvestigationStatus,
    SynthesisFailure,
    SynthesisFailureKind,
)
from verisight.execution.planning import QueryPlan, QueryRequest
from verisight.execution.structured_synthesis import StructuredInvestigationSynthesizer
from verisight.serialization import to_jsonable


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


class _Planner:
    def plan(self, request: QueryRequest) -> QueryPlan:
        return QueryPlan(
            request.question, "SELECT SUM(value) AS total FROM measurements"
        )


class _Investigator:
    def decide(self, state: InvestigationState) -> InvestigationDecision:
        if state.observations:
            return InvestigationDecision(
                InvestigationAction.FINISH, "Evidence collected."
            )
        return InvestigationDecision(
            InvestigationAction.INVESTIGATE, "Need evidence.", "What is the total?"
        )


@pytest.mark.parametrize("with_diagnostics", [False, True])
@pytest.mark.parametrize(
    "kind",
    [
        SynthesisFailureKind.SYNTHESIS_ERROR,
        SynthesisFailureKind.PROVIDER_ERROR,
        SynthesisFailureKind.PROVIDER_UNAVAILABLE,
    ],
)
def test_synthesis_failure_metadata_survives_investigation_and_evaluation(
    tmp_path: Path,
    kind: SynthesisFailureKind,
    with_diagnostics: bool,
) -> None:
    secret = "synthetic-private-response-and-provider-details"
    diagnostics = (
        ProviderFailureDiagnostics(
            http_status=(
                503 if kind is SynthesisFailureKind.PROVIDER_UNAVAILABLE else 400
            ),
            retryable=kind is SynthesisFailureKind.PROVIDER_UNAVAILABLE,
            attempts=2,
            stage="structured_synthesis",
            call_number=1,
        )
        if with_diagnostics
        else None
    )

    class Client:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, prompt: str) -> str:
            self.calls += 1
            if kind is SynthesisFailureKind.PROVIDER_UNAVAILABLE:
                raise GeminiTransientError(secret, diagnostics=diagnostics)
            if kind is SynthesisFailureKind.PROVIDER_ERROR:
                raise GeminiGenerationError(secret, diagnostics=diagnostics)
            return secret

    path = tmp_path / "measurements.csv"
    path.write_text("value\n10\n20\n", encoding="utf-8")
    client = Client()
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False),
        planner=_Planner(),
        investigator=_Investigator(),
        synthesizer=StructuredInvestigationSynthesizer(client),
    )

    result = app.investigate(path, "Find the total.", max_steps=1)

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observations[0].result.rows == ((30,),)
    assert result.synthesis_failure is not None
    assert result.synthesis_failure.kind is kind
    expected_diagnostics = (
        None if kind is SynthesisFailureKind.SYNTHESIS_ERROR else diagnostics
    )
    assert result.synthesis_failure.diagnostics == expected_diagnostics
    assert result.generated_claims == ()
    assert result.verified_claims == ()
    assert result.narrative_verified is False
    assert client.calls == (2 if kind is SynthesisFailureKind.SYNTHESIS_ERROR else 1)

    payload = json.loads(json.dumps(to_jsonable(result)))
    expected_failure = {
        "kind": kind.value,
        "diagnostics": (
            asdict(expected_diagnostics) if expected_diagnostics is not None else None
        ),
    }
    assert payload["synthesis_failure"] == expected_failure
    assert secret not in json.dumps(payload)
    report = score_result(result, "30")
    assert report["outcome"] == "incomplete"
    assert report["synthesis_failure"] == expected_failure
    assert secret not in json.dumps(report)

    with pytest.raises(ValueError, match="requires an incomplete investigation"):
        replace(result, status=InvestigationStatus.COMPLETE)


def test_synthesis_failure_follows_nested_provider_causes() -> None:
    provider = GeminiTransientError("private")
    middle = InvestigationError("private wrapper")
    middle.__cause__ = provider
    outer = InvestigationError("private outer wrapper")
    outer.__cause__ = middle

    failure = SynthesisFailure.from_exception(outer)

    assert failure.kind is SynthesisFailureKind.PROVIDER_UNAVAILABLE
    assert failure.diagnostics is None
    assert "private" not in repr(failure)


def test_synthesis_failure_handles_cyclic_nonprovider_causes() -> None:
    error = InvestigationError("private")
    cause = ValueError("private parser details")
    error.__cause__ = cause
    cause.__cause__ = error

    failure = SynthesisFailure.from_exception(error)

    assert failure == SynthesisFailure(SynthesisFailureKind.SYNTHESIS_ERROR)
    assert "private" not in json.dumps(to_jsonable(failure))
