from verisight.execution.generation import TextGenerationClient


class StubTextGenerationClient:
    """Simple implementation used to verify the generation contract."""

    def generate(self, prompt: str) -> str:
        return f"generated:{prompt}"


def _generate(
    client: TextGenerationClient,
    prompt: str,
) -> str:
    return client.generate(prompt)


def test_text_generation_client_accepts_compatible_implementation() -> None:
    result = _generate(
        StubTextGenerationClient(),
        "test prompt",
    )

    assert result == "generated:test prompt"
