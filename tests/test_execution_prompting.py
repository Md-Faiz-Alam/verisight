from verisight.execution.context import (
    QueryColumn,
    QueryContext,
    QueryRelation,
)
from verisight.execution.planning import QueryRequest
from verisight.execution.prompting import QueryPromptBuilder
from verisight.ingestion.schema import LogicalType


def _make_request() -> QueryRequest:
    context = QueryContext(
        relations=(
            QueryRelation(
                name="Measurements",
                relation_name="measurements",
                row_count=3,
                columns=(
                    QueryColumn(
                        name="sample_id",
                        physical_dtype="int64",
                        logical_type=LogicalType.INTEGER,
                        nullable=False,
                    ),
                    QueryColumn(
                        name="reading",
                        physical_dtype="float64",
                        logical_type=LogicalType.FLOAT,
                        nullable=False,
                    ),
                ),
            ),
        )
    )

    return QueryRequest(
        question="What is the maximum reading?",
        context=context,
    )


def test_builds_query_planning_prompt() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert "analytical SQL planner for VeriSight" in prompt
    assert "QUESTION:\nWhat is the maximum reading?" in prompt
    assert "RELATION measurements" in prompt
    assert "DISPLAY NAME: Measurements" in prompt
    assert "- sample_id | integer | int64 | nullable=false" in prompt
    assert "- reading | float | float64 | nullable=false" in prompt


def test_prompt_requires_read_only_select_query() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert "exactly one read-only DuckDB SELECT query" in prompt
    assert "Return SQL only." in prompt
    assert "Do not modify data or database state." in prompt


def test_prompt_requires_exactly_one_sql_statement() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert "Return exactly one SQL statement." in prompt
    assert "Never return multiple semicolon-separated SQL statements." in prompt
    assert (
        "Do not emit separate SELECT statements for separate parts of "
        "the same analytical question."
    ) in prompt


def test_prompt_combines_related_computations_in_one_statement() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert (
        "If the analytical question requires multiple related "
        "computations, comparisons, groupings, or intermediate results"
    ) in prompt
    assert "combine them into one SQL statement" in prompt
    assert "without changing the meaning of the requested analysis" in prompt


def test_prompt_allows_single_statement_composition() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert "CTEs" in prompt
    assert "subqueries" in prompt
    assert "conditional aggregation" in prompt
    assert "window functions" in prompt
    assert "joins" in prompt
    assert "UNION" in prompt
    assert "UNION ALL" in prompt


def test_prompt_defines_ctes_as_single_statement() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert (
        "A WITH query containing one or more CTEs followed by one final "
        "SELECT is one SQL statement and is allowed."
    ) in prompt


def test_prompt_requires_meaningful_set_operations() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert (
        "UNION and UNION ALL may combine compatible result sets within "
        "the same SQL statement"
    ) in prompt
    assert "preserves clear and meaningful result semantics" in prompt


def test_prompt_does_not_distort_analysis_to_force_single_statement() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert (
        "Do not distort the requested analytical grain, aggregation, "
        "comparison, or interpretation merely to combine computations "
        "into one statement."
    ) in prompt


def test_prompt_handles_broad_questions_conservatively() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert (
        "If one statement cannot meaningfully represent every possible "
        "interpretation of a broad question"
    ) in prompt
    assert (
        "generate the single analytical query that directly answers the "
        "evidence request expressed by the question"
    ) in prompt
    assert "without inventing additional semantics" in prompt


def test_prompt_restricts_external_access() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert "Do not access external files" in prompt
    assert "PRAGMA" in prompt
    assert "ATTACH" in prompt
    assert "COPY" in prompt


def test_prompt_requires_semantically_correct_analytical_operations() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert (
        "Choose analytical operations according to the meaning of the "
        "question and the available evidence"
    ) in prompt
    assert (
        "not merely according to a column's physical or logical data type"
    ) in prompt


