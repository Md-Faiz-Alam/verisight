"""Gemini text-generation client for analytical query planning."""

import time
from collections.abc import Callable
from typing import Protocol

import httpx
from google import genai
from google.genai import errors, types

from verisight.exceptions import VeriSightError


class GeminiGenerationError(VeriSightError):
    """Raised when Gemini cannot provide a usable text response."""


class _GeminiResponse(Protocol):
    @property
    def text(self) -> str | None: ...


class _GeminiModels(Protocol):
    def generate_content(
        self,
        *,
        model: str,
        contents: str,
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


class GeminiTextGenerationClient:
    """Generate text with bounded retries for transient Gemini failures."""

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

        self._model = model
        self._max_retries = max_retries
        self._retry_base_delay_seconds = retry_base_delay_seconds
        self._sleep = sleep

        self._client = (
            client
            if client is not None
            else genai.Client(
                api_key=api_key,
                http_options=types.HttpOptions(
                    timeout=max(1, int(request_timeout_seconds * 1000)),
                    retry_options=types.HttpRetryOptions(attempts=1),
                ),
            )
        )

    def generate(self, prompt: str) -> str:
        """Generate text, retrying only transient request failures."""

        if not prompt.strip():
            raise ValueError("Generation prompt must not be empty.")

        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=prompt,
                )
            except Exception as exc:
                if not _is_retryable(exc) or attempt == self._max_retries:
                    raise GeminiGenerationError(
                        "Gemini text generation failed."
                    ) from exc

                delay = min(
                    self._retry_base_delay_seconds * (2**attempt),
                    8.0,
                )
                self._sleep(delay)
                continue

            try:
                text = response.text
            except (AttributeError, ValueError) as exc:
                raise GeminiGenerationError(
                    "Gemini returned an unusable text response."
                ) from exc

            if text is None or not text.strip():
                raise GeminiGenerationError("Gemini returned an empty text response.")

            return text

        raise AssertionError(
            "Gemini retry loop ended unexpectedly."
        )  # pragma: no cover
