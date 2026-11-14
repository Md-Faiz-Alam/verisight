"""Check generated SQL against the question and the data it actually ran on.

Matching a number to a result cell cannot show that the SQL is sound. These
checks need no model: they read the SQL's structure and look at the loaded
rows, through CTEs and subqueries as well as plain queries. A finding is a
specific reason to distrust a query. No finding means only that none of these
mistakes was seen.
"""

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

import pandas as pd
import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from verisight.execution.context import ObservedCategoryValues, ObservedTotalRows
from verisight.execution.models import QueryResult
from verisight.execution.validation import (
    _names_every_row,
    _population_terms,
    _question_assigns_category,
    _question_mentions_category,
)
from verisight.ingestion.models import LoadedDataset, LoadedTable

_MIN_NAMED_VALUE_LENGTH = 3
_MEDIAN = re.compile(r"\bmedian\b", re.IGNORECASE)
_NO_VALUE = re.compile(
    r"\b(?:no recorded|missing|without (?:a |any )?recorded)\b", re.IGNORECASE
)
_KNOWN_VALUE = re.compile(r"\b(?:recorded|known)\b(?! as\b)", re.IGNORECASE)
_AS_ZERO = re.compile(r"\bas (?:zero|0)\b", re.IGNORECASE)
_YEAR = re.compile(r"\b(?:1[5-9][0-9]{2}|20[0-9]{2})\b")
_AT_LEAST = re.compile(r"\bat least ([0-9][0-9,]*(?:\.[0-9]+)?)", re.IGNORECASE)
_ABOVE = re.compile(
    r"\b(?:above|over|more than|greater than) ([0-9][0-9,]*(?:\.[0-9]+)?)",
    re.IGNORECASE,
)
_PERCENT = re.compile(r"\bpercent(?:age)?\b", re.IGNORECASE)
_ORDERED = re.compile(r"\b(?:minus|than)\b", re.IGNORECASE)
_MINUS = re.compile(r"([^.?!,]+?)\s+minus\s+([^.?!,]+)", re.IGNORECASE)
_MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)
_MONTHS = {name: number for number, name in enumerate(_MONTH_NAMES, start=1)}
_MONTH_DAY = re.compile(rf"\b({'|'.join(_MONTHS)}) ([0-9]{{1,2}})\b", re.IGNORECASE)
_DISTINCT_WANTED = re.compile(
    r"\bhow many (?:different|distinct|unique)\b", re.IGNORECASE
)
_RANGE = re.compile(r"\bfrom ([0-9]+(?:\.[0-9]+)?) to ([0-9]+(?:\.[0-9]+)?)\b", re.I)
# Words that ask for money, and words that name a column holding it.
_MONEY_ASKED = re.compile(
    r"\b(?:prices?|costs?|revenues?|spend(?:ing)?|salar(?:y|ies)|wages?|incomes?|"
    r"profits?|fees?|fares?|euros?|dollars?|rupees?|currency)\b|[€$₹£¥]",
    re.IGNORECASE,
)
_MONEY_COLUMN_WORDS = frozenset(
    [
        "amount",
        "price",
        "cost",
        "revenue",
        "sale",
        "salary",
        "wage",
        "income",
        "earning",
        "spend",
        "spending",
        "profit",
        "turnover",
        "gross",
        "fee",
        "fare",
        "budget",
        "payment",
        "paid",
        "usd",
        "eur",
        "inr",
        "gbp",
        "dollar",
        "euro",
        "rupee",
    ]
)
_PEOPLE_ASKED = re.compile(
    r"\bhow many (?:(?:different|distinct|unique|individual|separate) )+"
    r"(?:people|persons|individuals|customers|users|riders|patients|employees|"
    r"students|members|visitors|clients|buyers|passengers)\b",
    re.IGNORECASE,
)
_PERSON_COLUMN_WORDS = frozenset(
    [
        "id",
        "name",
        "email",
        "customer",
        "user",
        "person",
        "member",
        "client",
        "patient",
        "employee",
        "student",
        "visitor",
        "rider",
        "buyer",
        "passenger",
        "account",
        "phone",
    ]
)
_MEASURED = (exp.Sum, exp.Avg, exp.Max, exp.Min, exp.Median)
# Grading words that need a definition: "large" means nothing until a threshold
# or a category is given. Superlatives such as "largest" are calculations instead.
_VAGUE_WORDS = frozenset(
    [
        "large",
        "big",
        "huge",
        "small",
        "tiny",
        "high",
        "low",
        "cheap",
        "expensive",
        "economical",
        "efficient",
        "recent",
        "recently",
        "old",
        "new",
        "young",
        "popular",
        "good",
        "bad",
        "local",
        "fast",
        "slow",
        "heavy",
        "light",
        "long",
        "short",
        "rich",
        "poor",
        "premium",
        "frequent",
        "rare",
        "busy",
        "major",
        "minor",
    ]
)
_COMPARED = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.In, exp.Like)
_HOW_MUCH_MORE = re.compile(
    r"\bhow (?:much|many) (?:higher|lower|more|less|bigger|smaller|larger|greater|"
    r"longer|shorter|faster|slower|heavier|lighter|cheaper|older|younger)\b",
    re.IGNORECASE,
)
_AGAINST = re.compile(r"\b(?:than|minus|compared|versus|vs)\b", re.IGNORECASE)
_NUMBER_TEXT = re.compile(r"[0-9]+(?:\.[0-9]+)?")
# Numbers a calculation may use without saying so: units, percentages, halves.
_PLAIN_CONSTANTS = frozenset({0.0, 1.0, 2.0, 100.0, 1000.0})
_MEASURE_PHRASE = re.compile(
    r"\b(?:average|mean|total|sum of|median|maximum|minimum|highest|lowest)\s+"
    r"(?:(?:of|the)\s+)*([a-z][a-z \-]{2,40})",
    re.IGNORECASE,
)
_FILLER = frozenset(
    [
        "the",
        "of",
        "for",
        "per",
        "in",
        "on",
        "at",
        "by",
        "and",
        "a",
        "an",
        "all",
        "each",
        "these",
        "those",
        "this",
        "that",
        "with",
        "to",
        "from",
        "was",
        "were",
        "is",
        "are",
    ]
)
_PARTIAL_MATCH_WANTED = re.compile(
    r"\b(?:contain\w*|includ\w*|start\w*|begin\w*|end\w*|like|any kind)\b",
    re.IGNORECASE,
)
_CALCULATION = re.compile(
    r"\b(average|mean|total|sum of|highest|maximum|lowest|minimum)\s+"
    r"(?:(?:of|the)\s+)*",
    re.IGNORECASE,
)
_WANTS: dict[str, tuple[type[exp.Expression], ...]] = {
    "average": (exp.Avg, exp.Div),
    "mean": (exp.Avg, exp.Div),
    "total": (exp.Sum, exp.Count),
    "sum of": (exp.Sum,),
    "highest": (exp.Max, exp.Order),
    "maximum": (exp.Max, exp.Order),
    "lowest": (exp.Min, exp.Order),
    "minimum": (exp.Min, exp.Order),
}


