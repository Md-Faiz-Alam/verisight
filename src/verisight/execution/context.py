"""Deterministic query context for analytical execution."""

import json
from dataclasses import asdict, dataclass, field, replace
from typing import Literal

import pandas as pd

from verisight.execution.exceptions import QueryValidationError
from verisight.ingestion.models import LoadedDataset
from verisight.ingestion.schema import DatasetSchema, LogicalType, SchemaInferer
from verisight.quality.totals import find_total_rows


@dataclass(frozen=True, slots=True)
class PopulationWarning:
    """A lexical scope concern, not proof that a query is analytically wrong."""

    relation: str
    column: str
    mentioned_value: str
    code: str = "question_category_not_explicitly_selected"


@dataclass(frozen=True, slots=True)
class PopulationReview:
    """Advisory only; no status certifies task semantics or changes acceptance."""

    status: Literal["not_assessed", "review_required", "no_warning_detected"]
    warnings: tuple[PopulationWarning, ...] = ()
    task_semantics_verified: bool = False


@dataclass(frozen=True, slots=True)
class CountingGrainReview:
    """A bounded counting diagnostic; no status certifies identity semantics."""

    status: Literal["not_assessed", "review_required", "no_warning_detected"]
    warnings: tuple[Literal["row_counts_for_identity_request"], ...] = ()
    task_semantics_verified: bool = False


@dataclass(frozen=True, slots=True)
class PopulationFilter:
    """Caller-selected equality/membership filter; all supplied filters use AND.

    Values are homogeneous tuples of strings, booleans, or signed 64-bit
    integers. Nulls, implicit casts, arbitrary expressions, and dates are not
    supported. A one-value tuple is equality; larger tuples are membership.
    """

    relation: str
    column: str
    values: tuple[str | int | bool, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.relation, str) or not self.relation.strip():
            raise QueryValidationError("Population relation must be a nonblank string.")
        if not isinstance(self.column, str) or not self.column.strip():
            raise QueryValidationError("Population column must be a nonblank string.")
        if type(self.values) is not tuple or not self.values:
            raise QueryValidationError("Population values must be a nonempty tuple.")
        kind = type(self.values[0])
        if kind not in (str, int, bool) or any(
            type(v) is not kind for v in self.values
        ):
            raise QueryValidationError(
                "Population values must have one supported scalar type."
            )
        if any(isinstance(v, int) and not -(2**63) <= v < 2**63 for v in self.values):
            raise QueryValidationError(
                "Population integers must fit signed 64-bit values."
            )


def validate_population(
    population: tuple[PopulationFilter, ...], context: "QueryContext"
) -> None:
    """Reject invalid policies before model calls or registration.

    Identifiers must exactly match supplied schema names, without normalization.
    This is deliberately stricter than DuckDB's identifier resolution.
    """
    if type(population) is not tuple or any(
        type(item) is not PopulationFilter for item in population
    ):
        raise QueryValidationError(
            "Population must be a tuple of PopulationFilter objects."
        )
    relations = {item.relation_name: item for item in context.relations}
    supported = {
        str: LogicalType.STRING,
        int: LogicalType.INTEGER,
        bool: LogicalType.BOOLEAN,
    }
    for item in population:
        relation = relations.get(item.relation)
        if relation is None:
            raise QueryValidationError("Population relation is not available.")
        columns = {column.name: column for column in relation.columns}
        column = columns.get(item.column)
        if column is None:
            raise QueryValidationError("Population column is not available.")
        if column.logical_type is not supported[type(item.values[0])]:
            raise QueryValidationError(
                "Population value type does not match a supported column type."
            )


@dataclass(frozen=True, slots=True)
class QueryColumn:
    """Column information exposed to an analytical query planner."""

    name: str
    physical_dtype: str
    logical_type: LogicalType
    nullable: bool


@dataclass(frozen=True, slots=True)
class QueryRelation:
    """Relation information exposed to an analytical query planner."""

    name: str
    relation_name: str
    row_count: int
    columns: tuple[QueryColumn, ...]


