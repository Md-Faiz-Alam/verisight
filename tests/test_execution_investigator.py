from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.execution.decisions import (
    InvestigationAction,
    InvestigationDecision,
)
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigator import Investigator
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile


class StubInvestigator:
    """Deterministic investigator used to verify the contract."""

    def decide(
        self,
        state: InvestigationState,
    ) -> InvestigationDecision:
        return InvestigationDecision(
            action=InvestigationAction.INVESTIGATE,
            reasoning="A time-based comparison is required.",
            question=f"Break down this question by time: {state.question}",
        )


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


def _decide(
    investigator: Investigator,
    state: InvestigationState,
) -> InvestigationDecision:
    return investigator.decide(state)


def test_investigator_accepts_compatible_implementation() -> None:
    state = _build_state()

    decision = _decide(
        StubInvestigator(),
        state,
    )

    assert decision == InvestigationDecision(
        action=InvestigationAction.INVESTIGATE,
        reasoning="A time-based comparison is required.",
        question=("Break down this question by time: Why did revenue decline?"),
    )
