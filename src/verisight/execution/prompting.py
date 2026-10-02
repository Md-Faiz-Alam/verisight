"""Prompt construction for analytical query planning."""

from verisight.execution.formatting import QueryContextFormatter
from verisight.execution.planning import QueryRequest


class QueryPromptBuilder:
    """Build deterministic prompts for analytical SQL planning."""

    def __init__(self) -> None:
        self._context_formatter = QueryContextFormatter()

    def build(self, request: QueryRequest) -> str:
        """Build a planner prompt from an analytical query request."""

        context = self._context_formatter.format(request.context)

        return (
            "You are an analytical SQL planner for VeriSight.\n\n"
            "Generate exactly one read-only DuckDB SELECT query that answers "
            "the user's question using only the relations and columns provided "
            "below.\n\n"
            "Rules:\n"
            "- Return SQL only.\n"
            "- Do not include Markdown code fences.\n"
            "- Use only the provided relations and columns.\n"
            "- Do not access external files, URLs, environment variables, "
            "or external databases.\n"
            "- Do not use PRAGMA, ATTACH, DETACH, COPY, INSTALL, LOAD, "
            "EXPORT, SET, RESET, CALL, or VACUUM.\n"
            "- Do not modify data or database state.\n\n"
            "AVAILABLE DATA:\n"
            f"{context}\n\n"
            "QUESTION:\n"
            f"{request.question}\n"
        )
