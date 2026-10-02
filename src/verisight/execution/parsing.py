"""Parsing for analytical query planner responses."""

import re

from verisight.execution.exceptions import QueryPlanningError

_SQL_FENCE_PATTERN = re.compile(
    r"^```sql[ \t]*\r?\n(?P<sql>.*?)\r?\n[ \t]*```$",
    re.IGNORECASE | re.DOTALL,
)

_GENERIC_FENCE_PATTERN = re.compile(
    r"^```[ \t]*\r?\n(?P<sql>.*?)\r?\n[ \t]*```$",
    re.DOTALL,
)

_EMPTY_SQL_FENCE_PATTERN = re.compile(
    r"^```sql[ \t]*\r?\n[ \t]*```$",
    re.IGNORECASE,
)

_EMPTY_GENERIC_FENCE_PATTERN = re.compile(
    r"^```[ \t]*\r?\n[ \t]*```$",
)


class QueryResponseParser:
    """Parse SQL from an analytical query planner response."""

    def parse(self, response: str) -> str:
        """Parse one SQL query from a planner response."""

        normalized = response.strip()

        if not normalized:
            raise QueryPlanningError("Query planner returned an empty response.")

        if (
            _EMPTY_SQL_FENCE_PATTERN.fullmatch(normalized) is not None
            or _EMPTY_GENERIC_FENCE_PATTERN.fullmatch(normalized) is not None
        ):
            raise QueryPlanningError("Query planner returned an empty SQL query.")

        sql_fence_match = _SQL_FENCE_PATTERN.fullmatch(normalized)

        if sql_fence_match is not None:
            return self._require_sql(sql_fence_match.group("sql"))

        generic_fence_match = _GENERIC_FENCE_PATTERN.fullmatch(normalized)

        if generic_fence_match is not None:
            return self._require_sql(generic_fence_match.group("sql"))

        if "```" in normalized:
            raise QueryPlanningError(
                "Query planner returned an invalid fenced response."
            )

        return self._require_sql(normalized)

    @staticmethod
    def _require_sql(sql: str) -> str:
        """Return normalized SQL or reject an empty SQL payload."""

        normalized = sql.strip()

        if not normalized:
            raise QueryPlanningError("Query planner returned an empty SQL query.")

        return normalized
