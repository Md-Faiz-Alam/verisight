import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.execution.decisions import (
    InvestigationAction,
    InvestigationDecision,
)
from verisight.execution.exceptions import InvestigationError
from verisight.execution.generative_investigator import (
    GenerativeInvestigator,
)
from verisight.execution.investigation import InvestigationState
from verisight.ingestion.schema import (
    ColumnSchema,
    DatasetSchema,
    LogicalType,
    TableSchema,
)
from verisight.profiling.models import DatasetProfile


class StubTextGenerationClient:
    """Deterministic generation client for investigator tests."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def _build_state(
    *,
    schema: DatasetSchema | None = None,
) -> InvestigationState:
    analysis = DatasetAnalysis(
        schema=schema if schema is not None else DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(),
    )

    return InvestigationState(
        question="Why did revenue decline?",
        analysis=AnalysisResultBuilder().build(analysis),
    )


def _build_sales_schema() -> DatasetSchema:
    return DatasetSchema(
        tables=(
            TableSchema(
                name="Sales",
                relation_name="sales",
                row_count=16,
                column_count=2,
                columns=(
                    ColumnSchema(
                        name="month",
                        physical_dtype="object",
                        logical_type=LogicalType.STRING,
                        nullable=False,
                        missing_count=0,
                    ),
                    ColumnSchema(
                        name="revenue",
                        physical_dtype="int64",
                        logical_type=LogicalType.INTEGER,
                        nullable=False,
                        missing_count=0,
                    ),
                ),
            ),
        ),
    )


def test_generative_investigator_builds_investigate_decision() -> None:
    client = StubTextGenerationClient(
        """
        {
            "action": "investigate",
            "reasoning": "Revenue should be compared over time.",
            "question": "What is total revenue by month?"
        }
        """
    )

    investigator = GenerativeInvestigator(client)

    decision = investigator.decide(_build_state())

    assert decision == InvestigationDecision(
        action=InvestigationAction.INVESTIGATE,
        reasoning="Revenue should be compared over time.",
        question="What is total revenue by month?",
    )


def test_generative_investigator_builds_finish_decision() -> None:
    client = StubTextGenerationClient(
        """
        {
            "action": "finish",
            "reasoning": "The available evidence is sufficient.",
            "question": null
        }
        """
    )

    investigator = GenerativeInvestigator(client)

    decision = investigator.decide(_build_state())

    assert decision == InvestigationDecision(
        action=InvestigationAction.FINISH,
        reasoning="The available evidence is sufficient.",
    )


def test_generative_investigator_builds_prompt_from_state() -> None:
    client = StubTextGenerationClient(
        """
        {
            "action": "finish",
            "reasoning": "No additional evidence is required.",
            "question": null
        }
        """
    )

    investigator = GenerativeInvestigator(client)
    investigator.decide(_build_state(schema=_build_sales_schema()))

    assert len(client.prompts) == 1

    prompt = client.prompts[0]

    assert "autonomous analytical investigator for VeriSight" in prompt
    assert "ORIGINAL QUESTION\nWhy did revenue decline?" in prompt
    assert "QUERYABLE DATASET STRUCTURE" in prompt
    assert "RELATION sales" in prompt
    assert (
        "- month | logical_type=string | physical_dtype=object | nullable=false"
    ) in prompt
    assert (
        "- revenue | logical_type=integer | physical_dtype=int64 | nullable=false"
    ) in prompt
    assert "EXECUTED OBSERVATIONS\nNone" in prompt


def test_generative_investigator_prompt_discourages_schema_discovery() -> None:
    client = StubTextGenerationClient(
        """
        {
            "action": "finish",
            "reasoning": "No additional evidence is required.",
            "question": null
        }
        """
    )

    investigator = GenerativeInvestigator(client)
    investigator.decide(_build_state(schema=_build_sales_schema()))

    prompt = client.prompts[0]

    assert (
        "Use that structure directly when deciding what evidence to request."
    ) in prompt
    assert (
        "Do not request exploratory schema-discovery questions merely to "
        "discover relation names, column names, column types, row counts, "
        "or the general shape of the dataset"
    ) in prompt
    assert (
        "Do not request raw row samples solely to learn what columns or relations exist"
    ) in prompt


def test_generative_investigator_propagates_invalid_response() -> None:
    client = StubTextGenerationClient("not valid json")
    investigator = GenerativeInvestigator(client)

    with pytest.raises(
        InvestigationError,
        match="Investigator returned invalid JSON.",
    ):
        investigator.decide(_build_state())
