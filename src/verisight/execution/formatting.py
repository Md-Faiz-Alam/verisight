"""Formatting for analytical query context."""

from verisight.execution.context import QueryContext, QueryRelation


class QueryContextFormatter:
    """Format deterministic query context for analytical planning."""

    def format(self, context: QueryContext) -> str:
        """Format query context as deterministic planner-facing text."""

        sections = tuple(
            self._format_relation(relation) for relation in context.relations
        )

        return "\n\n".join(sections)

    @staticmethod
    def _format_relation(relation: QueryRelation) -> str:
        """Format one queryable relation."""

        columns = "\n".join(
            (
                f"- {column.name} | "
                f"{column.logical_type.value} | "
                f"{column.physical_dtype} | "
                f"nullable={str(column.nullable).lower()}"
            )
            for column in relation.columns
        )

        return (
            f"RELATION {relation.relation_name}\n"
            f"DISPLAY NAME: {relation.name}\n"
            f"ROWS: {relation.row_count}\n"
            f"COLUMNS:\n"
            f"{columns}"
        )