@dataclass(frozen=True, slots=True)
class ObservedCategoryValues:
    """Complete distinct nonmissing strings from one original loaded column.

    These are untrusted data values, not a category vocabulary or business rule.
    Missing columns are unknown: their values may have been omitted by limits.
    """

    relation: str
    column: str
    observed_nonmissing_values: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ObservedTotalRows:
    """Rows of one category value that hold the sum of the other rows.

    Detected from the original loaded data by matching sums within groups that
    share the ``group_by`` columns; an empty ``group_by`` means the whole table.
    This is untrusted evidence for planning, not a verified business rule.
    """

    relation: str
    column: str
    value: str
    measures: tuple[str, ...]
    group_by: tuple[str, ...]


_MAX_TOTAL_ROWS = 20
_MAX_YEAR_CODES = 20
_MAX_CODED_COLUMNS = 10


@dataclass(frozen=True, slots=True)
class ObservedCodedYears:
    """An integer column whose every value matches exactly one year of a date.

    Derived from the loaded rows, such as ``yr`` 0 holding only 2011 dates. It is
    evidence for planning, not a business rule.
    """

    relation: str
    column: str
    date_column: str
    years: tuple[tuple[int, int], ...]


def _coded_years(
    data: pd.DataFrame, relation: "QueryRelation"
) -> list[ObservedCodedYears]:
    dates = [
        column.name
        for column in relation.columns
        if column.logical_type is LogicalType.DATETIME
    ]
    found: list[ObservedCodedYears] = []
    for column in relation.columns:
        if column.logical_type is not LogicalType.INTEGER or not dates:
            continue
        counts = data[column.name].value_counts()
        codes = counts.index
        plain_years = all(1900 <= int(code) <= 2100 for code in codes)
        # A code repeats across rows; a measure that happens to be unique does not.
        if not 1 < len(codes) <= _MAX_YEAR_CODES or plain_years or counts.min() < 2:
            continue
        for date in dates:
            pairs = (
                pd.DataFrame({"code": data[column.name], "year": data[date].dt.year})
                .dropna()
                .drop_duplicates()
            )
            if (
                len(pairs) == len(codes)
                and pairs["code"].is_unique
                and pairs["year"].is_unique
            ):
                years = tuple(
                    sorted((int(code), int(year)) for code, year in pairs.to_numpy())
                )
                found.append(
                    ObservedCodedYears(relation.relation_name, column.name, date, years)
                )
                break
    return found


def _complete_string_values(
    series: pd.Series, limit: int = 8
) -> tuple[str, ...] | None:
    """Retain at most ``limit`` values of at most 128 characters; never sample."""
    values: set[str] = set()
    for value in series.dropna():
        if not isinstance(value, str) or len(value) > 128:
            return None
        values.add(value)
        if len(values) > limit:
            return None
    return tuple(sorted(values)) if values else None


# A column may list more values when they repeat, as codes and labels do. Mostly
# unique columns, such as names and identifiers, stay out of the prompt.
_REPEATING_VALUES_PER_COLUMN = 64


def _repeating_string_values(series: pd.Series) -> tuple[str, ...] | None:
    """Return up to 64 values if each appears at least twice on average."""
    values = _complete_string_values(series, _REPEATING_VALUES_PER_COLUMN)
    if values is None or 2 * len(values) > int(series.notna().sum()):
        return None
    return values


# Review-only category values: larger than the prompt list, never sent to a model.
_REVIEW_VALUES_PER_COLUMN = 200
_REVIEW_VALUES_BUDGET = 65_536


