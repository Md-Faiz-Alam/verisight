"""Answer plainly worded questions with fixed rules, without a model.

A question is compiled only when every part of it maps exactly onto this
dataset: a real column, a real value, a known calculation. Anything else
returns ``None`` and goes to the model-backed workflow. When a value fits
several columns, the caller gets a question to ask instead of a guess.
"""

import re
from dataclasses import dataclass

import pandas as pd

from verisight.execution.claim_verification import (
    ClaimOperation,
    EvidenceReference,
    NumericalClaim,
    NumericalClaimVerifier,
    VerificationStatus,
)
from verisight.execution.engine import DuckDBExecutor
from verisight.execution.exceptions import QueryExecutionError
from verisight.execution.investigation_result import VerifiedNumericalClaim
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation
from verisight.execution.trust import CheckStatus, TrustCheck, TrustLevel, TrustReport
from verisight.ingestion.models import LoadedDataset, LoadedTable
from verisight.ingestion.schema import LogicalType, SchemaInferer
from verisight.quality.totals import find_total_rows

_NUMERIC = (LogicalType.INTEGER, LogicalType.FLOAT, LogicalType.DECIMAL)
_FUNCTIONS = {
    "total": "SUM",
    "sum of": "SUM",
    "average": "AVG",
    "mean": "AVG",
    "maximum": "MAX",
    "highest": "MAX",
    "minimum": "MIN",
    "lowest": "MIN",
}
_WORD = {"SUM": "total", "AVG": "average", "MAX": "highest", "MIN": "lowest"}
_MEASURE = re.compile(
    r"what (?:is|was) the (total|sum of|average|mean|maximum|highest|minimum|lowest) "
    r"(?:of )?(?:the )?(.+)",
    re.IGNORECASE,
)
_COUNT_TABLE = re.compile(
    r"how many (?:rows|records) (?:does|do|are in|in) (.+?)(?: have| contain)?",
    re.IGNORECASE,
)
_COUNT_EQUAL = re.compile(
    r"how many (?:rows|records) have (.+?) (?:equal to|of) (.+)", re.IGNORECASE
)
_COUNT_STATE = re.compile(r"how many (.+?) (?:were|are|is|was) (.+)", re.IGNORECASE)
_WHERE = re.compile(r" where (.+?) (?:is|equals|=) (.+)$", re.IGNORECASE)
_FOR = re.compile(r" (?:for|in) (.+)$", re.IGNORECASE)
_PERIOD = re.compile(r"[0-9]{4}(?:-[0-9]{2}(?:-[0-9]{2})?)?")
_PERIOD_FORMATS = {4: "%Y", 7: "%Y-%m", 10: "%Y-%m-%d"}
_DIRECT_CONCLUSION = "Calculated directly from your data, without AI."


@dataclass(frozen=True, slots=True)
class Clarification:
    """A question that fits several meanings, and the wordings that settle it."""

    question: str
    prompt: str
    options: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DirectAnswer:
    """A value computed by compiled SQL, with its evidence and trust report."""

    question: str
    conclusion: str
    sql: str
    observation: QueryObservation
    claim: VerifiedNumericalClaim
    trust: TrustReport


@dataclass(frozen=True, slots=True)
class _Filter:
    condition: str
    column: str


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _readable(name: str) -> str:
    return re.sub(r"\s+", " ", name.replace("_", " ")).strip().casefold()


def _singular(word: str) -> str:
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def _clean(question: str) -> str:
    return re.sub(r"\s+", " ", question).strip().rstrip("?.! ")


def _value_matches(series: pd.Series, value: str) -> bool:
    present = series.dropna()
    if present.empty or not all(isinstance(item, str) for item in present):
        return False
    wanted = value.strip().casefold()
    return bool(present.str.strip().str.casefold().eq(wanted).any())


def _equals(column: str, value: str) -> str:
    return (
        f"LOWER(TRIM(CAST({_quote(column)} AS VARCHAR))) = "
        f"{_literal(value.strip().casefold())}"
    )


