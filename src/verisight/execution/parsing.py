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

    @classmethod
    def _require_sql(cls, sql: str) -> str:
        """Return one normalized SQL statement or reject invalid output."""

        normalized = sql.strip()

        if not normalized:
            raise QueryPlanningError("Query planner returned an empty SQL query.")

        cls._require_single_statement(normalized)

        return normalized

    @staticmethod
    def _require_single_statement(sql: str) -> None:
        """Reject multiple SQL statements while respecting quotes and comments."""

        in_single_quote = False
        in_double_quote = False
        in_line_comment = False
        in_block_comment = False
        statement_ended = False

        index = 0
        length = len(sql)

        while index < length:
            character = sql[index]
            next_character = sql[index + 1] if index + 1 < length else ""

            if in_line_comment:
                if character in "\r\n":
                    in_line_comment = False
                index += 1
                continue

            if in_block_comment:
                if character == "*" and next_character == "/":
                    in_block_comment = False
                    index += 2
                    continue

                index += 1
                continue

            if in_single_quote:
                if character == "'":
                    if next_character == "'":
                        index += 2
                        continue
                    in_single_quote = False

                index += 1
                continue

            if in_double_quote:
                if character == '"':
                    if next_character == '"':
                        index += 2
                        continue
                    in_double_quote = False

                index += 1
                continue

            if character == "-" and next_character == "-":
                in_line_comment = True
                index += 2
                continue

            if character == "/" and next_character == "*":
                in_block_comment = True
                index += 2
                continue

            if character.isspace():
                index += 1
                continue

            if statement_ended:
                raise QueryPlanningError(
                    "Query planner returned multiple SQL statements."
                )

            if character == "'":
                in_single_quote = True
                index += 1
                continue

            if character == '"':
                in_double_quote = True
                index += 1
                continue

            if character == ";":
                statement_ended = True

            index += 1
