import pytest

from verisight.execution.gemini import GeminiTextGenerationClient


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


def test_generates_text_with_configured_model() -> None:
    sdk_client = StubGeminiClient("SELECT COUNT(*) FROM orders")

    client = GeminiTextGenerationClient(
        api_key="test-api-key",
        model="test-model",
        client=sdk_client,
    )

    result = client.generate("Generate SQL.")

    assert result == "SELECT COUNT(*) FROM orders"
    assert sdk_client.models.calls == [
        (
            "test-model",
            "Generate SQL.",
        )
    ]


@pytest.mark.parametrize(
    "api_key",
    [
        "",
        " ",
        "\n\t",
    ],
)
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


@pytest.mark.parametrize(
    "model",
    [
        "",
        " ",
        "\n\t",
    ],
)
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


@pytest.mark.parametrize(
    "prompt",
    [
        "",
        " ",
        "\n\t",
    ],
)
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


@pytest.mark.parametrize(
    "response_text",
    [
        None,
        "",
        " ",
        "\n\t",
    ],
)
def test_rejects_empty_gemini_response(
    response_text: str | None,
) -> None:
    client = GeminiTextGenerationClient(
        api_key="test-api-key",
        model="test-model",
        client=StubGeminiClient(response_text),
    )

    with pytest.raises(
        ValueError,
        match="Gemini returned an empty text response.",
    ):
        client.generate("Generate SQL.")
