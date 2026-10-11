"""Integration tests for provider failures across execution boundaries."""

from pathlib import Path

import pandas as pd
import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder, DatasetAnalysisResult
from verisight.execution.decisions import (
    InvestigationAction,
    InvestigationDecision,
)
from verisight.execution.exceptions import QueryPlanningError
from verisight.execution.gemini import GeminiGenerationError
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.generative_repair import GenerativeQueryRepairer
from verisight.execution.investigation import InvestigationState
from verisight.execution.orchestration import InvestigationOrchestrator
from verisight.execution.service import AnalyticalExecutionService
from verisight.ingestion.models import (
    LoadedDataset,
    LoadedTable,
    SourceMetadata,
)
from verisight.ingestion.schema import SchemaInferer
from verisight.profiling.models import DatasetProfile


class FailingGenerationClient:
    """Simulate a provider failure at the text-generation boundary."""

    def __init__(self, error: GeminiGenerationError) -> None:
        self.error = error
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        raise self.error


class StaticGenerationClient:
    """Return deterministic SQL without contacting Gemini."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class SingleQuestionInvestigator:
    """Request one analytical query, then finish if execution succeeds."""

    def __init__(self, question: str) -> None:
        self.question = question
        self.states: list[InvestigationState] = []

    def decide(self, state: InvestigationState) -> InvestigationDecision:
        self.states.append(state)

        if state.observation_count or state.failed_attempt_count:
            return InvestigationDecision(
                action=InvestigationAction.FINISH,
                reasoning="Investigation attempt completed.",
            )

        return InvestigationDecision(
            action=InvestigationAction.INVESTIGATE,
            reasoning="Analytical evidence is required.",
            question=self.question,
        )


class RecordingSynthesizer:
    """Record whether investigation synthesis was attempted."""

    def __init__(self) -> None:
        self.states: list[InvestigationState] = []

    def synthesize(self, state: InvestigationState) -> str:
        self.states.append(state)
        return "Investigation completed."


def _dataset() -> LoadedDataset:
    source = SourceMetadata(
        path=Path("observations.csv"),
        file_name="observations.csv",
        file_extension=".csv",
        file_size_bytes=1,
    )

    table = LoadedTable(
        name="Observations",
        data=pd.DataFrame(
            {
                "category": ["A", "B", "A"],
                "value": [10.0, 20.0, 30.0],
            }
        ),
        source=source,
    )
    table.relation_name = "observations"

    return LoadedDataset(tables=[table])


def _analysis(dataset: LoadedDataset) -> DatasetAnalysisResult:
    return AnalysisResultBuilder().build(
        DatasetAnalysis(
            schema=SchemaInferer().infer_dataset(dataset),
            profile=DatasetProfile(tables=()),
            issues=(),
        )
    )


def test_provider_failure_during_planning_stops_investigation() -> None:
    """Planner provider failure must propagate through the real service."""

    dataset = _dataset()
    provider_error = GeminiGenerationError("Provider unavailable.")
    generation_client = FailingGenerationClient(provider_error)

    execution_service = AnalyticalExecutionService(
        dataset,
        planner=GenerativeQueryPlanner(generation_client),
    )

    investigator = SingleQuestionInvestigator("Count available records.")
    synthesizer = RecordingSynthesizer()

    orchestrator = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
        max_steps=3,
    )

    with pytest.raises(
        QueryPlanningError,
        match="Query planner text generation failed.",
    ) as exc_info:
        orchestrator.investigate(
            question="Investigate the available data.",
            analysis=_analysis(dataset),
        )

    assert exc_info.value.__cause__ is provider_error
    assert len(generation_client.prompts) == 1
    assert len(investigator.states) == 1
    assert investigator.states[0].failed_attempt_count == 0
    assert investigator.states[0].observation_count == 0
    assert synthesizer.states == []


def test_provider_failure_during_repair_stops_investigation() -> None:
    """Repair provider failure must propagate through the real service."""

    dataset = _dataset()
    provider_error = GeminiGenerationError("Provider unavailable.")

    planner_client = StaticGenerationClient("SELECT missing_metric FROM observations")
    repair_client = FailingGenerationClient(provider_error)

    execution_service = AnalyticalExecutionService(
        dataset,
        planner=GenerativeQueryPlanner(planner_client),
        repairer=GenerativeQueryRepairer(repair_client),
    )

    investigator = SingleQuestionInvestigator("Calculate the unavailable metric.")
    synthesizer = RecordingSynthesizer()

    orchestrator = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
        max_steps=3,
    )

    with pytest.raises(
        QueryPlanningError,
        match="Query repairer text generation failed.",
    ) as exc_info:
        orchestrator.investigate(
            question="Investigate the available data.",
            analysis=_analysis(dataset),
        )

    assert exc_info.value.__cause__ is provider_error
    assert len(planner_client.prompts) == 1
    assert len(repair_client.prompts) == 1
    assert len(investigator.states) == 1
    assert investigator.states[0].failed_attempt_count == 0
    assert investigator.states[0].observation_count == 0
    assert synthesizer.states == []


def test_successful_generation_executes_real_sql() -> None:
    """Successful generated SQL must execute against the real dataset."""

    dataset = _dataset()
    generation_client = StaticGenerationClient(
        "SELECT COUNT(*) AS record_count FROM observations"
    )

    execution_service = AnalyticalExecutionService(
        dataset,
        planner=GenerativeQueryPlanner(generation_client),
    )

    investigator = SingleQuestionInvestigator("Count available records.")
    synthesizer = RecordingSynthesizer()

    result = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
        max_steps=1,
    ).investigate(
        question="Investigate the available data.",
        analysis=_analysis(dataset),
    )

    assert len(generation_client.prompts) == 1
    assert result.observation_count == 1
    assert result.observations[0].sql == (
        "SELECT COUNT(*) AS record_count FROM observations"
    )
    assert result.observations[0].result.rows == ((3,),)
    assert result.conclusion == "Investigation completed."
    assert len(synthesizer.states) == 1
    assert synthesizer.states[0].failed_attempt_count == 0
