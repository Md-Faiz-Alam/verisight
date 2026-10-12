"""Tests for the Gemini text-generation adapter."""

from collections.abc import Sequence
from unittest.mock import patch

import httpx
import pytest
from google.genai import errors

from verisight.exceptions import VeriSightError
from verisight.execution.gemini import (
    GeminiGenerationError,
    GeminiTextGenerationClient,
    _is_retryable,
)


class StubGeminiResponse:
    """Deterministic Gemini response for adapter tests."""

    def __init__(self, text: str | None) -> None:
        self.text = text


class StubGeminiModels:
    """Deterministic Gemini models API for adapter tests."""

    def __init__(self, response_text: str | None) -> None:
        self._response_text = response_text
        self.calls: list[tuple[str, str]] = []

    def generate_content(
        self,
        *,
        model: str,
        contents: str,
    ) -> StubGeminiResponse:
        self.calls.append((model, contents))
        return StubGeminiResponse(self._response_text)


class StubGeminiClient:
    """Deterministic Gemini client for adapter tests."""

    def __init__(self, response_text: str | None) -> None:
        self._models = StubGeminiModels(response_text)

    @property
    def models(self) -> StubGeminiModels:
        return self._models


class FailingGeminiModels:
    """Simulate a Gemini SDK request failure."""

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def generate_content(
        self,
        *,
        model: str,
        contents: str,
    ) -> StubGeminiResponse:
        self.calls.append((model, contents))
        raise self.error


class FailingGeminiClient:
    """Expose a failing Gemini models API."""

    def __init__(self, error: Exception) -> None:
        self._models = FailingGeminiModels(error)

    @property
    def models(self) -> FailingGeminiModels:
        return self._models


class BrokenGeminiResponse:
    """Simulate an SDK response with inaccessible text."""

    @property
    def text(self) -> str | None:
        raise ValueError("Response text is unavailable.")


class BrokenResponseGeminiModels:
    """Return a response whose text property fails."""

    def generate_content(
        self,
        *,
        model: str,
        contents: str,
    ) -> BrokenGeminiResponse:
        return BrokenGeminiResponse()


class BrokenResponseGeminiClient:
    """Expose an SDK response extraction failure."""

    @property
    def models(self) -> BrokenResponseGeminiModels:
        return BrokenResponseGeminiModels()


class SequencedGeminiModels:
    """Return configured successes or failures in sequence."""

    def __init__(
        self,
        outcomes: Sequence[Exception | str],
    ) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[tuple[str, str]] = []

    def generate_content(
        self,
        *,
        model: str,
        contents: str,
    ) -> StubGeminiResponse:
        self.calls.append((model, contents))

        outcome = self.outcomes.pop(0)

        if isinstance(outcome, Exception):
            raise outcome

        return StubGeminiResponse(outcome)


class SequencedGeminiClient:
    """Expose a deterministic sequence of provider outcomes."""

    def __init__(
        self,
        outcomes: Sequence[Exception | str],
    ) -> None:
        self._models = SequencedGeminiModels(outcomes)

    @property
    def models(self) -> SequencedGeminiModels:
        return self._models


def test_generates_text_with_configured_model() -> None:
    sdk_client = StubGeminiClient("SELECT COUNT(*) FROM orders")

    client = GeminiTextGenerationClient(
        api_key="test-api-key",
        model="test-model",
        client=sdk_client,
    )

    result = client.generate("Generate SQL.")

    assert result == "SELECT COUNT(*) FROM orders"
    assert sdk_client.models.calls == [("test-model", "Generate SQL.")]


@pytest.mark.parametrize("api_key", ["", " ", "\n\t"])
def test_rejects_empty_api_key(api_key: str) -> None:
    with pytest.raises(
        ValueError,
        match="Gemini API key must not be empty.",
    ):
        GeminiTextGenerationClient(
            api_key=api_key,
            model="test-model",
            client=StubGeminiClient("SELECT 1"),
        )


@pytest.mark.parametrize("model", ["", " ", "\n\t"])
def test_rejects_empty_model(model: str) -> None:
    with pytest.raises(
        ValueError,
        match="Gemini model must not be empty.",
    ):
        GeminiTextGenerationClient(
            api_key="test-api-key",
            model=model,
            client=StubGeminiClient("SELECT 1"),
        )


@pytest.mark.parametrize("prompt", ["", " ", "\n\t"])
def test_rejects_empty_prompt(prompt: str) -> None:
    client = GeminiTextGenerationClient(
        api_key="test-api-key",
        model="test-model",
        client=StubGeminiClient("SELECT 1"),
    )

    with pytest.raises(
        ValueError,
        match="Generation prompt must not be empty.",
    ):
        client.generate(prompt)