@dataclass(frozen=True, slots=True)
class AuditFinding:
    """One specific reason to distrust a query, in plain words."""

    code: str
    detail: str


@dataclass(frozen=True, slots=True)
class SqlAudit:
    """What the checks found. ``assessed`` is false if the SQL could not be read."""

    assessed: bool
    findings: tuple[AuditFinding, ...] = ()


def audit_sql(
    *,
    question: str,
    sql: str,
    result: QueryResult | None,
    dataset: LoadedDataset,
    total_rows: Sequence[ObservedTotalRows] = (),
    categories: Sequence[ObservedCategoryValues] = (),
) -> SqlAudit:
    """Run every check on one executed query."""
    try:
        tree = sqlglot.parse_one(sql, read="duckdb")
    except SqlglotError:
        return SqlAudit(False)
    tables = {table.relation_name.casefold(): table for table in dataset.tables}
    used = {
        name: tables[name]
        for name in (t.name.casefold() for t in tree.find_all(exp.Table))
        if name in tables
    }
    if not used:
        return SqlAudit(False)
    return SqlAudit(
        True,
        (
            *_empty_result(result),
            *_fan_out(tree, used),
            *_uncounted_total_rows(tree, used, total_rows),
            *_filter_values(tree, used),
            *_named_value(question, tree, tables, categories),
            *_broad_match(question, tree, tables, categories),
            *_distinct_count(question, tree),
            *_measure_not_in_data(question, tree, used),
            *_assumed_definition(question, tree),
            *_missing_comparison(question),
            *_invented_constants(question, tree),
            *_measure_not_named(question, tree),
            *_calculation(question, tree, tables),
            *_median(question, tree),
            *_missing_as_zero(question, tree, used),
            *_missing_values(question, tree),
            *_period(question, tree, tables),
            *_thresholds(question, tree),
            *_range_ends(question, tree),
            *_scale(question, tree),
            *_subtraction_order(question, tree, tables, categories),
        ),
    )


def _empty_result(result: QueryResult | None) -> Iterator[AuditFinding]:
    if result is not None and (
        not result.rows or all(cell is None for cell in result.rows[0])
    ):
        yield AuditFinding(
            "empty_result", "The query returned no value for the rows it selected."
        )


def _names(tree: exp.Expression) -> set[str]:
    return {column.name.casefold() for column in tree.find_all(exp.Column)}


def _has_column(table: LoadedTable, name: str) -> bool:
    return name.casefold() in {str(c).casefold() for c in table.data.columns}


def _actual_name(table: LoadedTable, name: str) -> str:
    return next(
        str(c) for c in table.data.columns if str(c).casefold() == name.casefold()
    )


