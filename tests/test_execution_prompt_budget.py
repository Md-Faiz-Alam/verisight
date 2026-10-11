"""Tests for deterministic prompt character-budget enforcement."""

import pytest

from verisight.exceptions import VeriSightError
from verisight.execution.prompt_budget import (
    PromptBudget,
    PromptBudgetExceededError,
)


@pytest.mark.parametrize("limit", [0, -1, -100])
def test_rejects_non_positive_budget(limit: int) -> None:
    with pytest.raises(
        ValueError,
        match="Maximum prompt characters must be positive.",
    ):
        PromptBudget(max_prompt_chars=limit)


def test_default_budget_is_sixty_thousand_characters() -> None:
    assert PromptBudget().max_prompt_chars == 60_000


def test_accepts_prompt_below_budget_without_modification() -> None:
    prompt = "Analytical evidence"

    result = PromptBudget(max_prompt_chars=100).enforce(prompt)

    assert result == prompt


def test_accepts_prompt_at_exact_budget() -> None:
    prompt = "A" * 100

    result = PromptBudget(max_prompt_chars=100).enforce(prompt)

    assert result == prompt
    assert len(result) == 100


def test_rejects_prompt_one_character_over_budget() -> None:
    with pytest.raises(PromptBudgetExceededError) as exc_info:
        PromptBudget(max_prompt_chars=100).enforce("A" * 101)

    error = exc_info.value

    assert error.max_prompt_chars == 100
    assert error.actual_prompt_chars == 101
    assert "actual=101" in str(error)
    assert "maximum=100" in str(error)


def test_budget_error_inherits_application_error() -> None:
    with pytest.raises(VeriSightError):
        PromptBudget(max_prompt_chars=1).enforce("Too long")


def test_empty_prompt_is_accepted() -> None:
    assert PromptBudget(max_prompt_chars=1).enforce("") == ""


def test_unicode_characters_are_counted_as_python_characters() -> None:
    prompt = "é😀"

    assert PromptBudget(max_prompt_chars=2).enforce(prompt) == prompt

    with pytest.raises(PromptBudgetExceededError) as exc_info:
        PromptBudget(max_prompt_chars=1).enforce(prompt)

    assert exc_info.value.actual_prompt_chars == 2


def test_budget_enforcement_is_deterministic() -> None:
    budget = PromptBudget(max_prompt_chars=20)
    prompt = "SELECT COUNT(*)"

    assert budget.enforce(prompt) == budget.enforce(prompt)
