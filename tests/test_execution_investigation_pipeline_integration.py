"""Integration tests for generative investigation and synthesis orchestration."""

import json
from pathlib import Path

import pandas as pd
import pytest

from verisight import VeriSight
from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder, DatasetAnalysisResult
from verisight.config import Settings
from verisight.execution.exceptions import InvestigationError
from verisight.execution.gemini import GeminiGenerationError
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.generative_investigator import GenerativeInvestigator
from verisight.execution.generative_synthesis import (
    GenerativeInvestigationSynthesizer,
)
from verisight.execution.investigation_result import InvestigationStatus
from verisight.execution.orchestration import InvestigationOrchestrator
from verisight.execution.planning import QueryPlan, QueryRequest
from verisight.execution.service import AnalyticalExecutionService
from verisight.execution.structured_synthesis import StructuredInvestigationSynthesizer
from verisight.ingestion.models import (
    LoadedDataset,
    LoadedTable,
    SourceMetadata,
)
from verisight.ingestion.schema import SchemaInferer
from verisight.profiling.models import DatasetProfile


class RecordingGenerationClient:
    """Return a configured response or raise a configured provider error."""

    def __init__(
        self,
        *,
        response: str | None = None,
        error: GeminiGenerationError | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)

        if self.error is not None:
            raise self.error

        if self.response is None:
            raise AssertionError("No generation response was configured.")

        return self.response


