"""Recalculate an evidence-backed answer with a second, blind SQL query.

Matching a number to a SQL cell cannot show that the SQL answered the question.
A second query is planned from the question and dataset alone, without the
first SQL, its result or the conclusion, and the two numbers are compared. An
agreement is evidence, not proof: both queries can share the same mistake,
more so when one model writes both.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Literal

import sqlglot
from sqlglot import exp

from verisight.execution.analytical import AnalyticalQueryRunner
from verisight.execution.deadline import InvestigationDeadlineExceeded
from verisight.execution.exceptions import (
    QueryExecutionError,
    QueryPlanningError,
)
from verisight.execution.gemini import GeminiGenerationError
from verisight.execution.models import QueryResult
from verisight.execution.prompt_budget import PromptBudgetExceededError
from verisight.execution.validation import _population_terms

CROSS_CHECK_COLUMN = "cross_check_answer"
# Absorbs binary floating-point noise only; a rounded display does not agree.
_RELATIVE_TOLERANCE = Decimal("1e-9")

CROSS_CHECK_INSTRUCTION = (
    "INDEPENDENT CROSS-CHECK: work out this answer from scratch, using only the "
    "question and the data description. First decide which rows belong to the "
    "population, which column holds the measure, and which calculation the "
    "question asks for. If a join can repeat rows, make sure each entity is "
    "counted once. Do not add rows that are totals of other rows to their own "
    f"parts. Return exactly one row, with the final answer, unrounded, in a "
    f"numeric column named {CROSS_CHECK_COLUMN}. For a difference, that column "
    "holds the difference itself."
)


class CrossCheckStatus(StrEnum):
    """Outcome of comparing an answer with its independent recalculation."""

    AGREED = "agreed"
    DISAGREED = "disagreed"
    NOT_ASSESSED = "not_assessed"


CrossCheckReason = Literal[
    "values_match",
    "values_differ",
    "not_a_single_number",
    "multiple_claims",
    "query_failed",
    "provider_failed",
    "time_budget_exhausted",
]


@dataclass(frozen=True, slots=True)
class CrossCheck:
    """A second calculation of one answer, kept beside the original evidence.

    ``identical_sql`` is true when both queries are the same apart from column
    and table aliases, identifier quoting and the order of AND conditions. The
    second query then
    repeated the first formulation instead of reaching the number another way,
    so its agreement adds no independent evidence.
    """

    status: CrossCheckStatus
    reason: CrossCheckReason
    sql: str | None = None
    primary_value: Decimal | None = None
    independent_value: Decimal | None = None
    identical_sql: bool | None = None


class IndependentCrossChecker:
    """Plan, run and compare one blind recalculation of an answer."""

    def __init__(self, runner: AnalyticalQueryRunner) -> None:
        self._runner = runner

    def check(self, question: str, answer: Decimal, primary_sql: str) -> CrossCheck:
        """Compare ``answer`` with a query planned from ``question`` alone.

        ``primary_sql`` is used only after the second query has run, to record
        whether the two are the same. It never reaches the planner.
        """
        try:
            execution = self._runner.run(
                f"{question}\n\n{CROSS_CHECK_INSTRUCTION}", original_question=question
            )
        except InvestigationDeadlineExceeded:
            return _not_assessed("time_budget_exhausted")
        except GeminiGenerationError:
            return _not_assessed("provider_failed")
        except (
            PromptBudgetExceededError,
            QueryExecutionError,
            QueryPlanningError,
        ):
            return _not_assessed("query_failed")

        sql = execution.plan.sql
        identical = _canonical_sql(sql) == _canonical_sql(primary_sql)
        independent = _answer_cell(execution.result)
        if independent is None:
            return CrossCheck(
                status=CrossCheckStatus.NOT_ASSESSED,
                reason="not_a_single_number",
                sql=sql,
                primary_value=answer,
                identical_sql=identical,
            )
        agreed = _same_number(answer, independent)
        return CrossCheck(
            status=CrossCheckStatus.AGREED if agreed else CrossCheckStatus.DISAGREED,
            reason="values_match" if agreed else "values_differ",
            sql=sql,
            primary_value=answer,
            independent_value=independent,
            identical_sql=identical,
        )


def _not_assessed(reason: CrossCheckReason) -> CrossCheck:
    return CrossCheck(status=CrossCheckStatus.NOT_ASSESSED, reason=reason)


def _answer_cell(result: QueryResult) -> Decimal | None:
    """Return the one requested finite number, or None if it is not there."""
    if len(result.rows) != 1:
        return None
    named = [
        index
        for index, column in enumerate(result.columns)
        if column.casefold() == CROSS_CHECK_COLUMN
    ]
    if len(named) == 1:
        position = named[0]
    elif len(result.columns) == 1:
        position = 0
    else:
        return None
    cell = result.rows[0][position]
    if type(cell) not in (int, float, Decimal):
        return None
    value = Decimal(str(cell))
    return value if value.is_finite() else None


def _same_number(first: Decimal, second: Decimal) -> bool:
    margin = _RELATIVE_TOLERANCE * max(abs(first), abs(second))
    return abs(first - second) <= margin


def _number_sources(tree: exp.Expression) -> None:
    """Replace table aliases with positions, so their names cannot differ.

    Positions keep a table joined twice as two sources, so swapping their roles
    still reads as a different query. With one source, qualifiers are dropped.
    """
    sources = [
        node for node in tree.find_all(exp.Table, exp.Subquery) if node.alias_or_name
    ]
    positions: dict[str, str] = {}
    for node in sources:
        positions.setdefault(node.alias_or_name.casefold(), f"t{len(positions)}")
    for column in tree.find_all(exp.Column):
        position = positions.get(column.table.casefold())
        if position is not None:
            alone = len(positions) == 1
            column.set("table", None if alone else exp.to_identifier(position))
    for node in sources:
        node.set("alias", None)


def _canonical_sql(sql: str) -> str:
    """Render SQL without aliases, quoting or AND order, for comparison only."""
    tree = sqlglot.parse_one(sql, read="duckdb").transform(
        lambda node: node.this if isinstance(node, exp.Alias) else node
    )
    _number_sources(tree)
    for identifier in tree.find_all(exp.Identifier):
        identifier.set("quoted", False)
    # Deepest first, so each outer run of conditions sorts on settled text.
    for node in reversed(list(tree.find_all(exp.And))):
        if not isinstance(node.parent, exp.And):
            terms = _population_terms(node)
            terms.sort(key=lambda term: term.sql(dialect="duckdb"))
            node.replace(exp.and_(*terms))
    return tree.sql(dialect="duckdb")