def _sources(
    select: exp.Select, used: dict[str, LoadedTable]
) -> dict[str, LoadedTable]:
    """Map aliases to loaded tables; subqueries and CTEs are not base tables."""
    from_clause = select.args.get("from_")
    nodes = [from_clause.this] if isinstance(from_clause, exp.From) else []
    nodes += [join.this for join in select.args.get("joins") or []]
    return {
        node.alias_or_name.casefold(): used[node.name.casefold()]
        for node in nodes
        if isinstance(node, exp.Table) and node.name.casefold() in used
    }


def _owner(column: exp.Column, sources: dict[str, LoadedTable]) -> str | None:
    if column.table:
        alias = column.table.casefold()
        known = alias in sources and _has_column(sources[alias], column.name)
        return alias if known else None
    owners = [a for a, t in sources.items() if _has_column(t, column.name)]
    return owners[0] if len(owners) == 1 else None


def _join_keys(
    join: exp.Join, sources: dict[str, LoadedTable]
) -> dict[tuple[str, str], tuple[list[str], list[str]]]:
    """Group a join's ``a.x = b.y`` conditions by the two tables they connect."""
    keys: dict[tuple[str, str], tuple[list[str], list[str]]] = {}
    condition = join.args.get("on")
    for term in [] if condition is None else _population_terms(condition):
        if not (
            isinstance(term, exp.EQ)
            and isinstance(term.this, exp.Column)
            and isinstance(term.expression, exp.Column)
        ):
            continue
        left = _owner(term.this, sources)
        right = _owner(term.expression, sources)
        if left is None or right is None or left == right:
            continue
        columns = keys.setdefault((left, right), ([], []))
        columns[0].append(term.this.name)
        columns[1].append(term.expression.name)
    return keys


def _repeats(
    table: LoadedTable, columns: list[str], other: LoadedTable, others: list[str]
) -> bool:
    """Whether ``table`` holds several rows for a key that ``other`` also has."""
    keys = table.data[[_actual_name(table, c) for c in columns]].dropna()
    repeated = keys[keys.duplicated(keep=False)].drop_duplicates()
    if repeated.empty:
        return False
    seen = other.data[[_actual_name(other, c) for c in others]].dropna()
    aligned = seen.set_axis(list(repeated.columns), axis=1)
    try:
        return not aligned.merge(repeated, how="inner").empty
    except ValueError:
        return False


def _only_a_condition(column: exp.Column, aggregate: exp.Expression) -> bool:
    """True when the column only decides which rows count, as in ``CASE WHEN``.

    ``COUNT(CASE WHEN c.country = 'uk' THEN 1 END)`` measures the joined rows
    and filters them by ``c.country``, like a WHERE clause. A column in the
    THEN or ELSE part is still a measure.
    """
    child: exp.Expression = column
    parent = column.parent
    while parent is not None and child is not aggregate:
        if isinstance(parent, exp.If) and parent.this is child:
            return True
        child, parent = parent, parent.parent
    return False


def _aggregated_columns(tree: exp.Expression) -> Iterator[tuple[str, exp.Column]]:
    for node in tree.find_all(exp.Sum, exp.Avg, exp.Count):
        if isinstance(node.this, exp.Distinct):
            continue
        for column in node.find_all(exp.Column):
            if not _only_a_condition(column, node):
                yield type(node).__name__.upper(), column


def _fan_out(
    tree: exp.Expression, used: dict[str, LoadedTable]
) -> Iterator[AuditFinding]:
    """Find measures from rows that a join copies more than once.

    Summing orders joined to their items adds each order once per item. Only
    ``ON a.x = b.y`` joins between loaded tables are read. A subquery that
    already grouped by its key is unique by construction and is not flagged.
    """
    for select in tree.find_all(exp.Select):
        sources = _sources(select, used)
        for join in select.args.get("joins") or []:
            for (left, right), (lefts, rights) in _join_keys(join, sources).items():
                for copied, by, columns, others in (
                    (left, right, lefts, rights),
                    (right, left, rights, lefts),
                ):
                    if _repeats(sources[by], others, sources[copied], columns):
                        yield from _copied_measures(tree, sources, copied, by)


def _copied_measures(
    tree: exp.Expression, sources: dict[str, LoadedTable], copied: str, by: str
) -> Iterator[AuditFinding]:
    table = sources[copied]
    other = sources[by]
    for function, column in _aggregated_columns(tree):
        direct = column.table.casefold() == copied
        by_name = (
            column.table.casefold() not in sources
            and _has_column(table, column.name)
            and not _has_column(other, column.name)
        )
        if direct or by_name:
            yield AuditFinding(
                "join_fan_out",
                f"Joining {other.relation_name} repeats rows of "
                f"{table.relation_name}, so {function}({column.name}) counts "
                "some rows more than once.",
            )


