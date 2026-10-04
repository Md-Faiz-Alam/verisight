from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_prompting import (
    InvestigationPromptBuilder,
)
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation
from verisight.ingestion.schema import (
    ColumnSchema,
    DatasetSchema,
    LogicalType,
    TableSchema,
)
from verisight.profiling.models import DatasetProfile


def _build_state(
    *,
    observations: tuple[QueryObservation, ...] = (),
    schema: DatasetSchema | None = None,
    question: str = "How did the measurements change over time?",
) -> InvestigationState:
    analysis = DatasetAnalysis(
        schema=schema if schema is not None else DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(),
    )

    return InvestigationState(
        question=question,
        analysis=AnalysisResultBuilder().build(analysis),
        observations=observations,
    )


def _build_measurement_schema() -> DatasetSchema:
    return DatasetSchema(
        tables=(
            TableSchema(
                name="Measurements",
                relation_name="measurements",
                row_count=16,
                column_count=5,
                columns=(
                    ColumnSchema(
                        name="timestamp",
                        physical_dtype="object",
                        logical_type=LogicalType.STRING,
                        nullable=False,
                        missing_count=0,
                    ),
                    ColumnSchema(
                        name="location",
                        physical_dtype="object",
                        logical_type=LogicalType.STRING,
                        nullable=False,
                        missing_count=0,
                    ),
                    ColumnSchema(
                        name="reading",
                        physical_dtype="float64",
                        logical_type=LogicalType.FLOAT,
                        nullable=False,
                        missing_count=0,
                    ),
                    ColumnSchema(
                        name="sample_count",
                        physical_dtype="int64",
                        logical_type=LogicalType.INTEGER,
                        nullable=False,
                        missing_count=0,
                    ),
                    ColumnSchema(
                        name="quality_score",
                        physical_dtype="float64",
                        logical_type=LogicalType.FLOAT,
                        nullable=True,
                        missing_count=1,
                    ),
                ),
            ),
        ),
    )


def test_builds_investigation_prompt() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert "autonomous analytical investigator for VeriSight" in prompt
    assert "INVESTIGATION STATE:" in prompt
    assert "ORIGINAL QUESTION\nHow did the measurements change over time?" in prompt
    assert "DATASET SUMMARY" in prompt
    assert "QUERYABLE DATASET STRUCTURE" in prompt
    assert "EXECUTED OBSERVATIONS\nNone" in prompt


def test_prompt_defines_available_actions() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "- investigate: request exactly one additional analytical "
        "question whose result would provide useful evidence."
    ) in prompt

    assert (
        "- finish: stop investigating only when the available evidence "
        "adequately addresses the material analytical aspects of the "
        "original question"
    ) in prompt


def test_prompt_requires_completeness_before_finish() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert "Investigation completeness:" in prompt

    assert (
        "Before choosing finish, compare the original question with "
        "the evidence actually present in the executed observations."
    ) in prompt

    assert (
        "Identify the material analytical aspects explicitly requested "
        "by the original question"
    ) in prompt

    assert (
        "If a material aspect remains unanswered and a useful "
        "analytical question can still obtain relevant evidence from the "
        "available dataset, choose investigate rather than finish."
    ) in prompt


def test_prompt_requires_independent_aspect_coverage() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "Treat these aspects independently when they require different evidence."
    ) in prompt

    assert (
        "Evidence that adequately addresses one aspect does not "
        "automatically address another merely because the same columns "
        "appear in the result."
    ) in prompt


def test_prompt_requires_evidence_to_actually_address_an_aspect() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "Treat an aspect as addressed only when the executed "
        "observations contain evidence that actually answers it."
    ) in prompt

    assert (
        "Do not treat an analytical question as answered merely because an "
        "earlier requested question mentioned that aspect."
    ) in prompt


def test_prompt_does_not_treat_raw_columns_as_automatic_evidence() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "The presence of relevant columns or raw values in an "
        "observation is not by itself proof that a requested comparison"
    ) in prompt

    assert (
        "relationship, trend, distribution, ranking, or unusual-value "
        "analysis has been adequately investigated."
    ) in prompt


