"""Gemini text-generation client for analytical query planning."""

import asyncio
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from dataclasses import dataclass
from typing import Protocol

import httpx
from google import genai
from google.genai import errors, types

from verisight.exceptions import VeriSightError
from verisight.execution.deadline import (
    InvestigationDeadlineExceeded,
    check_deadline,
    remaining_seconds,
)
from verisight.execution.generation_telemetry import (
    GenerationStage,
    track_generation_call,
)


@dataclass(frozen=True, slots=True)
class ProviderFailureDiagnostics:
    """Allowlisted metadata only; never retain an SDK exception or request."""

    http_status: int | None
    retryable: bool
    attempts: int
    stage: GenerationStage
    call_number: int


class GeminiGenerationError(VeriSightError):
    """Raised when Gemini cannot provide a usable text response."""

    def __init__(
        self,
        message: str,
        *,
        diagnostics: ProviderFailureDiagnostics | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class GeminiTransientError(GeminiGenerationError):
    """Raised when a retryable Gemini request fails after retries."""


class _GeminiResponse(Protocol):
    @property
    def text(self) -> str | None: ...


class _GeminiModels(Protocol):
    def generate_content(
        self,
        *,
        model: str,
        contents: str,
        config: types.GenerateContentConfig | None = None,
    ) -> _GeminiResponse: ...


class _GeminiClient(Protocol):
    @property
    def models(self) -> _GeminiModels: ...


def _is_retryable(error: Exception) -> bool:
    """Return whether a provider failure is safe to retry."""

    if isinstance(error, errors.APIError):
        return error.code == 429 or 500 <= error.code < 600

    return isinstance(
        error,
        (
            TimeoutError,
            ConnectionError,
            httpx.TimeoutException,
            httpx.TransportError,
        ),
    )


def _generation_stage(schema: dict[str, object] | None) -> GenerationStage:
    """Infer a coarse stage from response fields, never from prompt contents."""
    properties = schema.get("properties") if schema is not None else None
    if isinstance(properties, dict):
        if "claims" in properties:
            return "structured_synthesis"
        if "action" in properties:
            return "investigator"
    return "text_generation"


class GeminiTextGenerationClient:
    """Generate text with cancellable SDK requests and bounded retries.

    The default SDK request is cancelled after request_timeout_seconds per
    attempt. Client setup and cancellation/connection cleanup add overhead;
    this is not an operating-system hard deadline for the whole investigation.
    Injected synchronous clients remain caller-owned and must enforce their
    own request deadlines.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        client: _GeminiClient | None = None,
        request_timeout_seconds: float = 30.0,
        max_retries: int = 2,
        retry_base_delay_seconds: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
        response_json_schema: dict[str, object] | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("Gemini API key must not be empty.")

        if not model.strip():
            raise ValueError("Gemini model must not be empty.")

        if not 0 < request_timeout_seconds < float("inf"):
            raise ValueError("Gemini request timeout must be finite and positive.")

        if isinstance(max_retries, bool) or not 0 <= max_retries <= 5:
            raise ValueError("Gemini max retries must be between 0 and 5.")

        if not 0 < retry_base_delay_seconds < float("inf"):
            raise ValueError("Gemini retry delay must be finite and positive.")

        self._stage: GenerationStage = _generation_stage(response_json_schema)
        self._call_number = 0
        self._model = model
        self._max_retries = max_retries
        self._retry_base_delay_seconds = retry_base_delay_seconds
        self._sleep = sleep
        self._response_config = types.GenerateContentConfig(
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
            response_mime_type=(
                "application/json" if response_json_schema is not None else None
            ),
            response_json_schema=response_json_schema,
        )

        self._client = client
        self._api_key = api_key
        self._request_timeout_seconds = request_timeout_seconds
        self._http_options = types.HttpOptions(
            timeout=max(1, int(request_timeout_seconds * 1000)),
            retry_options=types.HttpRetryOptions(attempts=1),
        )

    async def _request_async(self, prompt: str) -> _GeminiResponse:
        """Cancel the SDK coroutine and close both clients before returning."""
        # A fresh client stays on one event loop and is closed on every path.
        with genai.Client(
            api_key=self._api_key, http_options=self._http_options
        ) as client:
            async with client.aio as async_client:
                async with asyncio.timeout(
                    remaining_seconds(self._request_timeout_seconds)
                ):
                    return await async_client.models.generate_content(
                        model=self._model,
                        contents=prompt,
                        config=self._response_config,
                    )

    def _request(self, prompt: str) -> _GeminiResponse:
        """Keep the public API synchronous without abandoning timed-out work."""
        if self._client is not None:
            return self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config=self._response_config,
            )

        # The worker owns its event loop, even if the caller already has one.
        # Cancellation happens inside that loop; result() waits for cleanup.
        # A timeout on Future.result() alone would leave the request running.
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(
                copy_context().run, self._run_request, prompt
            ).result()

    def _run_request(self, prompt: str) -> _GeminiResponse:
        return asyncio.run(self._request_async(prompt))

    def generate(self, prompt: str) -> str:
        """Generate text, retrying only transient request failures."""

        if not prompt.strip():
            raise ValueError("Generation prompt must not be empty.")

        self._call_number += 1
        with track_generation_call(self._stage, self._call_number) as call:
            for attempt in range(self._max_retries + 1):
                check_deadline()
                call.attempts = attempt + 1
                try:
                    response = self._request(prompt)
                    check_deadline()
                except InvestigationDeadlineExceeded:
                    raise
                except Exception as exc:
                    http_status = exc.code if isinstance(exc, errors.APIError) else None
                    retryable = _is_retryable(exc)
                else:
                    try:
                        text = response.text
                    except (AttributeError, ValueError):
                        # Raise outside this handler for the same reason.
                        pass
                    else:
                        if text is None or not text.strip():
                            raise self._failure(
                                "Gemini returned an empty text response.",
                                attempts=attempt + 1,
                            )

                        call.returned_text = True
                        return text

                    raise self._failure(
                        "Gemini returned an unusable text response.",
                        attempts=attempt + 1,
                    )

                # Raise deadline errors outside the SDK exception handler so
                # provider details cannot leak through exception context.
                check_deadline()
                if retryable and attempt < self._max_retries:
                    delay = min(self._retry_base_delay_seconds * (2**attempt), 8.0)
                    self._sleep(remaining_seconds(delay))
                    continue

                if retryable:
                    raise self._failure(
                        "Gemini is temporarily unavailable.",
                        attempts=attempt + 1,
                        http_status=http_status,
                        retryable=True,
                    )

                raise self._failure(
                    "Gemini text generation failed.",
                    attempts=attempt + 1,
                    http_status=http_status,
                )

            raise AssertionError(
                "Gemini retry loop ended unexpectedly."
            )  # pragma: no cover

    def _failure(
        self,
        message: str,
        *,
        attempts: int,
        http_status: int | None = None,
        retryable: bool = False,
    ) -> GeminiGenerationError:
        error_type = GeminiTransientError if retryable else GeminiGenerationError
        return error_type(
            message,
            diagnostics=ProviderFailureDiagnostics(
                http_status=http_status,
                retryable=retryable,
                attempts=attempts,
                stage=self._stage,
                call_number=self._call_number,
            ),
        )