def _uncounted_total_rows(
    tree: exp.Expression,
    used: dict[str, LoadedTable],
    total_rows: Sequence[ObservedTotalRows],
) -> Iterator[AuditFinding]:
    """Find aggregates that add detected total rows to their own parts."""
    if tree.find(exp.AggFunc) is None:
        return
    names = _names(tree)
    for item in total_rows:
        if (
            item.relation.casefold() in used
            and item.column.casefold() not in names
            and names & {measure.casefold() for measure in item.measures}
        ):
            yield AuditFinding(
                "total_rows_included",
                f"Rows where {item.column} is {item.value!r} already hold totals, "
                "and this query adds them to their own parts.",
            )


def _bare_column(node: exp.Expression) -> tuple[exp.Column | None, bool]:
    """Unwrap LOWER, UPPER, TRIM and CAST; true if the comparison is normalised."""
    normalised = False
    current = node
    while isinstance(current, exp.Lower | exp.Upper | exp.Trim | exp.Cast | exp.Paren):
        normalised = normalised or not isinstance(current, exp.Cast | exp.Paren)
        current = current.this
    return (current, normalised) if isinstance(current, exp.Column) else (None, False)


def _comparisons(
    tree: exp.Expression, *, broad: bool = False
) -> Iterator[tuple[exp.Column, bool, str]]:
    """Yield every ``column = 'text'`` and ``column IN ('text', ...)``.

    With ``broad``, also yield ``<>`` and ``LIKE``: they show that a column
    was restricted, but their text need not be a stored value.
    """
    kinds: tuple[type[exp.Expression], ...] = (exp.EQ, exp.In)
    if broad:
        kinds += (exp.NEQ, exp.Like, exp.ILike)
    for node in tree.find_all(*kinds):
        if isinstance(node, exp.In):
            pairs = [(node.this, value) for value in node.expressions]
        else:
            pairs = [(node.this, node.expression), (node.expression, node.this)]
        for side, literal in pairs:
            column, normalised = _bare_column(side)
            if (
                column is not None
                and isinstance(literal, exp.Literal)
                and literal.is_string
            ):
                yield column, normalised, literal.this


def _resolve_text_column(
    tree: exp.Expression, column: exp.Column, used: dict[str, LoadedTable]
) -> tuple[LoadedTable, pd.Series] | None:
    """Find the one loaded text column a query's column refers to."""
    aliases = {
        t.alias_or_name.casefold(): t.name.casefold() for t in tree.find_all(exp.Table)
    }
    if column.table:
        named = used.get(aliases.get(column.table.casefold(), ""))
        owners = [named] if named is not None else []
    else:
        owners = list(used.values())
    matching = [t for t in owners if _has_column(t, column.name)]
    if len(matching) != 1:
        return None
    table = matching[0]
    series = table.data[_actual_name(table, column.name)]
    present = series.dropna()
    if present.empty or not all(isinstance(value, str) for value in present):
        return None
    return table, present


def _normal(value: str) -> str:
    return value.strip().casefold()


def _found_elsewhere(value: str, used: dict[str, LoadedTable], skip: str) -> str | None:
    for table in used.values():
        for name in table.data.columns:
            present = table.data[name].dropna()
            if (
                str(name) != skip
                and not present.empty
                and all(isinstance(v, str) for v in present)
                and value in {_normal(v) for v in present}
            ):
                return str(name)
    return None


def _filter_values(
    tree: exp.Expression, used: dict[str, LoadedTable]
) -> Iterator[AuditFinding]:
    """Find filters on text values that the column lacks or only partly matches."""
    for column, normalised, literal in _comparisons(tree):
        resolved = _resolve_text_column(tree, column, used)
        if resolved is None:
            continue
        _, present = resolved
        wanted = _normal(literal)
        spellings = {value for value in present if _normal(value) == wanted}
        if len(spellings) > 1 and not normalised:
            yield AuditFinding(
                "filter_misses_spellings",
                f"{column.name} = {literal!r} misses other spellings of that value "
                "in the data.",
            )
        elif not spellings:
            elsewhere = _found_elsewhere(wanted, used, str(present.name))
            hint = f" It appears in {elsewhere}." if elsewhere else ""
            yield AuditFinding(
                "filter_value_missing",
                f"{column.name} never contains {literal!r}.{hint}",
            )
        elif not normalised and literal not in spellings:
            yield AuditFinding(
                "filter_misses_spellings",
                f"{column.name} = {literal!r} does not match how the value is "
                "written in the data.",
            )