class DirectAnswerer:
    """Compile and run plainly worded questions for one loaded dataset."""

    def __init__(self, dataset: LoadedDataset, executor: DuckDBExecutor) -> None:
        self._dataset = dataset
        self._executor = executor
        self._types = {
            table.relation_name: {
                column.name: column.logical_type
                for column in SchemaInferer().infer_table(table).columns
            }
            for table in dataset.tables
        }
        self._totals: dict[str, tuple[tuple[str, str], ...]] = {}

    def answer(self, question: str) -> DirectAnswer | Clarification | None:
        """Return a result, a question to ask, or ``None`` for the model workflow."""
        text = _clean(question)
        for attempt in (self._count_table, self._count_equal, self._count_state):
            compiled = attempt(text)
            if compiled is not None:
                return self._finish(question, compiled)
        measured = self._measure(question, text)
        if isinstance(measured, Clarification):
            return measured
        return None if measured is None else self._finish(question, measured)

    def _table_named(self, words: str) -> LoadedTable | None:
        wanted = _singular(_readable(words))
        return next(
            (
                table
                for table in self._dataset.tables
                if _singular(_readable(table.relation_name)) == wanted
            ),
            None,
        )

    def _column_owner(self, name: str) -> tuple[LoadedTable, str] | None:
        """Find the one table holding a column with this readable name."""
        wanted = _readable(name)
        found = [
            (table, str(column))
            for table in self._dataset.tables
            for column in table.data.columns
            if _readable(str(column)) == wanted
        ]
        return found[0] if len(found) == 1 else None

    def _exclusions(self, table: LoadedTable, kept: str | None) -> list[str]:
        if table.relation_name not in self._totals:
            columns = SchemaInferer().infer_table(table).columns
            self._totals[table.relation_name] = tuple(
                (item.column, item.value)
                for item in find_total_rows(table.data, columns)
            )
        return [
            f"{_quote(column)} IS DISTINCT FROM {_literal(value)}"
            for column, value in self._totals[table.relation_name]
            if column != kept
        ]

    def _sql(self, expression: str, table: LoadedTable, chosen: _Filter | None) -> str:
        kept = None if chosen is None else chosen.column
        conditions = self._exclusions(table, kept)
        conditions += [] if chosen is None else [chosen.condition]
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        return f"SELECT {expression} AS value FROM {_quote(table.relation_name)}{where}"

    def _count_table(self, text: str) -> str | None:
        match = _COUNT_TABLE.fullmatch(text)
        table = None if match is None else self._table_named(match[1])
        return None if table is None else self._sql("COUNT(*)", table, None)

    def _count_equal(self, text: str) -> str | None:
        match = _COUNT_EQUAL.fullmatch(text)
        if match is None:
            return None
        owner = self._column_owner(match[1])
        if owner is None or not _value_matches(owner[0].data[owner[1]], match[2]):
            return None
        chosen = _Filter(_equals(owner[1], match[2]), owner[1])
        return self._sql("COUNT(*)", owner[0], chosen)

    def _count_state(self, text: str) -> str | None:
        match = _COUNT_STATE.fullmatch(text)
        table = None if match is None else self._table_named(match[1])
        if match is None or table is None:
            return None
        columns = [
            str(c)
            for c in table.data.columns
            if _value_matches(table.data[c], match[2])
        ]
        if len(columns) != 1:
            return None
        return self._sql(
            "COUNT(*)", table, _Filter(_equals(columns[0], match[2]), columns[0])
        )

    def _measure(self, question: str, text: str) -> str | Clarification | None:
        match = _MEASURE.fullmatch(text)
        if match is None:
            return None
        function = _FUNCTIONS[match[1].casefold()]
        rest = match[2]
        where = _WHERE.search(rest)
        short = _FOR.search(rest)
        if where is not None:
            name, condition = rest[: where.start()], where
        elif short is not None:
            name, condition = rest[: short.start()], short
        else:
            name, condition = rest, None
        owner = self._column_owner(name)
        if (
            owner is None
            or self._types[owner[0].relation_name][owner[1]] not in _NUMERIC
        ):
            return None
        table, column = owner
        expression = f"{function}({_quote(column)})"
        if condition is None:
            return self._sql(expression, table, None)
        if where is not None:
            target = self._column_owner(where[1])
            if (
                target is None
                or target[0] is not table
                or not _value_matches(table.data[target[1]], where[2])
            ):
                return None
            chosen = _Filter(_equals(target[1], where[2]), target[1])
            return self._sql(expression, table, chosen)
        resolved = self._filter_for(
            table, short[1] if short else "", question, name, match[1]
        )
        if resolved is None or isinstance(resolved, Clarification):
            return resolved
        return self._sql(expression, table, resolved)

    def _filter_for(
        self, table: LoadedTable, value: str, question: str, measure: str, word: str
    ) -> _Filter | Clarification | None:
        """Decide what ``for X`` or ``in X`` refers to, or ask."""
        if _PERIOD.fullmatch(value):
            dates = [
                name
                for name, kind in self._types[table.relation_name].items()
                if kind is LogicalType.DATETIME
            ]
            if len(dates) != 1:
                return None
            shape = _PERIOD_FORMATS[len(value)]
            condition = f"strftime({_quote(dates[0])}, '{shape}') = {_literal(value)}"
            return _Filter(condition, dates[0])
        columns = [
            str(c) for c in table.data.columns if _value_matches(table.data[c], value)
        ]
        if not columns:
            return None
        if len(columns) == 1:
            return _Filter(_equals(columns[0], value), columns[0])
        return Clarification(
            question=question,
            prompt=f"{value!r} appears in more than one column. Which did you mean?",
            options=tuple(
                f"What is the {word.casefold()} {measure} where "
                f"{column.replace('_', ' ')} is {value}?"
                for column in columns
            ),
        )

    def _finish(self, question: str, sql: str) -> DirectAnswer | None:
        try:
            result = self._executor.execute(self._dataset, sql)
        except QueryExecutionError:
            return None
        return _answer(question, sql, result)


def _answer(question: str, sql: str, result: QueryResult) -> DirectAnswer | None:
    cell = result.rows[0][0]
    if cell is None:
        return None
    observation = QueryObservation(question=question, sql=sql, result=result)
    claim = NumericalClaim(
        operation=ClaimOperation.VALUE,
        expected=cell,  # type: ignore[arg-type]
        left=EvidenceReference(0, 0, "value"),
    )
    verification = NumericalClaimVerifier().verify(claim, (observation,))
    assert verification.status is VerificationStatus.SUPPORTED
    return DirectAnswer(
        question=question,
        conclusion=_DIRECT_CONCLUSION,
        sql=sql,
        observation=observation,
        claim=VerifiedNumericalClaim(claim, verification),
        trust=TrustReport(
            TrustLevel.COMPUTED,
            (
                TrustCheck(
                    "compiled_without_ai",
                    CheckStatus.PASSED,
                    "Your question matched exact columns and values, so fixed "
                    "rules wrote the SQL.",
                ),
            ),
        ),
    )
