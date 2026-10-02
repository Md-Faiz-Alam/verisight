"""Gemini text-generation client for analytical query planning."""

from typing import Protocol

from google import genai


class _GeminiResponse(Protocol):
    """Response surface required from the Gemini SDK."""

    @property
    def text(self) -> str | None:
        """Return generated response text."""
        ...


class _GeminiModels(Protocol):
    """Model-generation surface required from the Gemini SDK."""

    def generate_content(
        self,
        *,
        model: str,
        contents: str,
    ) -> _GeminiResponse:
        """Generate content using a Gemini model."""
        ...


class _GeminiClient(Protocol):
    """Client surface required by the Gemini text-generation adapter."""

    @property
    def models(self) -> _GeminiModels:
        """Return the Gemini models API."""
        ...


class GeminiTextGenerationClient:
    """Generate planner text using the Gemini API."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        client: _GeminiClient | None = None,
    ) -> None:
        """Initialize the Gemini text-generation client."""

        if not api_key.strip():
            raise ValueError("Gemini API key must not be empty.")

        if not model.strip():
            raise ValueError("Gemini model must not be empty.")

        self._model = model
        self._client = client if client is not None else genai.Client(api_key=api_key)

    def generate(self, prompt: str) -> str:
        """Generate text for a planner prompt."""

        if not prompt.strip():
            raise ValueError("Generation prompt must not be empty.")

        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
        )

        text = response.text

        if text is None or not text.strip():
            raise ValueError("Gemini returned an empty text response.")

        return text
