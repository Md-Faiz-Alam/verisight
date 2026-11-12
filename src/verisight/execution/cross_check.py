"""Recalculate an evidence-backed answer with a second, blind SQL query.

Matching a number to a SQL cell cannot show that the SQL answered the question.
A second query is planned from the question and dataset alone, without the
first SQL, its result or the conclusion, and the two numbers are compared. An
agreement is evidence, not proof: both queries can share the same mistake,
more so when one model writes both.
"""

import re
from dataclasses import dataclass
from decimal import Decimal, DecimalException
from enum import StrEnum
from typing import Literal

import sqlglot
from sqlglot import exp

from verisight.execution.analytical import AnalyticalQueryRunner
from verisight.execution.claim_verification import (
    MAX_ROUNDED_PLACES,
    DecimalRoundingPolicy,
    _round_for_policy,
)
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
# A column no calculation produces by accident: the second query declined.
CROSS_CHECK_REFUSAL_COLUMN = "cross_check_refused"
# Absorbs binary floating-point noise only; a rounded display does not agree.
_RELATIVE_TOLERANCE = Decimal("1e-9")
_PLACE_WORDS = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
    "ten",
    "eleven",
    "twelve",
]
_PLACES_ASKED = re.compile(
    rf"\b([0-9]{{1,2}}|{'|'.join(_PLACE_WORDS)})[ -](?:decimals?|places?|dp)\b",
    re.IGNORECASE,
)

