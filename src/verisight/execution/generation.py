"""Contracts for planner text generation."""

from typing import Protocol


class TextGenerationClient(Protocol):
    """Contract for components that generate text from a prompt."""

    def generate(self, prompt: str) -> str:
        """Generate text for a prompt."""
        ...
