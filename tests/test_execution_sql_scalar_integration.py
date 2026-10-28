"""Integration tests for real DuckDB SQL scalar serialization."""

import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock
from uuid import UUID

import pandas as pd
import pytest

from verisight import VeriSight
from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder, DatasetAnalysisResult
from verisight.config import Settings
from verisight.error_reporting import ErrorCode
from verisight.execution.exceptions import (
    QueryDataBindingError,
    QueryRuntimeError,
    QueryValidationError,
)
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.generative_investigator import GenerativeInvestigator
from verisight.execution.generative_synthesis import (
    GenerativeInvestigationSynthesizer,
)
from verisight.execution.investigation_formatting import (
    InvestigationStateFormatter,
)
from verisight.execution.investigation_result import InvestigationStatus
from verisight.execution.models import QueryResult, QueryScalar
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
from verisight.ingestion.service import DatasetLoader
from verisight.profiling.models import DatasetProfile
from verisight.public_api import run_public_operation
from verisight.serialization import to_jsonable


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
        ("TIME '10:30:00'", time(10, 30)),
        ("INTERVAL '1 day'", timedelta(days=1)),
        (
            "UUID '12345678-1234-5678-1234-567812345678'",
            UUID("12345678-1234-5678-1234-567812345678"),
        ),
        ("TRUE", True),
        ("CAST(1.25 AS DOUBLE)", 1.25),
        ("42", 42),
        ("'sample'", "sample"),
        ("NULL", None),
    ],
)
def test_real_duckdb_expressions_are_json_safe(
    expression: str,
    expected: QueryScalar,
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


@pytest.mark.parametrize("extension", ["csv", "json"])
@pytest.mark.parametrize(
    ("integer", "fraction"),
    [
        (9007199254740993, "0.5"),
        (-9007199254740993, "-0.25"),
        (9007199254740993, "2e-2"),
    ],
)
def test_mixed_large_integers_and_fractions_remain_exact_through_sql(
    tmp_path: Path, extension: str, integer: int, fraction: str
) -> None:
    path = tmp_path / f"measurements.{extension}"
    if extension == "csv":
        path.write_text(f"id,value\n1,{integer}\n2,{fraction}\n3,\n", encoding="utf-8")
    else:
        path.write_text(
            json.dumps(
                [
                    {"id": 1, "value": integer},
                    {"id": 2, "value": float(fraction)},
                    {"id": 3, "value": None},
                ]
            ),
            encoding="utf-8",
        )
    settings = Settings(gemini_api_key=None, allow_llm_data_disclosure=False)
    table = DatasetLoader(settings).load([path]).tables[0]
    assert Decimal(str(table.data.loc[0, "value"])) == Decimal(integer)
    original = table.data.copy(deep=True)
    service = AnalyticalExecutionService(LoadedDataset(tables=[table]))

    result = service.execute("SELECT value FROM measurements ORDER BY id")
    total = VeriSight(settings=settings).execute(
        path, "SELECT SUM(value) AS total FROM measurements"
    )

    assert result.rows == ((Decimal(integer),), (Decimal(fraction),), (None,))
    assert all(type(row[0]) is Decimal for row in result.rows[:2])
    assert total.rows == ((Decimal(integer) + Decimal(fraction),),)
    payload = json.loads(json.dumps(to_jsonable(result)))
    assert payload["rows"][2] == [None]
    pd.testing.assert_frame_equal(table.data, original)


def test_csv_preserves_fractional_digits_lost_by_float_conversion(
    tmp_path: Path,
) -> None:
    path = tmp_path / "measurements.csv"
    path.write_text("value\n0.12345678901234567\n0.5\n", encoding="utf-8")

    result = VeriSight(
        settings=Settings(gemini_api_key=None, allow_llm_data_disclosure=False)
    ).execute(path, "SELECT value FROM measurements ORDER BY value")

    assert result.rows == ((Decimal("0.12345678901234567"),), (Decimal("0.5"),))


@pytest.mark.parametrize(
    "values",
    [
        [Decimal("1e-38"), Decimal(0)],
        [Decimal("9" * 38), Decimal(0)],
        [Decimal("1.2300"), Decimal("0.5")],
        [2**100, 0],
        [0.1, 0.2],
        [Decimal("0E+1000000"), Decimal("0E-1000000")],
    ],
)
def test_explicit_decimal_binding_preserves_object_backed_numbers(
    values: list[int | float | Decimal],
) -> None:
    dataset = _dataset()
    dataset.tables[0].data = pd.DataFrame(
        {
            "row_id": [0, 1],
            'gross"amount': pd.Series(values, dtype=object),
            "adjustment": pd.Series([Decimal("0.125"), Decimal("0.25")], dtype=object),
        }
    )
    original = dataset.tables[0].data.copy(deep=True)

    result = AnalyticalExecutionService(dataset).execute(
        'SELECT "gross""amount", adjustment FROM observations ORDER BY row_id'
    )

    assert result.rows == (
        (Decimal(str(values[0])), Decimal("0.125")),
        (Decimal(str(values[1])), Decimal("0.25")),
    )
    assert all(type(value) is Decimal for row in result.rows for value in row)
    pd.testing.assert_frame_equal(dataset.tables[0].data, original)


@pytest.mark.parametrize("value", [Decimal("1e38"), Decimal("1e-39"), float("inf")])
@pytest.mark.parametrize(
    "query",
    [
        "SELECT value FROM observations",
        "SELECT safe_value FROM observations",
        "SELECT COUNT(*) FROM observations",
    ],
    ids=["numeric-column", "unrelated-column", "row-count"],
)
def test_exact_sql_binding_rejects_unsupported_precision_or_nonfinite_values(
    value: Decimal | float,
    query: str,
) -> None:
    dataset = _dataset()
    dataset.tables[0].data = pd.DataFrame(
        {"value": pd.Series([value], dtype=object), "safe_value": [7]}
    )
    original = dataset.tables[0].data.copy(deep=True)

    class Planner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(request.question, query)

    repairer = MagicMock()
    repairer.repair.side_effect = AssertionError(
        "Binding errors must not invoke SQL repair."
    )
    service = AnalyticalExecutionService(dataset, planner=Planner(), repairer=repairer)
    with pytest.raises(
        QueryDataBindingError, match="Object-backed numerical data"
    ) as caught:
        service.execute(query)
    assert isinstance(caught.value, QueryRuntimeError)
    with pytest.raises(QueryDataBindingError):
        service.run("Read the synthetic measurements.")
    public = run_public_operation(
        lambda: service.run("Read the synthetic measurements.")
    )
    assert public.error is not None
    assert public.error.code is ErrorCode.QUERY_RUNTIME_ERROR
    assert public.error.message == "The analytical query could not be executed."
    assert public.value is None
    repairer.repair.assert_not_called()
    pd.testing.assert_frame_equal(dataset.tables[0].data, original)


def test_large_integer_outside_sampling_range_remains_exact(tmp_path: Path) -> None:
    path = tmp_path / "measurements.json"
    path.write_text(
        json.dumps([{"value": 0.5}] * 10000 + [{"value": 9007199254740993}]),
        encoding="utf-8",
    )

    result = VeriSight(
        settings=Settings(gemini_api_key=None, allow_llm_data_disclosure=False)
    ).execute(path, "SELECT MAX(value) AS largest FROM measurements")

    assert result.rows == ((Decimal("9007199254740993"),),)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT histogram(value) FROM observations",
        "SELECT list(value) FROM observations",
        "SELECT struct_pack(metric := value) FROM observations LIMIT 1",
        "SELECT encode('private-binary-value') FROM observations LIMIT 1",
    ],
)
def test_unsupported_sql_values_raise_a_safe_execution_error(query: str) -> None:
    service = AnalyticalExecutionService(_dataset())

    with pytest.raises(QueryValidationError, match="unsupported result type") as caught:
        service.execute(query)

    assert "private-binary-value" not in str(caught.value)
    public = run_public_operation(lambda: service.execute(query))
    assert not public.succeeded
    assert public.value is None
    assert public.error is not None
    assert public.error.code is ErrorCode.QUERY_VALIDATION_ERROR
    assert "private-binary-value" not in public.error.message
    assert service.execute("SELECT COUNT(*) FROM observations").rows == ((3,),)


