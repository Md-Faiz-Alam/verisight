"""Tests for the Gemini text-generation adapter."""

import asyncio
from collections.abc import AsyncIterator, Sequence
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from google import genai
from google.genai import errors, types

from verisight.exceptions import VeriSightError
from verisight.execution.gemini import (
    GeminiGenerationError,
    GeminiTextGenerationClient,
    GeminiTransientError,
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
        config: types.GenerateContentConfig | None = None,
    ) -> StubGeminiResponse:
        self.calls.append((model, contents))
        return StubGeminiResponse(self._response_text)


class ConfiguredGeminiModels:
    """Record provider configuration passed for structured responses."""

    def __init__(self, response_text: str) -> None:
        self._response_text = response_text
        self.calls: list[tuple[str, str, types.GenerateContentConfig | None]] = []

    def generate_content(
        self,
        *,
        model: str,
        contents: str,
        config: types.GenerateContentConfig | None = None,
    ) -> StubGeminiResponse:
        self.calls.append((model, contents, config))
        return StubGeminiResponse(self._response_text)


class ConfiguredGeminiClient:
    """SDK stub exposing the structured-response configuration."""

    def __init__(self, response_text: str) -> None:
        self._models = ConfiguredGeminiModels(response_text)

    @property
    def models(self) -> ConfiguredGeminiModels:
        return self._models


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
        config: types.GenerateContentConfig | None = None,
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
        config: types.GenerateContentConfig | None = None,
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
        self.configs: list[types.GenerateContentConfig | None] = []

    def generate_content(
        self,
        *,
        model: str,
        contents: str,
        config: types.GenerateContentConfig | None = None,
    ) -> StubGeminiResponse:
        self.calls.append((model, contents))
        self.configs.append(config)

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


def make_api_error(status_code: int) -> errors.APIError:
    """Create a synthetic provider error without sensitive details."""

    return errors.APIError(
        code=status_code,
        response_json={
            "error": {
                "message": "Synthetic provider failure",
            }
        },
    )


def test_generates_text_with_configured_model() -> None:
    sdk_client = ConfiguredGeminiClient("SELECT COUNT(*) FROM orders")

    client = GeminiTextGenerationClient(
        api_key="test-api-key",
        model="test-model",
        client=sdk_client,
    )

    result = client.generate("Generate SQL.")

    assert result == "SELECT COUNT(*) FROM orders"
    assert len(sdk_client.models.calls) == 1
    model, prompt, config = sdk_client.models.calls[0]
    assert (model, prompt) == ("test-model", "Generate SQL.")
    assert config is not None
    assert config.automatic_function_calling is not None
    assert config.automatic_function_calling.disable is True
    assert config.tools is None
    assert config.response_mime_type is None
    assert config.response_json_schema is None


def test_requests_gemini_structured_json_when_schema_is_configured() -> None:
    schema: dict[str, object] = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
    }
    sdk_client = ConfiguredGeminiClient('{"answer":"ready"}')
    client = GeminiTextGenerationClient(
        api_key="test-api-key",
        model="test-model",
        client=sdk_client,
        response_json_schema=schema,
    )

    assert client.generate("Return structured JSON.") == '{"answer":"ready"}'
    assert len(sdk_client.models.calls) == 1
    model, prompt, config = sdk_client.models.calls[0]
    assert (model, prompt) == ("test-model", "Return structured JSON.")
    assert config is not None
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == schema
    assert config.automatic_function_calling is not None
    assert config.automatic_function_calling.disable is True
    assert config.tools is None


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
    ) as exc_info:
        client.generate("Generate SQL.")

    assert not isinstance(exc_info.value, GeminiTransientError)


@pytest.mark.parametrize(
    ("error", "expected_type", "expected_message"),
    [
        (
            RuntimeError("Provider unavailable."),
            GeminiGenerationError,
            "Gemini text generation failed.",
        ),
        (
            TimeoutError("Request timed out."),
            GeminiTransientError,
            "Gemini is temporarily unavailable.",
        ),
        (
            ConnectionError("Connection lost."),
            GeminiTransientError,
            "Gemini is temporarily unavailable.",
        ),
    ],
)
def test_wraps_provider_failures(
    error: Exception,
    expected_type: type[GeminiGenerationError],
    expected_message: str,
) -> None:
    sdk_client = FailingGeminiClient(error)

    client = GeminiTextGenerationClient(
        api_key="test-api-key",
        model="test-model",
        client=sdk_client,
        max_retries=0,
    )

    with pytest.raises(
        expected_type,
        match=expected_message,
    ) as exc_info:
        client.generate("Generate SQL.")

    assert type(exc_info.value) is expected_type
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

    assert type(exc_info.value) is GeminiGenerationError
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_generation_error_is_application_error() -> None:
    assert issubclass(GeminiGenerationError, VeriSightError)


