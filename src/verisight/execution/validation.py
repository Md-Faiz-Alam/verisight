"""Validation for VeriSight analytical SQL execution."""

import re

import duckdb
import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError
from sqlglot.optimizer.scope import Scope, ScopeType, traverse_scope

from verisight.execution.context import (
    PopulationReview,
    PopulationWarning,
    QueryContext,
)
from verisight.execution.exceptions import (
    QueryRuntimeError,
    QueryValidationError,
)


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
    """Mask nested SQL block comments while preserving newlines."""

    index = start
    length = len(characters)
    depth = 0

    while index < length:
        if (
            characters[index] == "/"
            and index + 1 < length
            and characters[index + 1] == "*"
        ):
            characters[index] = " "
            characters[index + 1] = " "
            depth += 1
            index += 2
            continue

        if (
            characters[index] == "*"
            and index + 1 < length
            and characters[index + 1] == "/"
        ):
            characters[index] = " "
            characters[index + 1] = " "
            depth -= 1
            index += 2

            if depth == 0:
                return index

            continue

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


_BLOCKED_SCALAR_METADATA_FUNCTIONS = frozenset(
    {
        "current_setting",
        "current_schemas",
        "version",
    }
)


def validate_dataset_relations(
    query: str,
    allowed_relations: frozenset[str],
) -> None:
    """Restrict SQL relation sources to registered dataset tables."""

    try:
        expression = sqlglot.parse_one(
            query,
            read="duckdb",
            error_level="RAISE",
        )

        scopes = list(traverse_scope(expression))
        selected_sources = [scope.selected_sources for scope in scopes]
    except (OptimizeError, ParseError, ValueError, RecursionError) as exc:
        raise QueryValidationError(
            "Dataset access is not allowed: SQL analysis failed."
        ) from exc

    if not scopes:
        raise QueryValidationError(
            "Dataset access is not allowed: SQL scopes could not be resolved."
        )

    for function in expression.find_all(exp.Func):
        if isinstance(
            function,
            (
                exp.CurrentCatalog,
                exp.CurrentDatabase,
                exp.CurrentSchema,
                exp.CurrentSchemas,
                exp.CurrentUser,
                exp.SessionUser,
            ),
        ):
            raise QueryValidationError(
                "Dataset access is not allowed: internal metadata function."
            )

        if (
            isinstance(function, exp.Anonymous)
            and function.name.lower() in _BLOCKED_SCALAR_METADATA_FUNCTIONS
        ):
            raise QueryValidationError(
                "Dataset access is not allowed: internal metadata function."
            )

    for sources in selected_sources:
        for _, source in sources.values():
            if isinstance(source, Scope):
                if source.scope_type == ScopeType.UDTF and not isinstance(
                    source.expression,
                    (exp.Unnest, exp.Values),
                ):
                    raise QueryValidationError(
                        "Dataset access is not allowed: unsupported inline table."
                    )
                continue

            if not isinstance(source, exp.Table):
                raise QueryValidationError(
                    "Dataset access is not allowed: unsupported SQL source."
                )

            if isinstance(source.this, exp.GenerateSeries):
                if source.db or source.catalog:
                    raise QueryValidationError(
                        "Dataset access is not allowed: "
                        "schema-qualified table function."
                    )
                continue

            if not isinstance(source.this, exp.Identifier):
                raise QueryValidationError(
                    "Dataset access is not allowed: unauthorized table function."
                )

            if source.db or source.catalog:
                raise QueryValidationError(
                    "Dataset access is not allowed: schema-qualified relation."
                )

            if source.name.lower() not in allowed_relations:
                raise QueryRuntimeError(
                    "Analytical query execution failed: "
                    f"relation '{source.name}' is not registered."
                )


def _question_mentions_category(question: str, value: str) -> bool:
    """Exact case-insensitive words only; direct negative mentions are skipped."""
    if not value.strip():
        return False
    literal = re.escape(value)
    if not re.search(rf"(?<!\w){literal}(?!\w)", question, re.IGNORECASE):
        return False
    negative = (
        rf"\b(?:exclude|excluding|except|without|not|non[- ])\s*"
        rf"(?:all\s+)?['\"]?{literal}(?!\w)"
    )
    return not re.search(negative, question, re.IGNORECASE)


