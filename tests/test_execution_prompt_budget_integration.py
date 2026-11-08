"""Integration tests for investigation prompt budgets."""

import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_prompting import (
    InvestigationPromptBuilder,
)
from verisight.execution.prompt_budget import PromptBudgetExceededError
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile


def _state(question: str = "What happened?") -> InvestigationState:
    """Construct a minimal investigation state."""

    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(),
    )

    return InvestigationState(
        question=question,
        analysis=AnalysisResultBuilder().build(analysis),
    )


def _builder(limit: int) -> InvestigationPromptBuilder:
    return InvestigationPromptBuilder(max_prompt_chars=limit)


def test_existing_prompt_remains_unchanged() -> None:
    state = _state()

    original = _builder(60_000).build(state)
    budgeted = _builder(len(original)).build(state)

    assert budgeted == original
    assert "ORIGINAL QUESTION" in budgeted
    assert "What happened?" in budgeted


def test_rejects_prompt_one_character_over_budget() -> None:
    state = _state()
    original = _builder(60_000).build(state)

    with pytest.raises(PromptBudgetExceededError) as exc_info:
        _builder(len(original) - 1).build(state)

    assert exc_info.value.actual_prompt_chars == len(original)
    assert exc_info.value.max_prompt_chars == len(original) - 1


def test_rejects_oversized_investigation_question() -> None:
    state = _state("X" * 70_000)

    with pytest.raises(PromptBudgetExceededError):
        _builder(60_000).build(state)


def test_rejects_invalid_builder_budget() -> None:
    with pytest.raises(
        ValueError,
        match="Maximum prompt characters must be positive.",
    ):
        _builder(0)


def test_prompt_building_remains_deterministic() -> None:
    state = _state()
    builder = _builder(60_000)

    assert builder.build(state) == builder.build(state)