def test_transient_error_preserves_generation_error_compatibility() -> None:
    assert issubclass(GeminiTransientError, GeminiGenerationError)
    assert issubclass(GeminiTransientError, VeriSightError)


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
        GeminiTransientError,
        match="Gemini is temporarily unavailable.",
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

    with pytest.raises(GeminiGenerationError) as exc_info:
        client.generate("Generate SQL.")

    assert type(exc_info.value) is GeminiGenerationError
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

    with pytest.raises(GeminiTransientError):
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
    error = make_api_error(status_code)

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


@pytest.mark.parametrize("status_code", [429, 500, 503, 599])
def test_retryable_api_error_becomes_transient_after_retries(
    status_code: int,
) -> None:
    sdk_client = FailingGeminiClient(make_api_error(status_code))
    delays: list[float] = []

    client = GeminiTextGenerationClient(
        api_key="test-api-key",
        model="test-model",
        client=sdk_client,
        max_retries=2,
        sleep=delays.append,
    )

    with pytest.raises(
        GeminiTransientError,
        match="Gemini is temporarily unavailable.",
    ) as exc_info:
        client.generate("Generate SQL.")

    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert len(sdk_client.models.calls) == 3
    assert delays == [1.0, 2.0]


@pytest.mark.parametrize("status_code", [400, 401, 403, 404])
def test_permanent_api_error_is_not_transient(
    status_code: int,
) -> None:
    sdk_client = FailingGeminiClient(make_api_error(status_code))
    delays: list[float] = []

    client = GeminiTextGenerationClient(
        api_key="test-api-key",
        model="test-model",
        client=sdk_client,
        sleep=delays.append,
    )

    with pytest.raises(
        GeminiGenerationError,
        match="Gemini text generation failed.",
    ) as exc_info:
        client.generate("Generate SQL.")

    assert type(exc_info.value) is GeminiGenerationError
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert len(sdk_client.models.calls) == 1
    assert delays == []


def test_retries_api_error_then_succeeds() -> None:
    sdk_client = SequencedGeminiClient(
        [
            make_api_error(503),
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

    assert client.generate("Generate SQL.") == "SELECT 1"
    assert len(sdk_client.models.calls) == 2
    assert delays == [1.0]

    assert len(sdk_client.models.configs) == 2
    for config in sdk_client.models.configs:
        assert config is not None
        assert config.automatic_function_calling is not None
        assert config.automatic_function_calling.disable is True


def test_configures_sdk_timeout_and_single_attempt() -> None:
    with patch("verisight.execution.gemini.genai.Client") as factory:
        sdk = factory.return_value.__enter__.return_value
        async_sdk = sdk.aio.__aenter__.return_value
        async_sdk.models.generate_content = AsyncMock(
            return_value=StubGeminiResponse("SELECT 1")
        )
        client = GeminiTextGenerationClient(
            api_key="test-api-key",
            model="test-model",
            request_timeout_seconds=12.5,
        )
        factory.assert_not_called()
        assert client.generate("Generate SQL.") == "SELECT 1"
        async_sdk.models.generate_content.assert_awaited_once()
        sdk.aio.__aexit__.assert_awaited_once()
        factory.return_value.__exit__.assert_called_once()

    factory.assert_called_once()

    assert factory.call_args.kwargs["api_key"] == "test-api-key"

    options = factory.call_args.kwargs["http_options"]

    assert options.timeout == 12_500
    assert options.retry_options is not None
    assert options.retry_options.attempts == 1


def test_minimum_sdk_timeout_is_one_millisecond() -> None:
    with patch("verisight.execution.gemini.genai.Client") as factory:
        sdk = factory.return_value.__enter__.return_value
        async_sdk = sdk.aio.__aenter__.return_value
        async_sdk.models.generate_content = AsyncMock(
            return_value=StubGeminiResponse("SELECT 1")
        )
        client = GeminiTextGenerationClient(
            api_key="test-api-key",
            model="test-model",
            request_timeout_seconds=0.0001,
        )
        assert client.generate("Generate SQL.") == "SELECT 1"

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
    ) as exc_info:
        client.generate("Generate SQL.")

    assert type(exc_info.value) is GeminiGenerationError
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
    ) as exc_info:
        client.generate("Generate SQL.")

    assert type(exc_info.value) is GeminiGenerationError


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
    assert type(error) is GeminiGenerationError
    assert error.__cause__ is None
    assert error.__context__ is None


def test_transient_error_does_not_expose_provider_detail() -> None:
    secret = "synthetic-private-provider-detail"

    client = GeminiTextGenerationClient(
        api_key="synthetic-test-key",
        model="test-model",
        client=FailingGeminiClient(TimeoutError(f"Connection failed: {secret}")),
        max_retries=0,
    )

    with pytest.raises(GeminiTransientError) as exc_info:
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