def _mentions(
    question: str,
    tables: dict[str, LoadedTable],
    categories: Sequence[ObservedCategoryValues],
) -> list[tuple[ObservedCategoryValues, str]]:
    """Name each value the question uses and the one column it belongs to.

    A value held by several columns counts only if the question ties it to
    one, as in "housing is yes". Short lower-case words are too common to read.
    """
    by_value: dict[str, list[tuple[ObservedCategoryValues, str]]] = {}
    subjects = {*tables, *(item.relation for item in categories)}
    for item in categories:
        for value in item.observed_nonmissing_values:
            long_enough = (
                len(value.strip()) >= _MIN_NAMED_VALUE_LENGTH or value.isupper()
            )
            if (
                long_enough
                and _question_mentions_category(question, value)
                and not _names_every_row(question, subjects, item.column, value)
            ):
                by_value.setdefault(value.casefold(), []).append((item, value))
    found = []
    for pairs in by_value.values():
        tied = [
            pair
            for pair in pairs
            if _question_assigns_category(question, pair[0].column, pair[1])
        ]
        chosen = tied or pairs
        # The same column name in several tables is still one meaning.
        if len({pair[0].column.casefold() for pair in chosen}) == 1:
            found.append(chosen[0])
    return found


def _named_value(
    question: str,
    tree: exp.Expression,
    tables: dict[str, LoadedTable],
    categories: Sequence[ObservedCategoryValues],
) -> Iterator[AuditFinding]:
    """Find values the question names that the query never selects."""
    restricted = [
        (column.name.casefold(), literal.casefold())
        for column, _, literal in _comparisons(tree, broad=True)
    ]
    names = _names(tree)
    for item, value in _mentions(question, tables, categories):
        column = item.column.casefold()
        wanted = value.casefold()
        if any(c == column and wanted in text for c, text in restricted):
            continue
        # A column that is only grouped or displayed shows every value.
        if any(c == column for c, _ in restricted) or column not in names:
            yield AuditFinding(
                "named_value_not_selected",
                f"The question asks about {value!r}, but the query does not "
                f"select it in {item.column}.",
            )


def _broad_match(
    question: str,
    tree: exp.Expression,
    tables: dict[str, LoadedTable],
    categories: Sequence[ObservedCategoryValues],
) -> Iterator[AuditFinding]:
    """Find a LIKE that also takes in values the question did not name."""
    if _PARTIAL_MATCH_WANTED.search(question):
        return
    for item, value in _mentions(question, tables, categories):
        for column, _, literal in _comparisons(tree, broad=True):
            if column.name.casefold() != item.column.casefold() or "%" not in literal:
                continue
            shape = re.escape(literal.casefold()).replace("%", ".*").replace("_", ".")
            others = [
                other
                for other in item.observed_nonmissing_values
                if other.casefold() != value.casefold()
                and re.fullmatch(shape, other.casefold())
            ]
            if others:
                yield AuditFinding(
                    "filter_too_broad",
                    f"The question asks about {value!r}, but {literal!r} also "
                    f"selects {others[0]!r}.",
                )


def _distinct_count(question: str, tree: exp.Expression) -> Iterator[AuditFinding]:
    """Find a question about different things answered by adding up rows."""
    if _DISTINCT_WANTED.search(question) and tree.find(exp.Distinct, exp.Group) is None:
        yield AuditFinding(
            "distinct_not_counted",
            "The question counts different values, but the query counts rows.",
        )


def _column_words(name: str) -> set[str]:
    """Split ``order_date``, ``orderDate`` and ``Order Date`` into the same words."""
    parts = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])", name)
    words = {part.casefold() for part in parts}
    return words | {word.removesuffix("s") for word in words}


def _readable_word(word: str) -> bool:
    """A real word, not an abbreviation such as ``cnt`` whose meaning is unknown."""
    return len(word) > 3 and re.search(r"[aeiou]", word) is not None


def _related(words: set[str], others: set[str]) -> bool:
    """Words that share a stem, so "ordering" matches ``order``."""
    return any(one[:4] == two[:4] for one in words for two in others)


def _holds_money(tables: dict[str, LoadedTable], name: str) -> bool:
    """A column named for money, or one whose currency marks were removed."""
    if _column_words(name) & _MONEY_COLUMN_WORDS:
        return True
    return any(
        note.rule == "currency_symbol" and note.column.casefold() == name.casefold()
        for table in tables.values()
        for note in table.value_notes
    )


def _measure_not_in_data(
    question: str, tree: exp.Expression, used: dict[str, LoadedTable]
) -> Iterator[AuditFinding]:
    """Find a question about money or people answered with some other column.

    A price cannot be read from an acidity column, and summed visits do not
    count different people. Counting rows that match a price is not affected.
    """
    measured = sorted(
        {
            column.name
            for node in tree.find_all(*_MEASURED)
            for column in node.find_all(exp.Column)
        }
    )
    if (
        _MONEY_ASKED.search(question)
        and measured
        and not any(_holds_money(used, name) for name in measured)
    ):
        yield AuditFinding(
            "measure_not_in_data",
            f"The question asks for money, but {measured[0]} does not hold money "
            "amounts. The data may not contain what was asked.",
        )
    if _PEOPLE_ASKED.search(question):
        identifies = any(
            _column_words(column.name) & _PERSON_COLUMN_WORDS
            for column in tree.find_all(exp.Column)
        )
        if not identifies or tree.find(exp.Distinct, exp.Group) is None:
            yield AuditFinding(
                "measure_not_in_data",
                "The question counts different people, but the query counts no "
                "column that identifies a person.",
            )