CROSS_CHECK_INSTRUCTION = (
    "INDEPENDENT CROSS-CHECK: work out this answer from scratch, using only the "
    "question and the data description. First check that the data can answer "
    "it. If no column records the quantity asked for, or the columns record "
    "only a related but different quantity, do not substitute one and do not "
    "estimate from outside knowledge. If the answer depends on a grading word, "
    "group or comparison that neither the question nor the data defines, do not "
    "choose a definition. In either case return exactly "
    f"SELECT 'refused' AS {CROSS_CHECK_REFUSAL_COLUMN} and nothing else. Do not "
    "refuse because values are messy or missing, because a join is needed, or "
    "because the wording differs from a column that plainly holds the same "
    "thing. Otherwise decide which rows belong to the "
    "population, which column holds the measure, and which calculation the "
    "question asks for. If a join can repeat rows, make sure each entity is "
    "counted once. Do not add rows that are totals of other rows to their own "
    "parts. Reach the number by a less direct route than the most obvious query, "
    "while keeping exactly the same rows and meaning. Do not answer with a plain "
    "WHERE column = value filter around COUNT, SUM or AVG. For a filtered count "
    "or total, put the condition inside the aggregate, as SUM(CASE WHEN condition "
    "THEN 1 ELSE 0 END) or SUM(CASE WHEN condition THEN measure END). For an "
    "average, divide SUM(CASE WHEN condition THEN measure END) by "
    "COUNT(CASE WHEN condition THEN measure END). For a count of different "
    "values, count the rows of a "
    "SELECT DISTINCT subquery. Where a join only filters, use IN with a subquery. "
    "For a difference, calculate each side in its own subquery. If no such route "
    "fits, write the clearest correct query. "
    f"Return exactly one row, with the final answer, unrounded, in a "
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
    "second_query_refused",
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
    repeated the first formulation instead of reaching the number another way.

    ``single_route`` is recorded for a repeat only. It is true when the query
    reads one table with no join, grouping, subquery, distinct values or window,
    so no other route could test anything beyond the same choice of rows, column
    and calculation. ``separate_model`` is true when another model wrote the
    second query. A repeat counts as evidence only when both are true.
    """

    status: CrossCheckStatus
    reason: CrossCheckReason
    sql: str | None = None
    primary_value: Decimal | None = None
    independent_value: Decimal | None = None
    identical_sql: bool | None = None
    single_route: bool | None = None
    separate_model: bool | None = None


class IndependentCrossChecker:
    """Plan, run and compare one blind recalculation of an answer."""

    def __init__(
        self, runner: AnalyticalQueryRunner, *, separate_model: bool = False
    ) -> None:
        self._runner = runner
        self._separate_model = separate_model

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
        if _refused(execution.result):
            # The second model saw nothing in the data that holds what was asked.
            return CrossCheck(
                status=CrossCheckStatus.DISAGREED,
                reason="second_query_refused",
                sql=sql,
                primary_value=answer,
                identical_sql=False,
                separate_model=self._separate_model,
            )
        identical = _canonical_sql(sql) == _canonical_sql(primary_sql)
        single_route = _single_route(primary_sql) if identical else None
        independent = _answer_cell(execution.result)
        if independent is None:
            return CrossCheck(
                status=CrossCheckStatus.NOT_ASSESSED,
                reason="not_a_single_number",
                sql=sql,
                primary_value=answer,
                identical_sql=identical,
                single_route=single_route,
                separate_model=self._separate_model,
            )
        agreed = _same_number(answer, independent) or _same_when_rounded(
            question, answer, independent
        )
        return CrossCheck(
            status=CrossCheckStatus.AGREED if agreed else CrossCheckStatus.DISAGREED,
            reason="values_match" if agreed else "values_differ",
            sql=sql,
            primary_value=answer,
            independent_value=independent,
            identical_sql=identical,
            single_route=single_route,
            separate_model=self._separate_model,
        )


def _not_assessed(reason: CrossCheckReason) -> CrossCheck:
    return CrossCheck(status=CrossCheckStatus.NOT_ASSESSED, reason=reason)


def _refused(result: QueryResult) -> bool:
    return [column.casefold() for column in result.columns] == [
        CROSS_CHECK_REFUSAL_COLUMN
    ]


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


def _same_when_rounded(question: str, first: Decimal, second: Decimal) -> bool:
    """Compare at the decimal places the question itself asks for.

    This query is told to return an unrounded result, while the first query may
    round as asked. Without a stated number of places, nothing is relaxed.
    """
    asked = _PLACES_ASKED.search(question)
    if asked is None:
        return False
    word = asked[1].casefold()
    places = _PLACE_WORDS.index(word) if word in _PLACE_WORDS else int(word)
    if places > MAX_ROUNDED_PLACES:
        return False
    policy = DecimalRoundingPolicy(places)
    try:
        return _round_for_policy(first, policy) == _round_for_policy(second, policy)
    except DecimalException:
        return False


# Structures where another route can expose a mistake the obvious one hides:
# rows repeated by a join, the grain of a group, a nested population, values
# counted once, or a row picked by order.
_ROUTE_STRUCTURES: tuple[type[exp.Expression], ...] = (
    exp.Join,
    exp.Group,
    exp.Having,
    exp.Window,
    exp.Distinct,
    exp.With,
    exp.Subquery,
    exp.SetOperation,
    exp.Lateral,
    exp.Unnest,
    # Aggregates that pick one row's value depend on ties and order.
    exp.ArgMax,
    exp.ArgMin,
    exp.First,
    exp.Last,
    exp.AnyValue,
)


# Nodes that only join conditions or carry a value along; they relate nothing.
_COMBINERS: tuple[type[exp.Expression], ...] = (
    exp.Select,
    exp.From,
    exp.Where,
    exp.Alias,
    exp.And,
    exp.Or,
    exp.Not,
    exp.Paren,
    exp.Case,
    exp.If,
)


def _columns(node: exp.Expression) -> frozenset[str]:
    return frozenset(column.name.casefold() for column in node.find_all(exp.Column))


def _relates_columns(tree: exp.Select, projection: exp.Expression) -> bool:
    """Return whether the query builds a quantity from two different columns.

    Comparing a column with a value only chooses rows. Comparing or combining
    two columns, as in ``shipped <= required``, ``price - cost`` or
    ``SUM(a) / SUM(b)``, defines a new concept, and two models can share the
    same wrong definition. Such a query is never treated as single-route.
    """
    for node in tree.find_all(exp.Expression):
        # Arithmetic over aggregates is compared aggregate by aggregate below.
        if isinstance(node, _COMBINERS) or node.find(exp.AggFunc) is not None:
            continue
        if len(_columns(node)) > 1:
            return True
    outermost = [
        node
        for node in projection.find_all(exp.AggFunc)
        if node.find_ancestor(exp.AggFunc) is None
    ]
    # COUNT(*) reads no column; it counts the same rows, so it relates nothing.
    measures = {_columns(node) for node in outermost} - {frozenset()}
    return len(measures) > 1


def _single_route(sql: str) -> bool:
    """Return whether no other route could test more than the same choices.

    The query must read one table in one SELECT, return one expression built
    from aggregates, use none of the structures above, and never relate two
    columns. Its row conditions may sit in WHERE or inside the aggregate;
    either way they choose the same rows. This is decided from the SQL alone,
    never from the question.
    """
    tree = sqlglot.parse_one(sql, read="duckdb")
    if not isinstance(tree, exp.Select) or len(list(tree.find_all(exp.Select))) != 1:
        return False
    if tree.find(*_ROUTE_STRUCTURES) is not None:
        return False
    if len(list(tree.find_all(exp.Table))) != 1 or len(tree.expressions) != 1:
        return False
    projection = tree.expressions[0]
    if projection.find(exp.AggFunc) is None:
        return False
    if any(
        column.find_ancestor(exp.AggFunc) is None
        for column in projection.find_all(exp.Column)
    ):
        return False
    return not _relates_columns(tree, projection)


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