@pytest.mark.parametrize("max_retries", [0, 1])
def test_default_request_deadline_cancels_before_retry(max_retries: int) -> None:
    events: list[str] = []

    async def slow_response(**kwargs: object) -> StubGeminiResponse:
        events.append("started")
        try:
            await asyncio.sleep(0.5)
        finally:
            events.append("cancelled")
        return StubGeminiResponse("too late")

    def retry_delay(seconds: float) -> None:
        assert events[-1] == "cancelled"
        events.append("retry")

    with patch("verisight.execution.gemini.genai.Client") as factory:
        sdk = factory.return_value.__enter__.return_value
        async_sdk = sdk.aio.__aenter__.return_value
        async_sdk.models.generate_content = AsyncMock(side_effect=slow_response)
        client = GeminiTextGenerationClient(
            api_key="synthetic-key",
            model="test-model",
            request_timeout_seconds=0.02,
            max_retries=max_retries,
            sleep=retry_delay,
        )
        with pytest.raises(GeminiTransientError) as caught:
            client.generate("Synthetic request")

        assert factory.call_count == max_retries + 1
        assert sdk.aio.__aexit__.await_count == max_retries + 1
        assert factory.return_value.__exit__.call_count == max_retries + 1
    assert events == (
        ["started", "cancelled"]
        if max_retries == 0
        else ["started", "cancelled", "retry", "started", "cancelled"]
    )
    assert caught.value.diagnostics is not None
    assert caught.value.diagnostics.attempts == max_retries + 1
    assert caught.value.diagnostics.http_status is None
    assert caught.value.__context__ is None


def test_default_request_retries_after_cancellation_and_preserves_telemetry() -> None:
    from verisight.execution.generation_telemetry import capture_generation_calls

    attempts = 0
    cancelled = False

    async def response(**kwargs: object) -> StubGeminiResponse:
        nonlocal attempts, cancelled
        attempts += 1
        if attempts == 1:
            try:
                await asyncio.sleep(0.5)
            finally:
                cancelled = True
        assert cancelled
        return StubGeminiResponse("SELECT 1")

    with patch("verisight.execution.gemini.genai.Client") as factory:
        sdk = factory.return_value.__enter__.return_value
        async_sdk = sdk.aio.__aenter__.return_value
        async_sdk.models.generate_content = AsyncMock(side_effect=response)

        def retry_delay(seconds: float) -> None:
            assert seconds == 1.0
            sdk.aio.__aexit__.assert_awaited_once()
            factory.return_value.__exit__.assert_called_once()

        client = GeminiTextGenerationClient(
            api_key="synthetic-key",
            model="test-model",
            request_timeout_seconds=0.02,
            max_retries=1,
            sleep=retry_delay,
        )
        with capture_generation_calls() as calls:
            assert client.generate("Synthetic request") == "SELECT 1"
        assert factory.call_count == 2
        assert calls[0].attempts == 2
        assert calls[0].returned_text is True


def test_sync_generation_works_inside_running_event_loop() -> None:
    async def invoke() -> None:
        with patch("verisight.execution.gemini.genai.Client") as factory:
            sdk = factory.return_value.__enter__.return_value
            async_sdk = sdk.aio.__aenter__.return_value
            async_sdk.models.generate_content = AsyncMock(
                return_value=StubGeminiResponse("SELECT 1")
            )
            client = GeminiTextGenerationClient(
                api_key="synthetic-key", model="test-model"
            )
            assert client.generate("First request") == "SELECT 1"
            assert client.generate("Second request") == "SELECT 1"
            assert factory.call_count == 2
            assert sdk.aio.__aexit__.await_count == 2

    asyncio.run(invoke())


def test_real_sdk_trickling_response_is_cancelled_and_closed() -> None:
    class TrickleStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.cancelled = False
            self.closed = False
            self.chunks = 0

        async def __aiter__(self) -> AsyncIterator[bytes]:
            try:
                for _ in range(100):
                    await asyncio.sleep(0.005)
                    self.chunks += 1
                    yield b" "
            except asyncio.CancelledError:
                self.cancelled = True
                raise
            yield b'{"candidates":[{"content":{"parts":[{"text":"late"}]}}]}'

        async def aclose(self) -> None:
            self.closed = True

    stream = TrickleStream()
    sync_http = httpx.Client(
        transport=httpx.MockTransport(lambda request: httpx.Response(500)),
        trust_env=False,
    )
    async_http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, stream=stream)
        ),
        trust_env=False,
    )
    sdk = genai.Client(
        api_key="synthetic-key",
        http_options=types.HttpOptions(
            httpx_client=sync_http,
            httpx_async_client=async_http,
            retry_options=types.HttpRetryOptions(attempts=1),
        ),
    )
    with patch("verisight.execution.gemini.genai.Client", return_value=sdk):
        client = GeminiTextGenerationClient(
            api_key="synthetic-key",
            model="test-model",
            request_timeout_seconds=0.05,
            max_retries=0,
        )
        with pytest.raises(GeminiTransientError):
            client.generate("Synthetic request")
    assert stream.cancelled
    assert stream.closed
    assert stream.chunks < 100
    # SDK leaves explicitly supplied HTTP clients owned by the caller.
    sync_http.close()
    asyncio.run(async_http.aclose())
