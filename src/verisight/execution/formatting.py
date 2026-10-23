"""Formatting for analytical query context."""

import json

from verisight.execution.context import QueryContext, QueryRelation
from verisight.serialization import to_jsonable


class QueryContextFormatter:
    """Format deterministic query context for analytical planning."""

    def format(self, context: QueryContext) -> str:
        """Format query context as deterministic planner-facing text."""

        sections = tuple(
            self._format_relation(relation) for relation in context.relations
        )

        formatted = "\n\n".join(sections)
        if context.population:
            formatted += (
                "\n\nCALLER-ENFORCED RELATION POPULATION\n"
                "All filters are AND; values within each filter are OR. "
                "Applied before every query, including repair and comparison queries. "
                "Listed row counts describe the original loaded data, "
                "not this population. "
                "No excluded rows are available through these relations. "
                "Other relations retain their own scope. "
                "This does not verify the question's meaning.\n"
                + json.dumps(to_jsonable(context.population), ensure_ascii=False)
            )
        return formatted

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