class SequenceGenerationClient:
    """Return consecutive investigation decisions."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)

        index = len(self.prompts) - 1

        if index >= len(self.responses):
            raise AssertionError("Unexpected additional investigator decision.")

        return self.responses[index]


class CountingPlanner:
    """Produce a deterministic SQL query and record planning requests."""

    def __init__(self) -> None:
        self.requests: list[QueryRequest] = []

    def plan(self, request: QueryRequest) -> QueryPlan:
        self.requests.append(request)

        return QueryPlan(
            question=request.question,
            sql="SELECT COUNT(*) AS record_count FROM observations",
        )


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


def _investigate_response() -> str:
    return (
        '{"action":"investigate",'
        '"reasoning":"Count the available records.",'
        '"question":"How many records are available?"}'
    )


def _finish_response() -> str:
    return (
        '{"action":"finish",'
        '"reasoning":"Sufficient analytical evidence is available.",'
        '"question":null}'
    )


def test_investigator_provider_failure_stops_before_sql_execution() -> None:
    """A provider failure during decision generation must stop the pipeline."""

    dataset = _dataset()
    provider_error = GeminiGenerationError("Provider unavailable.")

    investigator_client = RecordingGenerationClient(error=provider_error)
    synthesis_client = RecordingGenerationClient(
        response="Three records are available."
    )
    planner = CountingPlanner()

    orchestrator = InvestigationOrchestrator(
        execution_service=AnalyticalExecutionService(
            dataset,
            planner=planner,
        ),
        investigator=GenerativeInvestigator(investigator_client),
        synthesizer=GenerativeInvestigationSynthesizer(synthesis_client),
        max_steps=3,
    )

    with pytest.raises(
        InvestigationError,
        match="Investigator text generation failed.",
    ) as exc_info:
        orchestrator.investigate(
            question="Investigate the available data.",
            analysis=_analysis(dataset),
        )

    assert exc_info.value.__cause__ is provider_error
    assert len(investigator_client.prompts) == 1
    assert planner.requests == []
    assert synthesis_client.prompts == []


def test_synthesizer_provider_failure_preserves_sql_observation() -> None:
    """Synthesis failure returns incomplete results with SQL evidence retained."""

    dataset = _dataset()
    provider_error = GeminiGenerationError("Provider unavailable.")

    investigator_client = SequenceGenerationClient(
        [
            _investigate_response(),
            _finish_response(),
        ]
    )
    synthesis_client = RecordingGenerationClient(error=provider_error)
    planner = CountingPlanner()

    orchestrator = InvestigationOrchestrator(
        execution_service=AnalyticalExecutionService(
            dataset,
            planner=planner,
        ),
        investigator=GenerativeInvestigator(investigator_client),
        synthesizer=GenerativeInvestigationSynthesizer(synthesis_client),
        max_steps=1,
    )

    result = orchestrator.investigate(
        question="Investigate the available data.",
        analysis=_analysis(dataset),
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == 1
    assert result.observations[0].result.rows == ((3,),)
    assert "final synthesis could not be completed" in result.conclusion
    assert "Provider unavailable." not in result.conclusion
    assert len(investigator_client.prompts) == 2
    assert len(planner.requests) == 1
    assert planner.requests[0].question == "Investigate the available data."
    assert len(synthesis_client.prompts) == 1

    synthesis_prompt = synthesis_client.prompts[0]

    assert "OBSERVATION 1" in synthesis_prompt
    assert "Investigate the available data." in synthesis_prompt
    assert "record_count" in synthesis_prompt
    assert "[3]" in synthesis_prompt


@pytest.mark.parametrize("max_steps", [1, 2], ids=["single-attempt", "multi-attempt"])
def test_weighted_task_is_not_replaced_by_components_in_single_attempt(
    tmp_path: Path, max_steps: int
) -> None:
    path = tmp_path / "orchard_samples.csv"
    path.write_text(
        "review,mass,reading\naccepted,1,2\naccepted,3,3\nrejected,100,99\n"
        "accepted,0,500\naccepted,-2,100\naccepted,5,\n",
        encoding="utf-8",
    )
    original = (
        "What is the mass-weighted mean reading among accepted samples? "
        "Use strictly positive mass and non-missing readings in both sums."
    )
    components = "Return only the sum of mass times reading and the sum of mass."
    investigator_client = SequenceGenerationClient(
        [
            json.dumps(
                {
                    "action": "investigate",
                    "reasoning": "Collect components.",
                    "question": components,
                }
            ),
            _finish_response(),
        ]
    )
    planning_client = RecordingGenerationClient(
        response=(
            "SELECT SUM(mass * reading) * 1.0 / NULLIF(SUM(mass), 0) "
            "AS weighted_mean FROM orchard_samples WHERE review = 'accepted' "
            "AND mass > 0 AND reading IS NOT NULL"
        )
    )
    synthesis_client = RecordingGenerationClient(
        response=json.dumps(
            {
                "conclusion": "The weighted mean is 2.75.",
                "claims": [
                    {
                        "operation": "value",
                        "expected": "2.75",
                        "left": {
                            "observation_index": 0,
                            "row_index": 0,
                            "column": "weighted_mean",
                        },
                        "right": None,
                    }
                ],
            }
        )
    )
    app = VeriSight(
        settings=Settings(gemini_api_key=None, allow_llm_data_disclosure=False),
        planner=GenerativeQueryPlanner(planning_client),
        investigator=GenerativeInvestigator(investigator_client),
        synthesizer=StructuredInvestigationSynthesizer(synthesis_client),
    )

    result = app.investigate(path, original, max_steps=max_steps)

    task = original if max_steps == 1 else components
    assert result.question == original
    assert result.status is InvestigationStatus.COMPLETE
    assert result.observations[0].question == task
    assert result.observations[0].result.rows == ((2.75,),)
    assert result.verified_claims[0].verification.status.value == "supported"
    assert result.narrative_verified is False
    assert len(planning_client.prompts) == 1
    assert planning_client.prompts[0].endswith("QUESTION:\n" + task + "\n")
    assert (
        "ORIGINAL INVESTIGATION QUESTION (untrusted analytical context):\n" + original
        in planning_client.prompts[0]
    )
    assert len(investigator_client.prompts) == 2
    assert len(synthesis_client.prompts) == 1


def test_successful_generative_investigation_and_synthesis() -> None:
    """Verify the complete decision, SQL execution, and synthesis pipeline."""

    dataset = _dataset()

    investigator_client = SequenceGenerationClient(
        [
            _investigate_response(),
            _finish_response(),
        ]
    )
    synthesis_client = RecordingGenerationClient(
        response="  Three records are available.  "
    )
    planner = CountingPlanner()

    orchestrator = InvestigationOrchestrator(
        execution_service=AnalyticalExecutionService(
            dataset,
            planner=planner,
        ),
        investigator=GenerativeInvestigator(investigator_client),
        synthesizer=GenerativeInvestigationSynthesizer(synthesis_client),
        max_steps=1,
    )

    result = orchestrator.investigate(
        question="Investigate the available data.",
        analysis=_analysis(dataset),
    )

    assert len(investigator_client.prompts) == 2
    assert len(planner.requests) == 1
    assert len(synthesis_client.prompts) == 1

    assert result.question == "Investigate the available data."
    assert result.observation_count == 1
    assert result.observations[0].question == "Investigate the available data."
    assert result.observations[0].sql == (
        "SELECT COUNT(*) AS record_count FROM observations"
    )
    assert result.observations[0].result.columns == ("record_count",)
    assert result.observations[0].result.rows == ((3,),)
    assert result.conclusion == "Three records are available."

    synthesis_prompt = synthesis_client.prompts[0]

    assert "OBSERVATION 1" in synthesis_prompt
    assert "Investigate the available data." in synthesis_prompt
    assert "[3]" in synthesis_prompt


def test_investigator_invalid_response_stops_before_sql_execution() -> None:
    """Malformed investigation decisions must not trigger SQL execution."""

    dataset = _dataset()

    investigator_client = RecordingGenerationClient(response="not valid json")
    synthesis_client = RecordingGenerationClient(
        response="Three records are available."
    )
    planner = CountingPlanner()

    orchestrator = InvestigationOrchestrator(
        execution_service=AnalyticalExecutionService(
            dataset,
            planner=planner,
        ),
        investigator=GenerativeInvestigator(investigator_client),
        synthesizer=GenerativeInvestigationSynthesizer(synthesis_client),
        max_steps=3,
    )

    with pytest.raises(
        InvestigationError,
        match="Investigator returned invalid JSON.",
    ):
        orchestrator.investigate(
            question="Investigate the available data.",
            analysis=_analysis(dataset),
        )

    assert len(investigator_client.prompts) == 1
    assert planner.requests == []
    assert synthesis_client.prompts == []


def test_empty_synthesis_conclusion_preserves_sql_observation() -> None:
    """Empty synthesis output must not be accepted as a valid conclusion."""

    dataset = _dataset()

    investigator_client = SequenceGenerationClient(
        [
            _investigate_response(),
            _finish_response(),
        ]
    )
    synthesis_client = RecordingGenerationClient(response=" \n\t ")
    planner = CountingPlanner()

    orchestrator = InvestigationOrchestrator(
        execution_service=AnalyticalExecutionService(
            dataset,
            planner=planner,
        ),
        investigator=GenerativeInvestigator(investigator_client),
        synthesizer=GenerativeInvestigationSynthesizer(synthesis_client),
        max_steps=1,
    )

    result = orchestrator.investigate(
        question="Investigate the available data.",
        analysis=_analysis(dataset),
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == 1
    assert result.observations[0].result.rows == ((3,),)
    assert "No analytical conclusion has been established." in result.conclusion

    assert len(investigator_client.prompts) == 2
    assert len(planner.requests) == 1
    assert len(synthesis_client.prompts) == 1