@dataclass(frozen=True, slots=True)
class QueryContext:
    """Deterministic description of relations available for querying."""

    relations: tuple[QueryRelation, ...]
    population: tuple[PopulationFilter, ...] = ()
    observed_categories: tuple[ObservedCategoryValues, ...] = ()
    total_rows: tuple[ObservedTotalRows, ...] = ()
    coded_years: tuple[ObservedCodedYears, ...] = ()
    # Complete value sets for advisory review only; never formatted into prompts.
    review_categories: tuple[ObservedCategoryValues, ...] = field(
        default=(), repr=False
    )

    @property
    def relation_count(self) -> int:
        """Return the number of queryable relations."""

        return len(self.relations)


class QueryContextBuilder:
    """Build analytical query context from an inferred dataset schema."""

    def build(
        self, schema: DatasetSchema, *, population: tuple[PopulationFilter, ...] = ()
    ) -> QueryContext:
        """Build deterministic query context from a dataset schema."""

        relations = tuple(
            QueryRelation(
                name=table.name,
                relation_name=table.relation_name,
                row_count=table.row_count,
                columns=tuple(
                    QueryColumn(
                        name=column.name,
                        physical_dtype=column.physical_dtype,
                        logical_type=column.logical_type,
                        nullable=column.nullable,
                    )
                    for column in table.columns
                ),
            )
            for table in schema.tables
        )

        context = QueryContext(relations=relations, population=population)
        validate_population(population, context)
        return context

    def build_from_dataset(
        self,
        dataset: LoadedDataset,
        *,
        population: tuple[PopulationFilter, ...] = (),
    ) -> QueryContext:
        """Include bounded categorical evidence without modifying or filtering data.

        The serialized category array is limited to 8,192 characters, including
        identifiers and JSON escaping. Individual columns are omitted in full
        when limits prevent a complete nonmissing value set. Small columns come
        first, then larger columns whose values repeat, within what is left. This
        bounds retained prompt context, not input size or the cost of scanning
        loaded columns.
        """
        context = self.build(
            SchemaInferer().infer_dataset(dataset), population=population
        )
        categories: list[ObservedCategoryValues] = []
        used = 2
        listed: set[tuple[str, str]] = set()
        for read_values in (_complete_string_values, _repeating_string_values):
            for table, relation in zip(dataset.tables, context.relations, strict=True):
                for column in relation.columns:
                    key = (relation.relation_name, column.name)
                    if column.logical_type is not LogicalType.STRING or key in listed:
                        continue
                    values = read_values(table.data[column.name])
                    if values is None:
                        continue
                    item = ObservedCategoryValues(
                        relation=relation.relation_name,
                        column=column.name,
                        observed_nonmissing_values=values,
                    )
                    size = len(json.dumps(asdict(item), ensure_ascii=False))
                    size += 2 * bool(categories)
                    if used + size > 8_192:
                        continue
                    categories.append(item)
                    listed.add(key)
                    used += size
        totals = [
            ObservedTotalRows(
                relation=relation.relation_name,
                column=found.column,
                value=found.value,
                measures=found.measures,
                group_by=found.keys,
            )
            for table, relation in zip(dataset.tables, context.relations, strict=True)
            for found in find_total_rows(table.data, relation.columns)
            if len(found.value) <= 128
        ][:_MAX_TOTAL_ROWS]
        review: list[ObservedCategoryValues] = []
        review_used = 0
        for table, relation in zip(dataset.tables, context.relations, strict=True):
            for column in relation.columns:
                if column.logical_type is not LogicalType.STRING:
                    continue
                values = _complete_string_values(
                    table.data[column.name], _REVIEW_VALUES_PER_COLUMN
                )
                if values is None:
                    continue
                review_used += sum(len(value) for value in values)
                if review_used > _REVIEW_VALUES_BUDGET:
                    break
                review.append(
                    ObservedCategoryValues(relation.relation_name, column.name, values)
                )
        coded = [
            item
            for table, relation in zip(dataset.tables, context.relations, strict=True)
            for item in _coded_years(table.data, relation)
        ][:_MAX_CODED_COLUMNS]
        return replace(
            context,
            observed_categories=tuple(categories),
            total_rows=tuple(totals),
            review_categories=tuple(review),
            coded_years=tuple(coded),
        )
