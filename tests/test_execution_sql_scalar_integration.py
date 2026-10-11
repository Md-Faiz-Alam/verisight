"""Integration tests for real DuckDB SQL scalar serialization."""

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder, DatasetAnalysisResult
from verisight.execution.generative_investigator import GenerativeInvestigator
from verisight.execution.generative_synthesis import (
    GenerativeInvestigationSynthesizer,
)
from verisight.execution.investigation_formatting import (
    InvestigationStateFormatter,
)
from verisight.execution.models import QueryResult
from verisight.execution.orchestration import InvestigationOrchestrator
from verisight.execution.planning import QueryPlan, QueryRequest
from verisight.execution.service import AnalyticalExecutionService
from verisight.ingestion.models import (
    LoadedDataset,
    LoadedTable,
    SourceMetadata,
)
from verisight.ingestion.schema import SchemaInferer
from verisight.profiling.models import DatasetProfile


class SequenceGenerationClient:
    """Return configured investigator responses and record prompts."""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)

        index = len(self.prompts) - 1

        if index >= len(self.responses):
            raise AssertionError("Unexpected investigator request.")

        return self.responses[index]


class RecordingGenerationClient:
    """Record synthesis prompts and return a deterministic conclusion."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class ScalarQueryPlanner:
    """Generate SQL returning real temporal and decimal DuckDB values."""

    def __init__(self) -> None:
        self.requests: list[QueryRequest] = []

    def plan(self, request: QueryRequest) -> QueryPlan:
        self.requests.append(request)

        return QueryPlan(
            question=request.question,
            sql=(
                "SELECT "
                "DATE '2026-01-15' AS report_date, "
                "TIMESTAMP '2026-01-15 10:30:00' AS created_at, "
                "CAST(1234.567890 AS DECIMAL(18, 6)) AS amount "
                "FROM observations LIMIT 1"
            ),
        )


def _dataset() -> LoadedDataset:
    """Create a small dataset registered as a real DuckDB relation."""

    source = SourceMetadata(
        path=Path("observations.csv"),
        file_name="observations.csv",
        file_extension=".csv",
        file_size_bytes=1,
    )

    table = LoadedTable(
        name="Observations",
        data=pd.DataFrame({"value": [1, 2, 3]}),
        source=source,
    )
    table.relation_name = "observations"

    return LoadedDataset(tables=[table])


def _analysis(dataset: LoadedDataset) -> DatasetAnalysisResult:
    """Build the deterministic analysis needed by the orchestrator."""

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
        '"reasoning":"Inspect temporal and decimal SQL results.",'
        '"question":"What are the date, timestamp, and amount?"}'
    )


def _finish_response() -> str:
    return (
        '{"action":"finish",'
        '"reasoning":"The SQL results provide sufficient evidence.",'
        '"question":null}'
    )


def test_real_duckdb_scalar_types_reach_synthesis_prompt() -> None:
    """Temporal and decimal values survive execution and prompt formatting."""

    dataset = _dataset()

    investigator_client = SequenceGenerationClient(
        [_investigate_response(), _finish_response()]
    )
    synthesis_client = RecordingGenerationClient(
        "The report date is January 15, 2026, and the amount is 1234.567890."
    )
    planner = ScalarQueryPlanner()

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
        question="Inspect SQL scalar serialization.",
        analysis=_analysis(dataset),
    )

    assert result.observation_count == 1
    assert len(planner.requests) == 1
    assert len(synthesis_client.prompts) == 1

    observation = result.observations[0]
    query_result = observation.result

    assert query_result.columns == (
        "report_date",
        "created_at",
        "amount",
    )
    assert query_result.rows == (
        (
            date(2026, 1, 15),
            datetime(2026, 1, 15, 10, 30),
            Decimal("1234.567890"),
        ),
    )

    synthesis_prompt = synthesis_client.prompts[0]

    assert "OBSERVATION 1" in synthesis_prompt
    assert "report_date" in synthesis_prompt
    assert "created_at" in synthesis_prompt
    assert "amount" in synthesis_prompt
    assert '["2026-01-15","2026-01-15T10:30:00","1234.567890"]' in synthesis_prompt


def test_real_duckdb_scalar_types_format_directly() -> None:
    """The formatter supports the exact types DuckDB returns."""

    result = QueryResult(
        columns=("report_date", "created_at", "amount"),
        rows=(
            (
                date(2026, 1, 15),
                datetime(2026, 1, 15, 10, 30),
                Decimal("1234.567890"),
            ),
        ),
    )

    formatted = InvestigationStateFormatter()._format_result(result)

    assert '["2026-01-15","2026-01-15T10:30:00","1234.567890"]' in formatted


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        (
            "DATE '2026-01-15'",
            date(2026, 1, 15),
        ),
        (
            "TIMESTAMP '2026-01-15 10:30:00'",
            datetime(2026, 1, 15, 10, 30),
        ),
        (
            "CAST(1234.567890 AS DECIMAL(18, 6))",
            Decimal("1234.567890"),
        ),
    ],
)
def test_real_duckdb_expressions_are_json_safe(
    expression: str,
    expected: date | datetime | Decimal,
) -> None:
    """Verify real DuckDB scalar values survive prompt formatting."""

    service = AnalyticalExecutionService(_dataset())

    query = f"SELECT {expression} AS value FROM observations LIMIT 1"

    result = service.execute(query)

    assert result.columns == ("value",)
    assert result.rows == ((expected,),)

    formatted = InvestigationStateFormatter()._format_result(result)

    assert "Columns: value" in formatted
    assert "Row count: 1" in formatted
    assert "Rows:" in formatted
