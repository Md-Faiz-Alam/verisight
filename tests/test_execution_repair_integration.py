"""Integration tests for SQL repair and investigation recovery."""

from pathlib import Path

import pandas as pd

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.execution.decisions import (
    InvestigationAction,
    InvestigationDecision,
)
from verisight.execution.investigation import InvestigationState
from verisight.execution.orchestration import InvestigationOrchestrator
from verisight.execution.planning import QueryPlan, QueryRequest
from verisight.execution.repair import QueryRepairRequest
from verisight.execution.service import AnalyticalExecutionService
from verisight.ingestion.models import (
    LoadedDataset,
    LoadedTable,
    SourceMetadata,
)
from verisight.ingestion.schema import SchemaInferer
from verisight.profiling.models import DatasetProfile


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


class ScenarioPlanner:
    """Generate deterministic SQL for integration scenarios."""

    def plan(self, request: QueryRequest) -> QueryPlan:
        if request.question == "Calculate unavailable metric.":
            sql = "SELECT missing_metric FROM observations"
        else:
            sql = "SELECT COUNT(*) AS record_count FROM observations"

        return QueryPlan(
            question=request.question,
            sql=sql,
        )


class FailingRepairer:
    """Return an invalid repair to exercise repair exhaustion."""

    def __init__(self) -> None:
        self.requests: list[QueryRepairRequest] = []

    def repair(self, request: QueryRepairRequest) -> QueryPlan:
        self.requests.append(request)

        return QueryPlan(
            question=request.question,
            sql="SELECT still_missing FROM observations",
        )


class ScenarioInvestigator:
    """Choose an alternative question after a failed repair."""

    def __init__(self) -> None:
        self.states: list[InvestigationState] = []

    def decide(
        self,
        state: InvestigationState,
    ) -> InvestigationDecision:
        self.states.append(state)

        if state.observation_count:
            return InvestigationDecision(
                action=InvestigationAction.FINISH,
                reasoning="Successful evidence is available.",
            )

        if state.failed_attempt_count:
            return InvestigationDecision(
                action=InvestigationAction.INVESTIGATE,
                reasoning="Use an available measure instead.",
                question="Count available records.",
            )

        return InvestigationDecision(
            action=InvestigationAction.INVESTIGATE,
            reasoning="Investigate the requested measure.",
            question="Calculate unavailable metric.",
        )


class RecordingSynthesizer:
    """Capture the final evidence and failure history."""

    def __init__(self) -> None:
        self.states: list[InvestigationState] = []

    def synthesize(self, state: InvestigationState) -> str:
        self.states.append(state)
        return "Three records are available."


def test_failed_sql_repair_recovers_with_alternative_question() -> None:
    """Repair exhaustion must not terminate the investigation."""

    dataset = _dataset()
    repairer = FailingRepairer()

    execution_service = AnalyticalExecutionService(
        dataset,
        planner=ScenarioPlanner(),
        repairer=repairer,
    )

    analysis = AnalysisResultBuilder().build(
        DatasetAnalysis(
            schema=SchemaInferer().infer_dataset(dataset),
            profile=DatasetProfile(tables=()),
            issues=(),
        )
    )

    investigator = ScenarioInvestigator()
    synthesizer = RecordingSynthesizer()

    result = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
        max_steps=2,
    ).investigate(
        question="Investigate the available data.",
        analysis=analysis,
    )

    assert len(repairer.requests) == 1

    repair_request = repairer.requests[0]

    assert repair_request.question == "Calculate unavailable metric."
    assert repair_request.failed_sql == ("SELECT missing_metric FROM observations")
    assert "missing_metric" in repair_request.error

    assert result.observation_count == 1
    assert result.observations[0].question == "Count available records."
    assert result.observations[0].sql == (
        "SELECT COUNT(*) AS record_count FROM observations"
    )
    assert result.observations[0].result.rows == ((3,),)

    assert len(investigator.states) == 3

    recovered_state = investigator.states[1]

    assert recovered_state.failed_attempt_count == 1
    assert recovered_state.observation_count == 0

    failed_attempt = recovered_state.failed_attempts[0]

    assert failed_attempt.question == "Calculate unavailable metric."
    assert failed_attempt.error_type == "QueryRuntimeError"
    assert "still_missing" in failed_attempt.message

    final_state = synthesizer.states[0]

    assert final_state.failed_attempt_count == 1
    assert final_state.observation_count == 1
    assert result.conclusion == "Three records are available."