@pytest.mark.parametrize("has_prior_evidence", [False, True])
@pytest.mark.parametrize("recover", [False, True])
def test_unsupported_results_never_enter_investigation_evidence(
    tmp_path: Path, has_prior_evidence: bool, recover: bool
) -> None:
    path = tmp_path / "measurements.csv"
    path.write_text("value\n1\n1\n2\n", encoding="utf-8")
    questions = (["Get total"] if has_prior_evidence else []) + [
        "Get histogram",
        "Get grouped frequencies",
    ]
    decisions = [
        json.dumps(
            {"action": "investigate", "reasoning": "Collect evidence", "question": q}
        )
        for q in questions
    ]
    investigator_client = SequenceGenerationClient(decisions + [_finish_response()])
    queries = (
        ["SELECT SUM(value) AS total FROM measurements"] if has_prior_evidence else []
    ) + [
        "SELECT histogram(value) AS frequencies FROM measurements",
        "SELECT value, COUNT(*) AS frequency FROM measurements GROUP BY value "
        "ORDER BY value",
    ]
    planning_client = SequenceGenerationClient(queries)
    synthesis_client = RecordingGenerationClient(
        json.dumps(
            {
                "conclusion": "The highest frequency is 2.",
                "claims": [
                    {
                        "operation": "value",
                        "expected": "2",
                        "left": {
                            "observation_index": int(has_prior_evidence),
                            "row_index": 0,
                            "column": "frequency",
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

    result = app.investigate(
        path,
        "Inspect the value distribution.",
        max_steps=int(has_prior_evidence) + 1 + int(recover),
    )

    assert result.status is (
        InvestigationStatus.COMPLETE if recover else InvestigationStatus.INCOMPLETE
    )
    assert result.observation_count == int(has_prior_evidence) + int(recover)
    assert result.failed_attempt_count == 1
    assert result.failed_attempts[0].question == (
        "Inspect the value distribution."
        if not has_prior_evidence and not recover
        else "Get histogram"
    )
    assert result.failed_attempts[0].error_type == "QueryValidationError"
    assert all(
        "histogram" not in observation.sql for observation in result.observations
    )
    if has_prior_evidence:
        assert result.observations[0].result.rows == ((4,),)
    if recover:
        assert result.observations[-1].result.rows == ((1, 2), (2, 1))
        assert result.verified_claims[0].verification.status.value == "supported"
        assert result.verified_claims[0].verification.actual == Decimal(2)
    else:
        assert result.generated_claims == ()
        assert synthesis_client.prompts == []
    assert len(planning_client.prompts) == int(has_prior_evidence) + 1 + int(recover)
    payload = json.loads(json.dumps(to_jsonable(result)))
    assert len(payload["observations"]) == result.observation_count
    assert payload["failed_attempts"][0]["error_type"] == "QueryValidationError"