def test_prompt_requires_executed_evidence_not_unexecuted_computation() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "Judge sufficiency from what the executed result demonstrates, "
        "not merely from what could potentially be calculated or inferred "
        "from the returned rows by performing substantial new analysis."
    ) in prompt


def test_prompt_does_not_force_unnecessary_investigation() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "Do not continue investigating merely to accumulate more "
        "evidence when the material aspects of the original question are "
        "already adequately addressed."
    ) in prompt


def test_prompt_does_not_force_fixed_observation_count() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert "Do not require a fixed number of observations." in prompt

    assert (
        "A single observation can be sufficient when it directly and "
        "adequately answers the material aspects of the original question"
    ) in prompt

    assert "a broad multi-aspect question may require multiple observations." in prompt


def test_prompt_allows_finish_when_remaining_aspect_is_not_supported() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "If an unanswered aspect cannot be supported by the available "
        "relations, columns, or evidence, finishing is appropriate"
    ) in prompt

    assert "the final synthesis can state that limitation." in prompt


def test_completeness_rules_remain_domain_agnostic() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "Evaluate completeness from the original question, supplied "
        "dataset structure, and executed evidence."
    ) in prompt

    assert (
        "Do not use a domain-specific checklist or assume that particular "
        "analyses are required for every dataset."
    ) in prompt


def test_prompt_defines_smallest_sufficient_evidence_principle() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert "Evidence selection:" in prompt

    assert (
        "Seek the smallest sufficient and semantically appropriate "
        "evidence for the analytical aspect being investigated."
    ) in prompt


def test_prompt_prefers_direct_analytical_evidence() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "Prefer evidence whose result directly exposes the requested "
        "analytical property rather than requiring the final synthesizer "
        "to perform substantial unexecuted analytical computation"
    ) in prompt


def test_prompt_handles_comparison_evidence() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "For requested comparisons, seek evidence that makes the "
        "relevant groups, entities, periods, categories, or conditions "
        "meaningfully comparable"
    ) in prompt


def test_prompt_handles_distribution_and_variation_evidence() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "For requested distributions or variation, seek evidence that "
        "characterizes the relevant spread, frequencies, ranges, "
        "quantiles, extrema, or other semantically appropriate variation"
    ) in prompt


def test_prompt_handles_relationship_evidence() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "For requested relationships or associations, seek evidence "
        "that directly supports evaluating the relationship between the "
        "relevant variables."
    ) in prompt

    assert (
        "Co-occurrence of columns in raw rows alone "
        "does not automatically establish that the relationship has been "
        "adequately analyzed."
    ) in prompt


def test_prompt_handles_temporal_evidence() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "For requested temporal patterns, seek evidence that preserves "
        "or summarizes the relevant time ordering and analytical grain"
    ) in prompt


def test_prompt_handles_unusual_value_evidence() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "For requested unusual values or extremes, seek evidence that "
        "makes potentially unusual or extreme observations identifiable "
        "relative to an appropriate reference"
    ) in prompt


def test_prompt_does_not_force_aggregation() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert "Do not force aggregation." in prompt

    assert (
        "Unaggregated or row-level evidence "
        "is appropriate when individual observations, exact records, "
        "sequences, small result sets, or other row-level details are "
        "themselves the evidence needed"
    ) in prompt


def test_prompt_allows_one_query_to_cover_multiple_aspects() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "Do not force separate queries for aspects that can be answered "
        "clearly and semantically correctly by one compact analytical "
        "result."
    ) in prompt


def test_prompt_does_not_use_dataset_size_as_evidence_policy() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "Do not request the entire dataset merely because it is small "
        "if a more focused analytical result would answer the requested "
        "aspect more directly."
    ) in prompt

    assert (
        "Dataset size alone does not determine the "
        "appropriate analytical evidence shape."
    ) in prompt


def test_prompt_preserves_valid_raw_evidence() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "do not reject raw or detailed evidence merely "
        "because an aggregated representation is possible."
    ) in prompt

    assert (
        "Choose the "
        "representation that best preserves the meaning required by the "
        "original question."
    ) in prompt


