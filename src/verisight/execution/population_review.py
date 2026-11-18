"""Reviews of generated SQL against the population and counting unit asked for.

Each review can ask for attention; none certifies the SQL or rewrites it.
"""

import re

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from verisight.execution.context import (
    CountingGrainReview,
    PopulationReview,
    PopulationWarning,
    QueryContext,
)
from verisight.execution.question_terms import (
    names_every_row,
    population_terms,
    question_assigns_category,
    question_mentions_category,
)


def review_population(
    question: str, sql: str, context: QueryContext
) -> PopulationReview:
    """Combine the category/filter review with the total-row review.

    Either review can require attention; neither certifies the SQL.
    """
    review = _review_categories(question, sql, context)
    totals = _review_total_rows(sql, context)
    if not totals:
        return review
    return PopulationReview("review_required", (*review.warnings, *totals))


def _review_total_rows(
    sql: str, context: QueryContext
) -> tuple[PopulationWarning, ...]:
    """Warn when an aggregate may add detected total rows to their own parts.

    Applies to one direct table with a detected total row whose category
    column the query never references, so it neither filters nor groups by it.
    """
    try:
        statements = sqlglot.parse(sql, read="duckdb")
    except ParseError:
        return ()
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        return ()
    query = statements[0]
    source = query.args.get("from_")
    if (
        query.args.get("joins")
        or not isinstance(source, exp.From)
        or not isinstance(source.this, exp.Table)
        or query.find(exp.AggFunc) is None
    ):
        return ()
    relation = source.this.name.casefold()
    referenced = {column.name.casefold() for column in query.find_all(exp.Column)}
    return tuple(
        PopulationWarning(
            item.relation, item.column, item.value, "total_rows_not_excluded"
        )
        for item in context.total_rows
        if item.relation.casefold() == relation
        and item.column.casefold() not in referenced
    )


def _review_categories(
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
    every = context.review_categories or context.observed_categories
    subjects = {
        *(relation.relation_name for relation in context.relations),
        *(item.relation for item in every),
    }
    categories = [
        item for item in every if item.relation.casefold() == table.name.casefold()
    ]
    candidates = [
        (item, value)
        for item in categories
        for value in item.observed_nonmissing_values
        if question_mentions_category(question, value)
        and not names_every_row(question, subjects, item.column, value)
    ]
    # One value shared by several columns is attributed only when the question
    # names exactly one of those columns for it, as in "housing is yes".
    if len({value.casefold() for _, value in candidates}) == 1:
        anchored = [
            (item, value)
            for item, value in candidates
            if question_assigns_category(question, item.column, value)
        ]
        if anchored:
            candidates = anchored
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
    terms = [] if where is None else population_terms(where.this)
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


def _explicit_identity_count_request(question: str) -> bool:
    """Recognize a bounded positive instruction contrasting identities and rows."""
    pattern = (
        r"\bcount\s+(?:[\w-]+\s+){0,4}(?:identities|entities)"
        r"\s*,?\s*not\s+(?:[\w-]+\s+){0,2}rows\b"
    )
    for match in re.finditer(pattern, question, re.IGNORECASE):
        if not re.search(
            r"\b(?:not|never|avoid|don't)\s*$",
            question[: match.start()],
            re.IGNORECASE,
        ):
            return True
    return False


def review_counting_grain(question: str, sql: str) -> CountingGrainReview:
    """Review ordinary COUNT use for explicit identity-versus-row instructions.

    Only a scalar count-based projection over one direct table is assessed.
    Distinct counts do not establish that the right identity columns were used.
    Ordinary counts can be valid on unique input; the warning requests review.
    No SQL is rewritten and no task semantics are certified.
    """
    unknown = CountingGrainReview("not_assessed")
    if not _explicit_identity_count_request(question):
        return unknown
    try:
        statements = sqlglot.parse(sql, read="duckdb")
    except ParseError:
        return unknown
    if len(statements) != 1 or not isinstance(statements[0], exp.Select):
        return unknown
    query = statements[0]
    source = query.args.get("from_")
    if (
        not isinstance(source, exp.From)
        or not isinstance(source.this, exp.Table)
        or len(query.expressions) != 1
        or any(
            query.args.get(key)
            for key in ("with_", "joins", "group", "having", "qualify", "distinct")
        )
        or len(tuple(query.find_all(exp.Select))) != 1
        or query.find(exp.Window) is not None
    ):
        return unknown
    projection = query.expressions[0]
    counts = tuple(projection.find_all(exp.Count))
    if not counts or any(
        not isinstance(aggregate, exp.Count)
        for aggregate in projection.find_all(exp.AggFunc)
    ):
        return unknown
    if any(not isinstance(count.this, exp.Distinct) for count in counts):
        return CountingGrainReview(
            "review_required", ("row_counts_for_identity_request",)
        )
    return CountingGrainReview("no_warning_detected")
