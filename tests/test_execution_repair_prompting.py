from verisight.execution.context import (
    QueryColumn,
    QueryContext,
    QueryRelation,
)
from verisight.execution.repair import QueryRepairRequest
from verisight.execution.repair_prompting import QueryRepairPromptBuilder
from verisight.ingestion.schema import LogicalType


def _make_request() -> QueryRepairRequest:
    context = QueryContext(
        relations=(
            QueryRelation(
                name="Measurements",
                relation_name="measurements",
                row_count=3,
                columns=(
                    QueryColumn(
                        name="group_name",
                        physical_dtype="object",
                        logical_type=LogicalType.STRING,
                        nullable=False,
                    ),
                    QueryColumn(
                        name="value",
                        physical_dtype="float64",
                        logical_type=LogicalType.FLOAT,
                        nullable=False,
                    ),
                ),
            ),
        )
    )

    return QueryRepairRequest(
        question="Compare average value across groups.",
        failed_sql=(
            "SELECT group_name, AVG(missing_value) "
            "FROM measurements GROUP BY group_name"
        ),
        error=(
            'Binder Error: Referenced column "missing_value" not found in FROM clause'
        ),
        context=context,
    )


def test_builds_query_repair_prompt() -> None:
    prompt = QueryRepairPromptBuilder().build(_make_request())

    assert "analytical SQL repairer for VeriSight" in prompt
    assert "ORIGINAL QUESTION:\nCompare average value across groups." in prompt
    assert "FAILED SQL:" in prompt
    assert "AVG(missing_value)" in prompt
    assert "RUNTIME ERROR:" in prompt
    assert 'Referenced column "missing_value"' in prompt
    assert "RELATION measurements" in prompt
    assert "- value | float | float64 | nullable=false" in prompt


def test_repair_prompt_requires_safe_single_select() -> None:
    prompt = QueryRepairPromptBuilder().build(_make_request())

    assert "Generate exactly one SQL statement." in prompt
    assert "Generate only a read-only SELECT query." in prompt
    assert "Do not modify data or database state." in prompt
    assert "Do not access external files" in prompt


def test_repair_prompt_preserves_original_intent() -> None:
    prompt = QueryRepairPromptBuilder().build(_make_request())

    assert "Preserve the analytical intent of the original question" in prompt
    assert "Preserve the requested analytical grain" in prompt
    assert "Do not broaden the analysis" in prompt


def test_repair_prompt_requires_supported_schema() -> None:
    prompt = QueryRepairPromptBuilder().build(_make_request())

    assert "Use only the provided relations and columns." in prompt
    assert "Do not invent relation names, column names" in prompt


def test_repair_prompt_preserves_measure_semantics() -> None:
    prompt = QueryRepairPromptBuilder().build(_make_request())

    assert "Do not assume that numeric columns are additive." in prompt
    assert "Use weighting only when" in prompt
    assert "measure semantics are uncertain" in prompt


def test_repair_prompt_is_domain_agnostic() -> None:
    prompt = QueryRepairPromptBuilder().build(_make_request()).casefold()

    assert "sales" not in prompt
    assert "revenue" not in prompt
    assert "student" not in prompt
    assert "attendance" not in prompt
    assert "healthcare" not in prompt


def test_repair_prompt_is_deterministic() -> None:
    builder = QueryRepairPromptBuilder()
    request = _make_request()

    assert builder.build(request) == builder.build(request)
