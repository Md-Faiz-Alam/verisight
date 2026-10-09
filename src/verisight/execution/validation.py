"""Validation for VeriSight analytical SQL execution."""

import re

import duckdb

from verisight.execution.exceptions import QueryValidationError


def _blocked_function_pattern(name: str) -> re.Pattern[str]:
    """Match unquoted or double-quoted calls to a blocked function."""

    escaped_name = re.escape(name)

    return re.compile(
        rf'(?:\b{escaped_name}|"{escaped_name}")\s*\(',
        re.IGNORECASE,
    )


_BLOCKED_SELECT_PATTERNS = tuple(
    _blocked_function_pattern(name)
    for name in (
        "read_csv",
        "read_csv_auto",
        "read_parquet",
        "read_json",
        "read_json_auto",
        "read_blob",
        "read_text",
        "read_ndjson",
        "read_ndjson_auto",
        "glob",
        "getenv",
    )
)

_PRAGMA_PATTERN = re.compile(
    r"^\s*pragma\b",
    re.IGNORECASE,
)


def _mask_sql_literals_and_comments(query: str) -> str:
    """Mask SQL literals and comments while preserving query structure."""

    characters = list(query)
    index = 0
    length = len(characters)

    while index < length:
        character = characters[index]

        if character == "'":
            index = _mask_single_quoted_literal(characters, index)
            continue

        if character == "-" and index + 1 < length and characters[index + 1] == "-":
            index = _mask_line_comment(characters, index)
            continue

        if character == "/" and index + 1 < length and characters[index + 1] == "*":
            index = _mask_block_comment(characters, index)
            continue

        index += 1

    return "".join(characters)


def _mask_single_quoted_literal(
    characters: list[str],
    start: int,
) -> int:
    """Mask one single-quoted SQL literal."""

    index = start
    length = len(characters)

    characters[index] = " "
    index += 1

    while index < length:
        if characters[index] == "'":
            characters[index] = " "

            if index + 1 < length and characters[index + 1] == "'":
                characters[index + 1] = " "
                index += 2
                continue

            return index + 1

        if characters[index] not in "\r\n":
            characters[index] = " "

        index += 1

    return index


def _mask_line_comment(
    characters: list[str],
    start: int,
) -> int:
    """Mask one SQL line comment."""

    index = start
    length = len(characters)

    while index < length and characters[index] not in "\r\n":
        characters[index] = " "
        index += 1

    return index


def _mask_block_comment(
    characters: list[str],
    start: int,
) -> int:
    """Mask one SQL block comment."""

    index = start
    length = len(characters)

    while index < length:
        if (
            characters[index] == "*"
            and index + 1 < length
            and characters[index + 1] == "/"
        ):
            characters[index] = " "
            characters[index + 1] = " "
            return index + 2

        if characters[index] not in "\r\n":
            characters[index] = " "

        index += 1

    return index


class AnalyticalQueryValidator:
    """Validate SQL against VeriSight's analytical execution boundary."""

    def validate(self, query: str) -> None:
        """Validate that a query is a single contained analytical statement."""

        if not query.strip():
            raise QueryValidationError("Analytical query must not be empty.")

        try:
            statements = duckdb.extract_statements(query)
        except duckdb.Error as exc:
            raise QueryValidationError(
                f"Analytical query validation failed: {exc}"
            ) from exc

        if len(statements) != 1:
            raise QueryValidationError(
                "Analytical execution requires exactly one SQL statement."
            )

        statement = statements[0]

        if statement.type != duckdb.StatementType.SELECT:
            raise QueryValidationError(
                "Only read-only analytical SELECT queries are allowed."
            )

        masked_query = _mask_sql_literals_and_comments(query)

        if _PRAGMA_PATTERN.search(masked_query):
            raise QueryValidationError(
                "PRAGMA statements are not allowed in analytical queries."
            )

        for pattern in _BLOCKED_SELECT_PATTERNS:
            if pattern.search(masked_query):
                raise QueryValidationError(
                    "External data access is not allowed in analytical queries."
                )
