"""Deterministic query context for analytical execution."""

from dataclasses import dataclass

from verisight.execution.exceptions import QueryValidationError
from verisight.ingestion.schema import DatasetSchema, LogicalType


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
class QueryContext:
    """Deterministic description of relations available for querying."""

    relations: tuple[QueryRelation, ...]
    population: tuple[PopulationFilter, ...] = ()

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