def _population_terms(expression: exp.Expression) -> list[exp.Expression]:
    """Only top-level conjunctions establish an explicit inclusion here."""
    pending = [expression]
    terms = []
    while pending:
        term = pending.pop()
        if isinstance(term, exp.Paren):
            pending.append(term.this)
        elif isinstance(term, exp.And):
            pending.extend((term.expression, term.this))
        else:
            terms.append(term)
    return terms


def review_population(
    question: str, sql: str, context: QueryContext
) -> PopulationReview:
    """Warn about a narrow category/filter mismatch without certifying SQL.

    Only one direct outer table is assessed. CTEs, joins, derived tables,
    ambiguous category mentions and complex uses of the target column are
    not assessed. Nested membership queries on other columns are supported.
    This is a lexical heuristic, not population inference or SQL rewriting.
    """
    unknown = PopulationReview("not_assessed")
    try:
        statements = sqlglot.parse(sql, read="duckdb")
    except ParseError:
        return unknown
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        return unknown
    query = statements[0]
    source = query.args.get("from_")
    if (
        query.args.get("with_")
        or query.args.get("joins")
        or not isinstance(source, exp.From)
        or not isinstance(source.this, exp.Table)
    ):
        return unknown
    table = source.this
    if table.args.get("db") or table.args.get("catalog"):
        return unknown
    categories = [
        item
        for item in context.observed_categories
        if item.relation.casefold() == table.name.casefold()
    ]
    candidates = [
        (item, value)
        for item in categories
        for value in item.observed_nonmissing_values
        if _question_mentions_category(question, value)
    ]
    # Multiple matches can be comparisons, overlapping labels or shared values.
    if len(candidates) != 1:
        return unknown
    item, value = candidates[0]
    policies = [
        policy
        for policy in context.population
        if policy.relation == item.relation and policy.column == item.column
    ]
    if any(policy.values == (value,) for policy in policies):
        return PopulationReview("no_warning_detected")

    def is_target(column: exp.Column) -> bool:
        return column.name.casefold() == item.column.casefold() and (
            not column.table
            or column.table.casefold() == table.alias_or_name.casefold()
        )

    where = query.args.get("where")
    terms = [] if where is None else _population_terms(where.this)
    # Do not confuse conditional aggregation, grouping or correlated use with
    # an absent filter. Never credit a same-name filter inside another scope.
    target_columns = [
        column for column in query.find_all(exp.Column) if is_target(column)
    ]
    simple_terms: list[exp.Expression] = []
    for term in terms:
        predicate = term.this if isinstance(term, exp.Not) else term
        if isinstance(predicate, (exp.EQ, exp.NEQ)) and not isinstance(term, exp.Not):
            pairs = (
                (predicate.this, predicate.expression),
                (predicate.expression, predicate.this),
            )
            if any(
                isinstance(column, exp.Column)
                and is_target(column)
                and isinstance(literal, exp.Literal)
                and literal.is_string
                for column, literal in pairs
            ):
                simple_terms.append(term)
        elif (
            isinstance(predicate, exp.In)
            and isinstance(predicate.this, exp.Column)
            and is_target(predicate.this)
            and not predicate.args.get("query")
            and all(
                isinstance(literal, exp.Literal) and literal.is_string
                for literal in predicate.expressions
            )
        ):
            simple_terms.append(term)
    covered = {
        id(column) for term in simple_terms for column in term.find_all(exp.Column)
    }
    if any(id(column) not in covered for column in target_columns):
        return unknown
    for term in simple_terms:
        if isinstance(term, exp.EQ):
            literal = (
                term.expression if isinstance(term.this, exp.Column) else term.this
            )
            if literal.this == value:
                return PopulationReview("no_warning_detected")
        elif (
            isinstance(term, exp.In)
            and len(term.expressions) == 1
            and term.expressions[0].this == value
        ):
            return PopulationReview("no_warning_detected")
    return PopulationReview(
        "review_required",
        (PopulationWarning(item.relation, item.column, value),),
    )