def _question_numbers(question: str) -> set[float]:
    return {float(text) for text in _NUMBER_TEXT.findall(question.replace(",", ""))}


def _assumed_definition(question: str, tree: exp.Expression) -> Iterator[AuditFinding]:
    """Find a vague word the query defined by itself, as "large" = one category."""
    words = set(re.findall(r"[a-z]+", question.casefold())) & _VAGUE_WORDS
    if not words:
        return
    lowered = question.casefold()
    asked = _question_numbers(question)
    for node in tree.find_all(*_COMPARED):
        for literal in node.find_all(exp.Literal):
            if literal.is_string:
                given = literal.this.casefold() in lowered
            else:
                given = float(literal.this) in asked | _PLAIN_CONSTANTS
            if not given:
                word = sorted(words)[0]
                yield AuditFinding(
                    "assumed_definition",
                    f"The question does not say what counts as {word!r}, and the "
                    f"query assumed {node.sql(dialect='duckdb')}. Say what counts as "
                    f"{word!r} to get a number.",
                )
                return


def _missing_comparison(question: str) -> Iterator[AuditFinding]:
    """Find "how much higher" with nothing to compare against."""
    match = _HOW_MUCH_MORE.search(question)
    if match is not None and not _AGAINST.search(question):
        yield AuditFinding(
            "missing_comparison",
            f"The question asks {match[0].casefold()!r} but not compared with what. "
            "Say what to compare with to get a number.",
        )


def _invented_constants(question: str, tree: exp.Expression) -> Iterator[AuditFinding]:
    """Find numbers in a calculation that come from neither question nor data."""
    asked = _question_numbers(question) | _PLAIN_CONSTANTS
    for node in tree.find_all(exp.Mul, exp.Div, exp.Add, exp.Sub):
        for side in (node.left, node.right):
            value = _numeric_literal(side)
            if value is not None and abs(value) not in asked:
                yield AuditFinding(
                    "invented_constant",
                    f"The calculation uses {side.this}, which comes from neither "
                    "the question nor the data.",
                )
                return


def _measure_not_named(question: str, tree: exp.Expression) -> Iterator[AuditFinding]:
    """Find an average or total of a column the question never mentions."""
    match = _MEASURE_PHRASE.search(question)
    if match is None:
        return
    wanted = set(re.findall(r"[a-z]+", match[1].casefold())) - _FILLER
    lowered = question.casefold()
    measured = {
        column.name
        for node in tree.find_all(*_MEASURED)
        for column in node.find_all(exp.Column)
    }
    mentioned = wanted | set(re.findall(r"[a-z]+", lowered))
    unrelated = [
        name
        for name in sorted(measured)
        if (named := {w for w in _column_words(name) - _FILLER if _readable_word(w)})
        and not _related(named, mentioned)
    ]
    if wanted and unrelated and len(unrelated) == len(measured):
        yield AuditFinding(
            "measure_not_named",
            f"The question asks about {match[1].strip()!r}, but the query measures "
            f"{unrelated[0]}, which the question never mentions.",
        )


def _calculation(
    question: str, tree: exp.Expression, tables: dict[str, LoadedTable]
) -> Iterator[AuditFinding]:
    """Compare ``average salary`` and the like with what the query computes."""
    columns = sorted(
        {
            str(c).replace("_", " ").casefold(): str(c)
            for t in tables.values()
            for c in t.data.columns
        }.items(),
        key=lambda item: -len(item[0]),
    )
    referenced = _names(tree)
    for match in _CALCULATION.finditer(question):
        rest = question[match.end() :].casefold()
        named = next(
            (
                actual
                for readable, actual in columns
                if re.match(rf"{re.escape(readable)}(?!\w)", rest)
            ),
            None,
        )
        if named is None:
            continue
        word = match[1].casefold()
        if named.casefold() not in referenced:
            yield AuditFinding(
                "question_column_unused",
                f"The question asks for {word} {named}, but the query never "
                "uses that column.",
            )
        elif tree.find(*_WANTS[word]) is None:
            yield AuditFinding(
                "wrong_calculation",
                f"The question asks for the {word}, but the query does not "
                "calculate it.",
            )


def _median(question: str, tree: exp.Expression) -> Iterator[AuditFinding]:
    if _MEDIAN.search(question) and tree.find(exp.Median, exp.PercentileCont) is None:
        yield AuditFinding(
            "wrong_calculation",
            "The question asks for the median, but the query does not calculate it.",
        )


