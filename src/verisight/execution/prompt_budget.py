"""Character-budget validation for LLM prompts."""

from dataclasses import dataclass

from verisight.exceptions import VeriSightError


class PromptBudgetExceededError(VeriSightError):
    """Raised when a complete prompt exceeds its configured budget."""

    def __init__(
        self,
        *,
        max_prompt_chars: int,
        actual_prompt_chars: int,
    ) -> None:
        self.max_prompt_chars = max_prompt_chars
        self.actual_prompt_chars = actual_prompt_chars

        super().__init__(
            "Prompt character budget exceeded: "
            f"actual={actual_prompt_chars}, "
            f"maximum={max_prompt_chars}. "
            "Reduce the investigation context or increase the prompt budget."
        )


@dataclass(frozen=True, slots=True)
class PromptBudget:
    """Validate complete prompts without changing their content."""

    max_prompt_chars: int = 60_000

    def __post_init__(self) -> None:
        """Reject invalid character budgets."""

        if self.max_prompt_chars <= 0:
            raise ValueError("Maximum prompt characters must be positive.")

    def enforce(self, prompt: str) -> str:
        """Return an unchanged prompt or raise when it exceeds the budget."""

        actual = len(prompt)

        if actual > self.max_prompt_chars:
            raise PromptBudgetExceededError(
                max_prompt_chars=self.max_prompt_chars,
                actual_prompt_chars=actual,
            )

        return prompt