def test_prompt_requires_strict_json_response() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert "Return exactly one JSON object and nothing else." in prompt
    assert '"action": "investigate" | "finish"' in prompt
    assert '"reasoning": "string"' in prompt
    assert '"question": "string" | null' in prompt
    assert "Do not use Markdown code fences." in prompt


def test_prompt_separates_investigation_from_sql_planning() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert "Do not generate SQL." in prompt

    assert (
        "Another VeriSight component is responsible for SQL planning "
        "and safe execution."
    ) in prompt


def test_prompt_requires_evidence_grounded_reasoning() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert "Do not invent evidence" in prompt

    assert (
        "Do not invent relation names, column names, values, trends, "
        "causes, correlations, or conclusions."
    ) in prompt

    assert (
        "Treat data-quality findings as constraints on interpretation, "
        "not as proof of the phenomenon being investigated."
    ) in prompt


def test_prompt_requires_causal_uncertainty() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "Distinguish observed evidence from possible explanations. "
        "Do not claim causation unless the available evidence supports "
        "a causal conclusion."
    ) in prompt


def test_prompt_declares_domain_agnostic_behavior() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert "VeriSight is domain-agnostic." in prompt

    assert (
        "Do not assume that the dataset belongs to any particular "
        "business, scientific, operational, financial, medical, "
        "technical, or other domain"
    ) in prompt

    assert (
        "Treat column names as evidence about available fields, not as "
        "sufficient proof of domain semantics."
    ) in prompt


def test_prompt_includes_queryable_dataset_structure() -> None:
    prompt = InvestigationPromptBuilder().build(
        _build_state(schema=_build_measurement_schema())
    )

    assert "QUERYABLE DATASET STRUCTURE" in prompt
    assert "RELATION measurements" in prompt
    assert "Display name: Measurements" in prompt
    assert "Rows: 16" in prompt

    assert (
        "- timestamp | logical_type=string | physical_dtype=object | nullable=false"
    ) in prompt

    assert (
        "- location | logical_type=string | physical_dtype=object | nullable=false"
    ) in prompt

    assert (
        "- reading | logical_type=float | physical_dtype=float64 | nullable=false"
    ) in prompt

    assert (
        "- sample_count | logical_type=integer | physical_dtype=int64 | nullable=false"
    ) in prompt

    assert (
        "- quality_score | logical_type=float | physical_dtype=float64 | nullable=true"
    ) in prompt


def test_prompt_requires_using_supplied_dataset_structure() -> None:
    prompt = InvestigationPromptBuilder().build(
        _build_state(schema=_build_measurement_schema())
    )

    assert (
        "Use that structure directly when deciding what evidence to request." in prompt
    )

    assert (
        "Use only relations and columns present in QUERYABLE DATASET "
        "STRUCTURE when formulating analytical questions."
    ) in prompt


def test_prompt_discourages_schema_discovery_questions() -> None:
    prompt = InvestigationPromptBuilder().build(
        _build_state(schema=_build_measurement_schema())
    )

    assert (
        "Do not request exploratory schema-discovery questions merely to "
        "discover relation names, column names, column types, row counts, "
        "or the general shape of the dataset"
    ) in prompt

    assert (
        "Do not request raw row samples solely to learn what columns or relations exist"
    ) in prompt


def test_prompt_prioritizes_evidence_seeking_questions() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "Prefer questions that directly test, quantify, compare, "
        "disaggregate, or otherwise obtain evidence relevant to the "
        "original question."
    ) in prompt


def test_prompt_requires_semantic_analytical_questions() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "Formulate analytical questions according to the meaning of "
        "the requested evidence, not merely according to column data "
        "types."
    ) in prompt


def test_prompt_does_not_assume_numeric_measures_are_additive() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "Do not assume that a numeric measure is additive merely "
        "because its values are numeric."
    ) in prompt

    assert (
        "Request totals or sums only when the measure is supported as "
        "additive across the relevant rows or groups."
    ) in prompt

    assert (
        "Do not request a sum when the resulting quantity would have "
        "unsupported or unclear analytical meaning."
    ) in prompt


def test_prompt_requires_meaningful_average_semantics() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "Request an arithmetic mean only when averaging is meaningful "
        "for the measure and the analytical question."
    ) in prompt