def _missing_as_zero(
    question: str, tree: exp.Expression, used: dict[str, LoadedTable]
) -> Iterator[AuditFinding]:
    """Find averages that count missing values as zero without being asked."""
    if _AS_ZERO.search(question):
        return
    for average in tree.find_all(exp.Avg):
        for coalesce in average.find_all(exp.Coalesce):
            zero = any(
                isinstance(item, exp.Literal)
                and not item.is_string
                and float(item.this) == 0
                for item in coalesce.expressions
            )
            name = coalesce.this.name
            holds_missing = any(
                _has_column(table, name)
                and bool(table.data[_actual_name(table, name)].isna().any())
                for table in used.values()
            )
            if zero and holds_missing:
                yield AuditFinding(
                    "missing_counted_as_zero",
                    f"The average counts missing {name} values as zero.",
                )


def _known_column_compared(question: str, tree: exp.Expression) -> bool:
    """Whether the query compares the column named after "recorded" or "known".

    A row whose value is missing can never satisfy such a comparison.
    """
    words = _KNOWN_VALUE.split(question, maxsplit=1)[-1].casefold()[:60]
    return any(
        column.name.replace("_", " ").casefold() in words
        for node in tree.find_all(exp.EQ, exp.GT, exp.GTE, exp.LT, exp.LTE, exp.Between)
        for column in node.find_all(exp.Column)
    )


def _missing_values(question: str, tree: exp.Expression) -> Iterator[AuditFinding]:
    """Compare a question about missing or known values with the query's filters."""
    if _NO_VALUE.search(question):
        if not any(
            isinstance(n.expression, exp.Null) and not isinstance(n.parent, exp.Not)
            for n in tree.find_all(exp.Is)
        ):
            yield AuditFinding(
                "missing_values_ignored",
                "The question is about missing values, but the query never tests "
                "for them.",
            )
    elif (
        _KNOWN_VALUE.search(question)
        and tree.find(exp.Avg, exp.Median, exp.Sum, exp.Max, exp.Min) is None
        or (
            _KNOWN_VALUE.search(question)
            and any(isinstance(c.this, exp.Star) for c in tree.find_all(exp.Count))
        )
    ) and (
        tree.find(exp.Is, exp.NEQ, exp.In, exp.Not) is None
        and not _known_column_compared(question, tree)
    ):
        yield AuditFinding(
            "unknown_values_counted",
            "The question is limited to known values, but the query keeps rows "
            "where the value is missing or unknown.",
        )


def _literal_texts(tree: exp.Expression) -> list[str]:
    return [node.this for node in tree.find_all(exp.Literal)]


def _coded_filter_selects_year(
    tree: exp.Expression, tables: dict[str, LoadedTable], year: int
) -> bool:
    """Whether a filter such as ``yr = 1`` selects only that year.

    A date column in the same table shows what the code means. Without one, the
    meaning of the code is unknown and the period still counts as not selected.
    """
    for node in tree.find_all(exp.EQ):
        for side, literal in (
            (node.this, node.expression),
            (node.expression, node.this),
        ):
            value = _numeric_literal(literal)
            if value is None or not isinstance(side, exp.Column):
                continue
            for table in tables.values():
                if not _has_column(table, side.name):
                    continue
                data = table.data
                rows = data[data[_actual_name(table, side.name)] == value]
                dates = rows.select_dtypes(include="datetime")
                for name in dates.columns:
                    if set(dates[name].dropna().dt.year) == {year}:
                        return True
    return False


def _period(
    question: str, tree: exp.Expression, tables: dict[str, LoadedTable]
) -> Iterator[AuditFinding]:
    """Find a year the question names that appears nowhere in the query."""
    texts = _literal_texts(tree)
    columns = " ".join(str(c) for t in tables.values() for c in t.data.columns)
    for year in _YEAR.findall(question):
        if (
            year not in columns
            and not any(year in text for text in texts)
            and not _coded_filter_selects_year(tree, tables, int(year))
        ):
            yield AuditFinding(
                "period_not_selected",
                f"The question names {year}, but the query never selects that year.",
            )


def _number_of(text: str) -> float:
    return float(text.replace(",", ""))


def _numeric_literal(node: exp.Expression) -> float | None:
    if isinstance(node, exp.Literal) and not node.is_string:
        return float(node.this)
    return None


def _thresholds(question: str, tree: exp.Expression) -> Iterator[AuditFinding]:
    """Compare "at least 5" and "above 5" with the query's comparisons."""
    wrong_kinds = (
        (_AT_LEAST, exp.GT, "at least"),
        (_ABOVE, exp.GTE, "more than"),
    )
    numbers = {
        value
        for node in tree.find_all(exp.Literal)
        if (value := _numeric_literal(node)) is not None
    }
    for pattern, wrong, words in wrong_kinds:
        for match in pattern.finditer(question):
            limit = _number_of(match[1])
            if limit not in numbers:
                yield AuditFinding(
                    "threshold_not_applied",
                    f"The question says {words} {match[1]}, but the query never "
                    "uses that number.",
                )
            elif any(
                _numeric_literal(n.expression) == limit for n in tree.find_all(wrong)
            ):
                yield AuditFinding(
                    "threshold_boundary",
                    f"The question says {words} {match[1]}, but the query treats "
                    "that exact value the other way.",
                )