def test_prompt_requires_requested_analytical_grain() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert (
        "Determine the analytical grain required by the question before "
        "choosing SELECT expressions, aggregates, and GROUP BY columns."
    ) in prompt
    assert (
        "GROUP BY only the dimensions required to define that requested result grain."
    ) in prompt


def test_prompt_rejects_grouping_by_aggregated_measure() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert (
        "Do not place an aggregated measure itself in GROUP BY merely "
        "to make the SQL valid."
    ) in prompt
    assert (
        "A column used as the argument of an aggregate such as SUM, "
        "AVG, MIN, or MAX should not also be a grouping key"
    ) in prompt


def test_prompt_rejects_accidental_grain_fragmentation() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert (
        "Do not mix row-level columns with grouped aggregate results "
        "unless those columns are legitimate grouping dimensions"
    ) in prompt
    assert (
        "return the aggregate at that grain rather than including extra "
        "grouping columns that fragment the result into a finer grain."
    ) in prompt


def test_prompt_does_not_assume_numeric_columns_are_additive() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert (
        "Do not assume that a numeric column is additive merely because "
        "its values are numeric."
    ) in prompt
    assert (
        "Use SUM only when the measure is supported as additive across "
        "the rows or groups being combined"
    ) in prompt
    assert (
        "Do not sum a measure when doing so would produce a quantity "
        "with unsupported or unclear analytical meaning."
    ) in prompt


def test_prompt_requires_meaningful_average_semantics() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert (
        "Use AVG only when an arithmetic mean is meaningful for the "
        "measure and the analytical question."
    ) in prompt


def test_prompt_requires_supported_weighting_semantics() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert (
        "Do not assume that an unweighted average is equivalent to a weighted measure."
    ) in prompt
    assert (
        "Use a weighted calculation only when the required weighting "
        "quantities and their relationship to the measure are supported"
    ) in prompt


def test_prompt_allows_alternative_analytical_operations() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert "COUNT" in prompt
    assert "COUNT DISTINCT" in prompt
    assert "MIN" in prompt
    assert "MAX" in prompt
    assert "grouping" in prompt
    assert "filtering" in prompt
    assert "ordering" in prompt
    assert "returning unaggregated values" in prompt


def test_prompt_preserves_measure_semantic_distinctions() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert (
        "Preserve the distinction between additive, non-additive, and "
        "semantically uncertain measures."
    ) in prompt


def test_prompt_handles_uncertain_measure_semantics_conservatively() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert (
        "If the appropriate aggregation or interpretation of a measure is uncertain"
    ) in prompt
    assert "does not impose unsupported semantics" in prompt


def test_prompt_rejects_unsupported_domain_assumptions() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert (
        "Do not infer domain-specific meaning solely from a column name "
        "when the supplied context does not establish that meaning."
    ) in prompt
    assert (
        "Do not invent semantic metadata, units, weighting rules, "
        "relationships, categories, hierarchies, or domain assumptions"
    ) in prompt


def test_prompt_limits_query_to_requested_analysis() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    assert (
        "Generate only the computation required to answer the question; "
        "do not add unrelated analytical assumptions."
    ) in prompt


def test_prompt_is_domain_agnostic() -> None:
    prompt = QueryPromptBuilder().build(_make_request())

    domain_specific_examples = (
        "revenue",
        "sales amounts",
        "units sold",
        "discount_pct",
        "business cause",
        "student",
        "attendance",
        "course",
        "temperature",
        "humidity",
        "pressure",
        "service",
        "retry_count",
    )

    for example in domain_specific_examples:
        assert example not in prompt.lower()


def test_prompt_is_deterministic() -> None:
    builder = QueryPromptBuilder()
    request = _make_request()

    first_prompt = builder.build(request)
    second_prompt = builder.build(request)

    assert first_prompt == second_prompt


def test_builds_prompt_for_empty_context() -> None:
    request = QueryRequest(
        question="What data is available?",
        context=QueryContext(relations=()),
    )

    prompt = QueryPromptBuilder().build(request)

    assert "AVAILABLE DATA:\n\n\nQUESTION:" in prompt
    assert "QUESTION:\nWhat data is available?" in prompt