def test_prompt_distinguishes_unweighted_and_weighted_analysis() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "Do not assume that an unweighted average represents a weighted measure."
    ) in prompt

    assert (
        "Request weighted analysis only when the necessary "
        "weighting quantities and their relationship to the measure are "
        "supported"
    ) in prompt


def test_prompt_allows_alternative_evidence_operations() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert "counts" in prompt
    assert "distinct counts" in prompt
    assert "extrema" in prompt
    assert "distributions" in prompt
    assert "group comparisons" in prompt
    assert "filtering" in prompt
    assert "ordering" in prompt
    assert "unaggregated values" in prompt


def test_prompt_handles_mixed_measure_questions() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert "When one investigation question includes multiple measures" in prompt

    assert (
        "allow each measure to use the analytical treatment appropriate "
        "to its own semantics."
    ) in prompt


def test_prompt_handles_uncertain_aggregation_semantics() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "If the appropriate aggregation or interpretation of a measure is uncertain"
    ) in prompt

    assert "does not impose unsupported semantics" in prompt


def test_prompt_rejects_unsupported_domain_assumptions() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "Do not infer domain-specific meaning solely from column names "
        "when the supplied evidence does not establish that meaning."
    ) in prompt

    assert (
        "Do not invent semantic metadata, units, weighting rules, "
        "relationships, categories, hierarchies, or domain assumptions"
    ) in prompt


def test_prompt_includes_existing_observations() -> None:
    observation = QueryObservation(
        question="What is the maximum reading by location?",
        sql=(
            "SELECT location, MAX(reading) AS maximum_reading "
            "FROM measurements GROUP BY location"
        ),
        result=QueryResult(
            columns=("location", "maximum_reading"),
            rows=(
                ("Site A", 18.5),
                ("Site B", 21.0),
            ),
        ),
    )

    prompt = InvestigationPromptBuilder().build(
        _build_state(
            observations=(observation,),
            schema=_build_measurement_schema(),
        )
    )

    assert "OBSERVATION 1" in prompt
    assert "Question: What is the maximum reading by location?" in prompt

    assert (
        "SELECT location, MAX(reading) AS maximum_reading "
        "FROM measurements GROUP BY location"
    ) in prompt

    assert '["Site A",18.5]' in prompt
    assert '["Site B",21.0]' in prompt


def test_prompt_discourages_repeating_executed_questions() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    assert (
        "Do not repeat an analytical question that has already been executed" in prompt
    )


def test_prompt_does_not_embed_sales_specific_guidance() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    sales_specific_guidance = (
        "revenue",
        "sales amounts",
        "units_sold",
        "discount_pct",
        "business cause",
    )

    for phrase in sales_specific_guidance:
        assert phrase not in prompt.lower()


def test_prompt_does_not_embed_education_specific_guidance() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    education_specific_guidance = (
        "student",
        "course",
        "attendance",
        "assessment",
        "max_score",
    )

    for phrase in education_specific_guidance:
        assert phrase not in prompt.lower()


def test_prompt_does_not_embed_operations_specific_guidance() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    operations_specific_guidance = (
        "service",
        "event_type",
        "retry_count",
        "duration_ms",
        "status",
    )

    for phrase in operations_specific_guidance:
        assert phrase not in prompt.lower()


def test_prompt_does_not_embed_environment_specific_guidance() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    environment_specific_guidance = (
        "temperature",
        "humidity",
        "pressure",
        "station",
        "weather",
    )

    for phrase in environment_specific_guidance:
        assert phrase not in prompt.lower()


def test_prompt_does_not_embed_domain_specific_completion_requirements() -> None:
    prompt = InvestigationPromptBuilder().build(_build_state())

    domain_specific_requirements = (
        "revenue by",
        "performance by course",
        "performance by student",
        "attendance relationship",
        "customer segment",
        "patient outcome",
        "inventory turnover",
    )

    for phrase in domain_specific_requirements:
        assert phrase not in prompt.lower()


def test_prompt_is_deterministic() -> None:
    builder = InvestigationPromptBuilder()
    state = _build_state(schema=_build_measurement_schema())

    first_prompt = builder.build(state)
    second_prompt = builder.build(state)

    assert first_prompt == second_prompt
