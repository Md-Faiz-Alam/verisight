from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.execution.investigation import InvestigationState
from verisight.execution.synthesis import InvestigationSynthesizer
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile


class StubInvestigationSynthesizer:
    """Deterministic investigation synthesizer for contract tests."""

    def synthesize(self, state: InvestigationState) -> str:
        return f"Conclusion for: {state.question}"


def _build_state() -> InvestigationState:
    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(),
    )

    return InvestigationState(
        question="Why did revenue decline?",
        analysis=AnalysisResultBuilder().build(analysis),
    )


def _synthesize(
    synthesizer: InvestigationSynthesizer,
    state: InvestigationState,
) -> str:
    return synthesizer.synthesize(state)


def test_investigation_synthesizer_contract() -> None:
    conclusion = _synthesize(
        StubInvestigationSynthesizer(),
        _build_state(),
    )

    assert conclusion == "Conclusion for: Why did revenue decline?"
