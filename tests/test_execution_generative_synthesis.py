"""Tests for the generative investigation synthesizer."""

import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.error_reporting import ErrorCode
from verisight.execution.exceptions import InvestigationError
from verisight.execution.gemini import GeminiGenerationError, GeminiTransientError
from verisight.execution.generative_synthesis import (
    GenerativeInvestigationSynthesizer,
)
from verisight.execution.investigation import InvestigationState
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation
from verisight.execution.prompt_budget import PromptBudgetExceededError
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile
from verisight.public_api import run_public_operation


class StubTextGenerationClient:
    """Deterministic generation client for synthesis tests."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def _build_state(
    *,
    observations: tuple[QueryObservation, ...] = (),
) -> InvestigationState:
    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(),
    )

    return InvestigationState(
        question="Why did revenue decline?",
        analysis=AnalysisResultBuilder().build(analysis),
        observations=observations,
    )


def test_generative_synthesizer_returns_conclusion() -> None:
    client = StubTextGenerationClient(
        "Revenue declined because the observed monthly totals decreased."
    )

    synthesizer = GenerativeInvestigationSynthesizer(client)

    conclusion = synthesizer.synthesize(_build_state())

    assert conclusion == (
        "Revenue declined because the observed monthly totals decreased."
    )


def test_generative_synthesizer_strips_surrounding_whitespace() -> None:
    client = StubTextGenerationClient(
        "\n  Revenue declined across the observed period.  \n"
    )

    synthesizer = GenerativeInvestigationSynthesizer(client)

    conclusion = synthesizer.synthesize(_build_state())

    assert conclusion == "Revenue declined across the observed period."


def test_generative_synthesizer_builds_prompt_from_state() -> None:
    observation = QueryObservation(
        question="What is revenue by month?",
        sql="SELECT month, SUM(revenue) AS revenue FROM sales GROUP BY month",
        result=QueryResult(
            columns=("month", "revenue"),
            rows=(
                ("January", 1000),
                ("February", 800),
            ),
        ),
    )

    client = StubTextGenerationClient("Revenue decreased from January to February.")

    synthesizer = GenerativeInvestigationSynthesizer(client)

    synthesizer.synthesize(_build_state(observations=(observation,)))

    assert len(client.prompts) == 1

    prompt = client.prompts[0]

    assert "analytical conclusion synthesizer for VeriSight" in prompt
    assert "ORIGINAL QUESTION\nWhy did revenue decline?" in prompt
    assert "OBSERVATION 1" in prompt
    assert "Question: What is revenue by month?" in prompt
    assert '["January",1000]' in prompt
    assert '["February",800]' in prompt


@pytest.mark.parametrize(
    "response",
    [
        "",
        " ",
        "\n\t",
    ],
)
def test_generative_synthesizer_rejects_empty_conclusion(
    response: str,
) -> None:
    client = StubTextGenerationClient(response)

    synthesizer = GenerativeInvestigationSynthesizer(client)

    with pytest.raises(
        InvestigationError,
        match="Investigation synthesizer returned an empty conclusion.",
    ):
        synthesizer.synthesize(_build_state())


def test_generative_synthesizer_does_not_call_llm_for_oversized_prompt() -> None:
    client = StubTextGenerationClient("Conclusion.")
    synthesizer = GenerativeInvestigationSynthesizer(client)

    state = _build_state()
    oversized_state = InvestigationState(
        question="X" * 60_000,
        analysis=state.analysis,
    )

    with pytest.raises(PromptBudgetExceededError):
        synthesizer.synthesize(oversized_state)

    assert client.prompts == []


def test_generative_synthesizer_translates_provider_failure() -> None:
    class FailingClient:
        def generate(self, prompt: str) -> str:
            raise GeminiGenerationError("Provider unavailable.")

    synthesizer = GenerativeInvestigationSynthesizer(FailingClient())

    with pytest.raises(
        InvestigationError,
        match="Investigation synthesis text generation failed.",
    ) as exc_info:
        synthesizer.synthesize(_build_state())

    assert isinstance(exc_info.value.__cause__, GeminiGenerationError)


def test_generative_synthesizer_preserves_unexpected_errors() -> None:
    class FailingClient:
        def generate(self, prompt: str) -> str:
            raise RuntimeError("Unexpected programming error.")

    synthesizer = GenerativeInvestigationSynthesizer(FailingClient())

    with pytest.raises(
        RuntimeError,
        match="Unexpected programming error.",
    ):
        synthesizer.synthesize(_build_state())


def test_generative_synthesizer_preserves_transient_provider_failure() -> None:
    error = GeminiTransientError("Gemini is temporarily unavailable.")

    class FailingClient:
        def generate(self, prompt: str) -> str:
            raise error

    synthesizer = GenerativeInvestigationSynthesizer(FailingClient())

    with pytest.raises(GeminiTransientError) as exc_info:
        synthesizer.synthesize(_build_state())

    assert exc_info.value is error
    assert exc_info.value.__cause__ is None


def test_generative_synthesizer_reports_transient_provider_unavailable() -> None:
    class FailingClient:
        def generate(self, prompt: str) -> str:
            raise GeminiTransientError("Sensitive provider details.")

    synthesizer = GenerativeInvestigationSynthesizer(FailingClient())

    result = run_public_operation(lambda: synthesizer.synthesize(_build_state()))

    assert result.succeeded is False
    assert result.value is None
    assert result.error is not None
    assert result.error.code is ErrorCode.PROVIDER_UNAVAILABLE
    assert result.error.message == "The AI provider is temporarily unavailable."
    assert "Sensitive provider details." not in repr(result)