def _range_ends(question: str, tree: exp.Expression) -> Iterator[AuditFinding]:
    """Find "from 2000 to 2010" written so that either end is left out."""
    for match in _RANGE.finditer(question):
        low, high = float(match[1]), float(match[2])
        if any(
            _numeric_literal(n.expression) == low for n in tree.find_all(exp.GT)
        ) or any(_numeric_literal(n.expression) == high for n in tree.find_all(exp.LT)):
            yield AuditFinding(
                "range_end_left_out",
                f"The question runs from {match[1]} to {match[2]}, but the query "
                "leaves out one of those ends.",
            )


def _scale(question: str, tree: exp.Expression) -> Iterator[AuditFinding]:
    """Find a percentage question whose answer was divided down to a fraction."""
    if not _PERCENT.search(question) or tree.find(exp.Mul) is not None:
        return
    for division in tree.find_all(exp.Div):
        if _numeric_literal(division.expression) == 100:
            yield AuditFinding(
                "wrong_scale",
                "The question asks for a percentage, but the query divides by 100.",
            )


def _holds(texts: set[str], anchors: set[str]) -> bool:
    return any(
        re.search(rf"(?<![a-z0-9_]){re.escape(anchor)}(?![a-z0-9_])", text)
        for anchor in anchors
        for text in texts
    )


def _sql_words(node: exp.Expression) -> set[str]:
    return {text.casefold() for text in _literal_texts(node)} | _names(node)


def _anchors(side: str, named: set[str], columns: dict[str, str]) -> set[str]:
    """What identifies one side of a subtraction: years, dates, values, columns."""
    lowered = side.casefold()
    found = set(_YEAR.findall(side))
    found |= {
        f"{_MONTHS[month.casefold()]:02d}-{int(day):02d}"
        for month, day in _MONTH_DAY.findall(side)
    }
    found |= {value for value in named if _holds({lowered}, {value})}
    # Longest first, so "alt price" is not also read as "price".
    for words, name in sorted(columns.items(), key=lambda item: -len(item[0])):
        if _holds({lowered}, {words}):
            found.add(name)
            lowered = lowered.replace(words, " ")
    return found


def _stated_order(
    sides: re.Match[str],
    tree: exp.Expression,
    tables: dict[str, LoadedTable],
    named: set[str],
) -> Iterator[AuditFinding]:
    """Compare "give A minus B" with what each side of each subtraction selects."""
    columns = {
        str(c).replace("_", " ").casefold(): str(c).casefold()
        for table in tables.values()
        for c in table.data.columns
    }
    # A label held by two columns is not "named", but the query shows which it is.
    filtered = {n.this.casefold() for n in tree.find_all(exp.Literal) if n.is_string}
    first = _anchors(sides[1], named | filtered, columns)
    second = _anchors(sides[2], named | filtered, columns)
    first, second = first - second, second - first
    for subtraction in tree.find_all(exp.Sub):
        left = _sql_words(subtraction.left)
        right = _sql_words(subtraction.right)
        # What both sides of the subtraction share cannot tell them apart.
        one = {a for a in first if not (_holds(left, {a}) and _holds(right, {a}))}
        two = {a for a in second if not (_holds(left, {a}) and _holds(right, {a}))}
        if (
            _holds(right, one)
            and _holds(left, two)
            and not _holds(left, one)
            and not _holds(right, two)
        ):
            yield AuditFinding(
                "reversed_subtraction",
                f"The question asks for {sorted(one)[0]} minus {sorted(two)[0]}, "
                "but the query calculates them the other way round.",
            )


def _subtraction_order(
    question: str,
    tree: exp.Expression,
    tables: dict[str, LoadedTable],
    categories: Sequence[ObservedCategoryValues],
) -> Iterator[AuditFinding]:
    """Find ``A minus B`` written in the query as ``B - A``."""
    if not _ORDERED.search(question):
        return
    lowered = question.casefold()
    named = {value.casefold() for _, value in _mentions(question, tables, categories)}
    stated = _MINUS.search(question)
    if stated is not None:
        yield from _stated_order(stated, tree, tables, named)
        return
    for subtraction in tree.find_all(exp.Sub):
        lefts = named & {text.casefold() for text in _literal_texts(subtraction.left)}
        rights = named & {text.casefold() for text in _literal_texts(subtraction.right)}
        for first in lefts - rights:
            for second in rights - lefts:
                if lowered.find(first) > lowered.find(second):
                    yield AuditFinding(
                        "reversed_subtraction",
                        f"The question asks for {second} minus {first}, but "
                        f"the query calculates {first} minus {second}.",
                    )
