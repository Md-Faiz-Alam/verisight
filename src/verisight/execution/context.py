"""Deterministic query context for analytical execution."""

from dataclasses import dataclass

from verisight.ingestion.schema import DatasetSchema, LogicalType


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

    @property
    def relation_count(self) -> int:
        """Return the number of queryable relations."""

        return len(self.relations)


class QueryContextBuilder:
    """Build analytical query context from an inferred dataset schema."""

    def build(self, schema: DatasetSchema) -> QueryContext:
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

        return QueryContext(relations=relations)
