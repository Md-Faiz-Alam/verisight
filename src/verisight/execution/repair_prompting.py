"""Prompt construction for analytical query repair."""

from verisight.execution.formatting import QueryContextFormatter
from verisight.execution.repair import QueryRepairRequest


class QueryRepairPromptBuilder:
    """Build deterministic prompts for analytical query repair."""

    def __init__(self) -> None:
        self._context_formatter = QueryContextFormatter()

    def build(self, request: QueryRepairRequest) -> str:
        """Build a repair prompt from a failed analytical query."""

        context = self._context_formatter.format(request.context)

        return (
            "You are an analytical SQL repairer for VeriSight.\n\n"
            "A previously generated DuckDB SELECT query failed during "
            "execution. Generate exactly one replacement read-only DuckDB "
            "SELECT query that answers the original analytical question.\n\n"
            "Use the failed SQL and runtime error only as evidence about what "
            "must be corrected. Preserve the analytical intent of the original "
            "question rather than blindly modifying the failed SQL.\n\n"
            "Rules:\n"
            "- Return SQL only.\n"
            "- Do not include Markdown code fences.\n"
            "- Generate exactly one SQL statement.\n"
            "- Generate only a read-only SELECT query.\n"
            "- Use only the provided relations and columns.\n"
            "- Do not invent relation names, column names, values, units, "
            "relationships, or semantic metadata.\n"
            "- Do not access external files, URLs, environment variables, "
            "or external databases.\n"
            "- Do not use PRAGMA, ATTACH, DETACH, COPY, INSTALL, LOAD, "
            "EXPORT, SET, RESET, CALL, or VACUUM.\n"
            "- Do not modify data or database state.\n"
            "- Correct the execution problem described by the runtime error.\n"
            "- Preserve the requested analytical grain unless changing it is "
            "necessary to make the query semantically correct.\n"
            "- Choose analytical operations according to the meaning implied "
            "by the question and supplied structure, not merely according to "
            "physical data type.\n"
            "- Do not assume that numeric columns are additive.\n"
            "- Use SUM, AVG, COUNT, MIN, MAX, DISTINCT, grouping, filtering, "
            "ordering, window functions, expressions, or other supported "
            "analytical operations only when appropriate for the question.\n"
            "- Do not assume that an unweighted average represents a weighted "
            "measure. Use weighting only when the required quantities and "
            "relationship are supported by the supplied data.\n"
            "- If measure semantics are uncertain, prefer a conservative "
            "interpretation that does not invent unsupported meaning.\n"
            "- Do not broaden the analysis beyond what is needed to answer "
            "the original question.\n\n"
            "AVAILABLE DATA:\n"
            f"{context}\n\n"
            "ORIGINAL QUESTION:\n"
            f"{request.question}\n\n"
            "FAILED SQL:\n"
            f"{request.failed_sql}\n\n"
            "RUNTIME ERROR:\n"
            f"{request.error}\n"
        )