@pytest.mark.parametrize("response_text", [None, "", " ", "\n\t"])
def test_rejects_empty_gemini_response(
    response_text: str | None,
) -> None:
    client = GeminiTextGenerationClient(
        api_key="test-api-key",
        model="test-model",
        client=StubGeminiClient(response_text),
    )

    with pytest.raises(
        GeminiGenerationError,
        match="Gemini returned an empty text response.",
    ):
        client.generate("Generate SQL.")


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("Provider unavailable."),
        TimeoutError("Request timed out."),
        ConnectionError("Connection lost."),
    ],
)
def test_wraps_provider_failures(error: Exception) -> None:
    sdk_client = FailingGeminiClient(error)

    client = GeminiTextGenerationClient(
        api_key="test-api-key",
        model="test-model",
        client=sdk_client,
        max_retries=0,
    )

    with pytest.raises(
        GeminiGenerationError,
        match="Gemini text generation failed.",
    ) as exc_info:
        client.generate("Generate SQL.")

    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert sdk_client.models.calls == [("test-model", "Generate SQL.")]


def test_wraps_response_text_extraction_failure() -> None:
    client = GeminiTextGenerationClient(
        api_key="test-api-key",
        model="test-model",
        client=BrokenResponseGeminiClient(),
    )

    with pytest.raises(
        GeminiGenerationError,
        match="Gemini returned an unusable text response.",
    ) as exc_info:
        client.generate("Generate SQL.")

    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_generation_error_is_application_error() -> None:
    assert issubclass(GeminiGenerationError, VeriSightError)


def test_retries_transient_failure_then_succeeds() -> None:
    sdk_client = SequencedGeminiClient(
        [
            TimeoutError("Temporary timeout."),
            "SELECT 1",
        ]
    )
    delays: list[float] = []

    client = GeminiTextGenerationClient(
        api_key="test-api-key",
        model="test-model",
        client=sdk_client,
        sleep=delays.append,
    )

    result = client.generate("Generate SQL.")

    assert result == "SELECT 1"
    assert sdk_client.models.calls == [
        ("test-model", "Generate SQL."),
        ("test-model", "Generate SQL."),
    ]
    assert delays == [1.0]


def test_retry_limit_is_enforced() -> None:
    errors_sequence = [
        ConnectionError("First failure."),
        ConnectionError("Second failure."),
        ConnectionError("Third failure."),
    ]

    sdk_client = SequencedGeminiClient(errors_sequence)
    delays: list[float] = []

    client = GeminiTextGenerationClient(
        api_key="test-api-key",
        model="test-model",
        client=sdk_client,
        max_retries=2,
        sleep=delays.append,
    )

    with pytest.raises(
        GeminiGenerationError,
        match="Gemini text generation failed.",
    ) as exc_info:
        client.generate("Generate SQL.")

    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert len(sdk_client.models.calls) == 3
    assert delays == [1.0, 2.0]


def test_permanent_failure_is_not_retried() -> None:
    sdk_client = SequencedGeminiClient([RuntimeError("Permanent failure.")])
    delays: list[float] = []

    client = GeminiTextGenerationClient(
        api_key="test-api-key",
        model="test-model",
        client=sdk_client,
        sleep=delays.append,
    )

    with pytest.raises(GeminiGenerationError):
        client.generate("Generate SQL.")

    assert len(sdk_client.models.calls) == 1
    assert delays == []


def test_zero_retries_attempts_once() -> None:
    sdk_client = SequencedGeminiClient([TimeoutError("Request timed out.")])

    client = GeminiTextGenerationClient(
        api_key="test-api-key",
        model="test-model",
        client=sdk_client,
        max_retries=0,
    )

    with pytest.raises(GeminiGenerationError):
        client.generate("Generate SQL.")

    assert len(sdk_client.models.calls) == 1


def test_retry_delay_is_capped() -> None:
    sdk_client = SequencedGeminiClient(
        [
            TimeoutError("Transient failure."),
            TimeoutError("Transient failure."),
            TimeoutError("Transient failure."),
            TimeoutError("Transient failure."),
            TimeoutError("Transient failure."),
            "SELECT 1",
        ]
    )
    delays: list[float] = []

    client = GeminiTextGenerationClient(
        api_key="test-api-key",
        model="test-model",
        client=sdk_client,
        max_retries=5,
        retry_base_delay_seconds=4.0,
        sleep=delays.append,
    )

    assert client.generate("Generate SQL.") == "SELECT 1"
    assert len(sdk_client.models.calls) == 6
    assert delays == [4.0, 8.0, 8.0, 8.0, 8.0]


