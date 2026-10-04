from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.execution.investigation import InvestigationState
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation
from verisight.execution.synthesis_prompting import (
    InvestigationSynthesisPromptBuilder,
)
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile


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
        question="Why did the measured outcome change?",
        analysis=AnalysisResultBuilder().build(analysis),
        observations=observations,
    )


def test_builds_investigation_synthesis_prompt() -> None:
    prompt = InvestigationSynthesisPromptBuilder().build(_build_state())

    assert "analytical conclusion synthesizer for VeriSight" in prompt
    assert "ORIGINAL QUESTION\nWhy did the measured outcome change?" in prompt
    assert "EXECUTED OBSERVATIONS\nNone" in prompt


def test_synthesis_prompt_requires_evidence_grounded_answer() -> None:
    prompt = InvestigationSynthesisPromptBuilder().build(_build_state())

    assert "Use only evidence present in the supplied investigation state." in prompt
    assert "Do not invent facts" in prompt
    assert "Distinguish observed evidence from interpretation." in prompt


def test_synthesis_prompt_handles_causal_uncertainty() -> None:
    prompt = InvestigationSynthesisPromptBuilder().build(_build_state())

    assert "Do not claim causation" in prompt
    assert (
        "If the available evidence is insufficient for a definitive answer"
    ) in prompt


def test_synthesis_prompt_requires_explicit_quantitative_evidence() -> None:
    prompt = InvestigationSynthesisPromptBuilder().build(_build_state())

    assert (
        "Base quantitative claims on quantities explicitly present in "
        "the deterministic analysis or executed observation results."
    ) in prompt


def test_synthesis_prompt_rejects_unexecuted_analytical_computation() -> None:
    prompt = InvestigationSynthesisPromptBuilder().build(_build_state())

    assert (
        "do not silently perform a new aggregation, grouping, weighted "
        "calculation, derived metric, statistical test, or other "
        "analytical computation"
    ) in prompt
    assert (
        "Do not present a newly calculated mean, total, rate, ratio, "
        "percentage, correlation, trend statistic, or grouped result"
    ) in prompt


def test_synthesis_prompt_requires_insufficient_evidence_when_metric_missing() -> None:
    prompt = InvestigationSynthesisPromptBuilder().build(_build_state())

    assert (
        "If answering the original question requires an analytical "
        "quantity that was not produced by the investigation"
    ) in prompt
    assert "rather than calculating the missing quantity yourself." in prompt


def test_synthesis_prompt_preserves_observation_grain() -> None:
    prompt = InvestigationSynthesisPromptBuilder().build(_build_state())

    assert "Preserve the analytical grain of executed observations." in prompt
    assert (
        "Do not reinterpret row-level results as grouped aggregates or "
        "grouped results as evidence at a different grain."
    ) in prompt


def test_synthesis_prompt_requires_quality_limitations() -> None:
    prompt = InvestigationSynthesisPromptBuilder().build(_build_state())

    assert (
        "Mention relevant data-quality limitations when they materially "
        "affect interpretation."
    ) in prompt


def test_synthesis_prompt_requires_plain_conclusion() -> None:
    prompt = InvestigationSynthesisPromptBuilder().build(_build_state())

    assert "Do not generate SQL." in prompt
    assert "Do not use Markdown code fences." in prompt
    assert "Return only the final analytical conclusion and nothing else." in prompt


def test_synthesis_prompt_includes_executed_observations() -> None:
    observation = QueryObservation(
        question="What is the measurement by period?",
        sql=(
            "SELECT period, AVG(measurement) AS measurement "
            "FROM observations GROUP BY period"
        ),
        result=QueryResult(
            columns=("period", "measurement"),
            rows=(
                ("Period A", 1000),
                ("Period B", 800),
            ),
        ),
    )

    prompt = InvestigationSynthesisPromptBuilder().build(
        _build_state(observations=(observation,))
    )

    assert "EXECUTED OBSERVATIONS" in prompt
    assert "OBSERVATION 1" in prompt
    assert "Question: What is the measurement by period?" in prompt
    assert '["Period A",1000]' in prompt
    assert '["Period B",800]' in prompt


def test_synthesis_prompt_is_domain_agnostic() -> None:
    prompt = InvestigationSynthesisPromptBuilder().build(_build_state())

    domain_specific_examples = (
        "revenue",
        "sales",
        "student",
        "attendance",
        "course",
        "temperature",
        "service failure",
    )

    for example in domain_specific_examples:
        assert example not in prompt.lower()


def test_synthesis_prompt_is_deterministic() -> None:
    state = _build_state()
    builder = InvestigationSynthesisPromptBuilder()

    first = builder.build(state)
    second = builder.build(state)

    assert first == second
