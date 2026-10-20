"""Explicit formatter configuration preserves synthesis evidence and budgets."""

import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.execution.generative_synthesis import GenerativeInvestigationSynthesizer
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_formatting import InvestigationStateFormatter
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation
from verisight.execution.prompt_budget import PromptBudgetExceededError
from verisight.execution.synthesis_prompting import InvestigationSynthesisPromptBuilder
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile


class RecordingClient:
    """Capture prompts without making provider requests."""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return "  Evidence reviewed.  "


def _state(row_count: int) -> InvestigationState:
    analysis = AnalysisResultBuilder().build(
        DatasetAnalysis(
            schema=DatasetSchema(tables=()),
            profile=DatasetProfile(tables=()),
            issues=(),
        )
    )
    return InvestigationState(
        question="Describe the supplied measurements.",
        analysis=analysis,
        observations=(
            QueryObservation(
                question="Read the measurements.",
                sql="SELECT metric FROM measurements",
                result=QueryResult(
                    columns=("metric",),
                    rows=tuple((index,) for index in range(row_count)),
                ),
            ),
        ),
    )


def test_explicit_default_formatter_preserves_prompt_content() -> None:
    state = _state(101)
    default_prompt = InvestigationSynthesisPromptBuilder().build(state)
    configured_prompt = InvestigationSynthesisPromptBuilder(
        state_formatter=InvestigationStateFormatter()
    ).build(state)
    assert configured_prompt == default_prompt
    assert "Rows omitted: 1 of 101" in default_prompt


def test_supplied_formatter_controls_evidence_without_changing_other_builders() -> None:
    state = _state(3)
    builder = InvestigationSynthesisPromptBuilder(
        state_formatter=InvestigationStateFormatter(max_result_rows=1)
    )
    prompt = builder.build(state)
    assert "[0]" in prompt
    assert "[1]" not in prompt
    assert "Rows omitted: 2 of 3" in prompt
    assert "Rows omitted:" not in InvestigationSynthesisPromptBuilder().build(state)
    assert builder.build(state) == prompt


def test_supplied_formatter_still_obeys_exact_prompt_budget() -> None:
    state = _state(101)
    formatter = InvestigationStateFormatter(max_result_rows=101)
    prompt = InvestigationSynthesisPromptBuilder(state_formatter=formatter).build(state)
    assert "Rows omitted:" not in prompt
    assert (
        InvestigationSynthesisPromptBuilder(
            state_formatter=formatter, max_prompt_chars=len(prompt)
        ).build(state)
        == prompt
    )
    with pytest.raises(PromptBudgetExceededError) as caught:
        InvestigationSynthesisPromptBuilder(
            state_formatter=formatter, max_prompt_chars=len(prompt) - 1
        ).build(state)
    assert caught.value.actual_prompt_chars == len(prompt)
    assert caught.value.max_prompt_chars == len(prompt) - 1


def test_legacy_synthesis_keeps_full_evidence_across_successive_calls() -> None:
    client = RecordingClient()
    synthesizer = GenerativeInvestigationSynthesizer(client)
    for row_count in (101, 2, 103):
        state = _state(row_count)
        assert synthesizer.synthesize(state) == "Evidence reviewed."
        prompt = client.prompts[-1]
        expected = InvestigationSynthesisPromptBuilder(
            state_formatter=InvestigationStateFormatter(max_result_rows=row_count)
        ).build(state)
        assert prompt == expected
        assert f"[{row_count - 1}]" in prompt
        assert "Rows omitted:" not in prompt
    assert len(client.prompts) == 3