@pytest.mark.parametrize(
    "timeout",
    [
        0.0,
        -1.0,
        float("inf"),
        float("nan"),
    ],
)
def test_rejects_invalid_request_timeout(timeout: float) -> None:
    with pytest.raises(ValueError):
        GeminiTextGenerationClient(
            api_key="test-api-key",
            model="test-model",
            client=StubGeminiClient("SELECT 1"),
            request_timeout_seconds=timeout,
        )


@pytest.mark.parametrize(
    "max_retries",
    [-1, 6, True],
)
def test_rejects_invalid_max_retries(max_retries: int) -> None:
    with pytest.raises(ValueError):
        GeminiTextGenerationClient(
            api_key="test-api-key",
            model="test-model",
            client=StubGeminiClient("SELECT 1"),
            max_retries=max_retries,
        )


@pytest.mark.parametrize(
    "delay",
    [
        0.0,
        -1.0,
        float("inf"),
        float("nan"),
    ],
)
def test_rejects_invalid_retry_delay(delay: float) -> None:
    with pytest.raises(ValueError):
        GeminiTextGenerationClient(
            api_key="test-api-key",
            model="test-model",
            client=StubGeminiClient("SELECT 1"),
            retry_base_delay_seconds=delay,
        )


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (400, False),
        (401, False),
        (403, False),
        (404, False),
        (429, True),
        (500, True),
        (503, True),
        (599, True),
    ],
)
def test_classifies_provider_status_codes(
    status_code: int,
    expected: bool,
) -> None:
    error = errors.APIError(
        code=status_code,
        response_json={
            "error": {
                "message": "Provider failure",
            }
        },
    )

    assert _is_retryable(error) is expected


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("Request timed out."),
        ConnectionError("Connection lost."),
        httpx.ConnectTimeout("Connection timed out."),
        httpx.ReadTimeout("Read timed out."),
        httpx.ConnectError("Connection failed."),
        httpx.ReadError("Read failed."),
    ],
)
def test_classifies_transport_failures_as_retryable(
    error: Exception,
) -> None:
    assert _is_retryable(error) is True


def test_classifies_unexpected_failure_as_non_retryable() -> None:
    assert _is_retryable(RuntimeError("Unexpected failure.")) is False


def test_configures_sdk_timeout_and_single_attempt() -> None:
    with patch("verisight.execution.gemini.genai.Client") as factory:
        GeminiTextGenerationClient(
            api_key="test-api-key",
            model="test-model",
            request_timeout_seconds=12.5,
        )

    factory.assert_called_once()

    assert factory.call_args.kwargs["api_key"] == "test-api-key"

    options = factory.call_args.kwargs["http_options"]

    assert options.timeout == 12_500
    assert options.retry_options is not None
    assert options.retry_options.attempts == 1


def test_minimum_sdk_timeout_is_one_millisecond() -> None:
    with patch("verisight.execution.gemini.genai.Client") as factory:
        GeminiTextGenerationClient(
            api_key="test-api-key",
            model="test-model",
            request_timeout_seconds=0.0001,
        )

    options = factory.call_args.kwargs["http_options"]

    assert options.timeout == 1


def test_empty_response_is_not_retried() -> None:
    sdk_client = SequencedGeminiClient(["", "SELECT 1"])
    delays: list[float] = []

    client = GeminiTextGenerationClient(
        api_key="test-api-key",
        model="test-model",
        client=sdk_client,
        sleep=delays.append,
    )

    with pytest.raises(
        GeminiGenerationError,
        match="Gemini returned an empty text response.",
    ):
        client.generate("Generate SQL.")

    assert len(sdk_client.models.calls) == 1
    assert delays == []


def test_unusable_response_is_not_retried() -> None:
    client = GeminiTextGenerationClient(
        api_key="test-api-key",
        model="test-model",
        client=BrokenResponseGeminiClient(),
    )

    with pytest.raises(
        GeminiGenerationError,
        match="Gemini returned an unusable text response.",
    ):
        client.generate("Generate SQL.")


def test_provider_error_does_not_expose_api_key() -> None:
    secret = "synthetic-gemini-secret-123456"

    client = GeminiTextGenerationClient(
        api_key=secret,
        model="test-model",
        client=FailingGeminiClient(
            RuntimeError(f"Provider rejected API key: {secret}")
        ),
        max_retries=0,
    )

    with pytest.raises(GeminiGenerationError) as exc_info:
        client.generate("Generate SQL.")

    error = exc_info.value

    assert secret not in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None


def test_response_extraction_failure_has_no_raw_context() -> None:
    client = GeminiTextGenerationClient(
        api_key="synthetic-test-key",
        model="test-model",
        client=BrokenResponseGeminiClient(),
    )

    with pytest.raises(GeminiGenerationError) as exc_info:
        client.generate("Generate SQL.")

    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
