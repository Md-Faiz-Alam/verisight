"""Integration tests for investigation and synthesis prompt budgets."""

from collections.abc import Callable

import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_prompting import (
    InvestigationPromptBuilder,
)
from verisight.execution.prompt_budget import PromptBudgetExceededError
from verisight.execution.synthesis_prompting import (
    InvestigationSynthesisPromptBuilder,
)
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


BuilderFactory = Callable[
    [int],
    InvestigationPromptBuilder | InvestigationSynthesisPromptBuilder,
]


def _investigator(limit: int) -> InvestigationPromptBuilder:
    return InvestigationPromptBuilder(max_prompt_chars=limit)


def _synthesizer(limit: int) -> InvestigationSynthesisPromptBuilder:
    return InvestigationSynthesisPromptBuilder(max_prompt_chars=limit)


@pytest.mark.parametrize(
    "factory",
    [_investigator, _synthesizer],
)
def test_existing_prompt_remains_unchanged(
    factory: BuilderFactory,
) -> None:
    state = _state()

    original = factory(60_000).build(state)
    budgeted = factory(len(original)).build(state)

    assert budgeted == original
    assert "ORIGINAL QUESTION" in budgeted
    assert "What happened?" in budgeted


@pytest.mark.parametrize(
    "factory",
    [_investigator, _synthesizer],
)
def test_rejects_prompt_one_character_over_budget(
    factory: BuilderFactory,
) -> None:
    state = _state()
    original = factory(60_000).build(state)

    with pytest.raises(PromptBudgetExceededError) as exc_info:
        factory(len(original) - 1).build(state)

    assert exc_info.value.actual_prompt_chars == len(original)
    assert exc_info.value.max_prompt_chars == len(original) - 1


@pytest.mark.parametrize(
    "factory",
    [_investigator, _synthesizer],
)
def test_rejects_oversized_investigation_question(
    factory: BuilderFactory,
) -> None:
    state = _state("X" * 70_000)

    with pytest.raises(PromptBudgetExceededError):
        factory(60_000).build(state)


@pytest.mark.parametrize(
    "factory",
    [_investigator, _synthesizer],
)
def test_rejects_invalid_builder_budget(
    factory: BuilderFactory,
) -> None:
    with pytest.raises(
        ValueError,
        match="Maximum prompt characters must be positive.",
    ):
        factory(0)


@pytest.mark.parametrize(
    "factory",
    [_investigator, _synthesizer],
)
def test_prompt_building_remains_deterministic(
    factory: BuilderFactory,
) -> None:
    state = _state()
    builder = factory(60_000)

    assert builder.build(state) == builder.build(state)
