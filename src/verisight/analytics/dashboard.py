"""Build a dashboard for one table from validated SQL, without a model.

Every figure comes from a query run by the guarded DuckDB executor, and that
query is returned beside the figure. Three choices protect the numbers: rows
detected as totals of other rows are left out, a measure is added up only when
its name says it can be, and labels differing only by case or outer spaces are
grouped together. Everything else is reported as found.
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import combinations

import pandas as pd

from verisight.analytics.domains import (
    Domain,
    DomainMatch,
    detect_domain,
    name_tokens,
)
from verisight.execution.engine import DuckDBExecutor
from verisight.execution.exceptions import QueryExecutionError
from verisight.execution.models import QueryResult, QueryScalar
from verisight.ingestion.models import LoadedDataset, LoadedTable
from verisight.ingestion.schema import ColumnSchema, LogicalType, SchemaInferer
from verisight.quality.totals import find_total_rows

_NUMERIC = (LogicalType.INTEGER, LogicalType.FLOAT, LogicalType.DECIMAL)
_IDENTIFIER_WORDS = frozenset(
    [
        "id",
        "uuid",
        "guid",
        "key",
        "code",
        "zip",
        "zipcode",
        "postcode",
        "phone",
        "ssn",
        "index",
        "lat",
        "latitude",
        "lon",
        "lng",
        "longitude",
    ]
)
_YEAR_WORDS = frozenset({"year", "yr", "fy"})
_NOT_ADDITIVE = frozenset(
    [
        "rate",
        "ratio",
        "pct",
        "percent",
        "percentage",
        "avg",
        "average",
        "mean",
        "median",
        "score",
        "rating",
        "age",
        "temperature",
        "temp",
        "price",
        "margin",
        "probability",
        "humidity",
        "gpa",
        "bmi",
        "share",
        "per",
        "discount",
        "balance",
        "latitude",
        "longitude",
    ]
)
_ADDITIVE = frozenset(
    [
        "amount",
        "revenue",
        "sale",
        "cost",
        "spend",
        "quantity",
        "qty",
        "unit",
        "count",
        "total",
        "profit",
        "expense",
        "payment",
        "fee",
        "volume",
        "death",
        "kwh",
        "mwh",
        "item",
        "sold",
        "fare",
        "tip",
        "toll",
        "precipitation",
        "output",
        "charge",
    ]
)
_MAX_MEASURES = 6
_MAX_BREAKDOWNS = 4
_MAX_DIMENSION_VALUES = 50
_PREFERRED_DIMENSION_VALUES = 12
_BARS_SHOWN = 8
_KPIS_SHOWN = 4
_HISTOGRAMS_SHOWN = 2
_HISTOGRAM_BINS = 12
_MAX_TREND_POINTS = 400
_DAILY_SPAN_DAYS = 62
_MONTHLY_SPAN_DAYS = 5 * 366
_MIN_CORRELATION_ROWS = 30
_MIN_CORRELATION = 0.5
_MIN_TREND_POINTS_FOR_PEAK = 3


class DashboardRequestError(ValueError):
    """A dashboard was requested for a table or filter that does not exist."""


@dataclass(frozen=True, slots=True)
class DashboardFilter:
    """Keep rows whose normalised label in ``column`` equals ``value``."""

    column: str
    value: str


@dataclass(frozen=True, slots=True)
class RelationSummary:
    """One table a dashboard can be built for."""

    name: str
    rows: int


@dataclass(frozen=True, slots=True)
class KpiTile:
    """One headline figure and the query that produced it."""

    label: str
    value: QueryScalar
    sql: str


@dataclass(frozen=True, slots=True)
class TrendPoint:
    """One period of a measure over time."""

    period: str
    value: QueryScalar
    rows: int


@dataclass(frozen=True, slots=True)
class Trend:
    """A measure over time, at the grain that suits the data's span."""

    title: str
    grain: str
    points: tuple[TrendPoint, ...]
    sql: str


@dataclass(frozen=True, slots=True)
class BreakdownBar:
    """One category. ``key`` is the normalised label used for filtering."""

    key: str
    label: str
    value: QueryScalar
    rows: int


@dataclass(frozen=True, slots=True)
class Breakdown:
    """The leading categories of one column for the primary measure."""

    title: str
    column: str
    bars: tuple[BreakdownBar, ...]
    categories: int
    sql: str


@dataclass(frozen=True, slots=True)
class HistogramBin:
    """One equal-width range of a measure and the rows inside it."""

    low: float
    high: float
    rows: int


@dataclass(frozen=True, slots=True)
class Histogram:
    """How one measure's values are spread."""

    title: str
    bins: tuple[HistogramBin, ...]
    sql: str


@dataclass(frozen=True, slots=True)
class Insight:
    """One sentence computed from a query result, never written by a model."""

    text: str
    sql: str


@dataclass(frozen=True, slots=True)
class Dashboard:
    """Everything shown for one table under the current filters."""

    relation: str
    relations: tuple[RelationSummary, ...]
    domain: DomainMatch
    filters: tuple[DashboardFilter, ...]
    excluded_totals: tuple[str, ...]
    kpis: tuple[KpiTile, ...]
    trend: Trend | None
    breakdowns: tuple[Breakdown, ...]
    histograms: tuple[Histogram, ...]
    insights: tuple[Insight, ...]
    suggestions: tuple[str, ...]
    computed_by: str = field(default="sql_without_model", init=False)


@dataclass(frozen=True, slots=True)
class _Measure:
    name: str
    additive: bool

    @property
    def function(self) -> str:
        return "SUM" if self.additive else "AVG"

    @property
    def word(self) -> str:
        return "Total" if self.additive else "Average"

    @property
    def expression(self) -> str:
        return f"{self.function}({_quote(self.name)})"

    @property
    def title(self) -> str:
        return f"{self.word} {_readable(self.name)}"


@dataclass(frozen=True, slots=True)
class _Time:
    name: str
    is_year: bool
    grain: str


@dataclass(frozen=True, slots=True)
class _Plan:
    table: LoadedTable
    domain: DomainMatch
    measures: tuple[_Measure, ...]
    dimensions: tuple[str, ...]
    time: _Time | None
    repeated_identifier: str | None
    exclusions: tuple[tuple[str, str], ...]


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _readable(name: str) -> str:
    return name.replace("_", " ").strip()


def _label(column: str) -> str:
    return f"TRIM(CAST({_quote(column)} AS VARCHAR))"


def _normalised(column: str) -> str:
    return f"LOWER({_label(column)})"


def _where(conditions: Sequence[str]) -> str:
    return f" WHERE {' AND '.join(conditions)}" if conditions else ""


def _number(value: object) -> float | None:
    if type(value) in (int, float, Decimal):
        return float(value)  # type: ignore[arg-type]
    return None


def _display(value: float) -> str:
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def _is_identifier(column: ColumnSchema, words: set[str], series: pd.Series) -> bool:
    if words & _IDENTIFIER_WORDS:
        return True
    # A row number counts up without gaps; unique amounts do not.
    present = series.dropna()
    return (
        column.logical_type is LogicalType.INTEGER
        and len(present) > 20
        and present.nunique() == len(present)
        and int(present.max()) - int(present.min()) == len(present) - 1
    )


def _is_year(column: ColumnSchema, words: set[str], series: pd.Series) -> bool:
    present = series.dropna()
    return (
        column.logical_type is LogicalType.INTEGER
        and bool(words & _YEAR_WORDS)
        and present.nunique() >= 2
        and bool(present.between(1000, 3000).all())
    )


def _date_time(name: str, series: pd.Series) -> _Time | None:
    present = series.dropna()
    if present.nunique() < 2:
        return None
    days = (present.max() - present.min()).days
    if days <= _DAILY_SPAN_DAYS:
        grain = "day"
    elif days <= _MONTHLY_SPAN_DAYS:
        grain = "month"
    else:
        grain = "year"
    return _Time(name, False, grain)


def _additive(words: set[str], percent_column: bool) -> bool:
    return (
        not percent_column and not (words & _NOT_ADDITIVE) and bool(words & _ADDITIVE)
    )


def _ranked_measures(measures: list[_Measure], domain: Domain) -> tuple[_Measure, ...]:
    def priority(measure: _Measure) -> tuple[int, bool]:
        words = set(name_tokens(measure.name))
        place = next(
            (i for i, word in enumerate(domain.measures) if word in words),
            len(domain.measures),
        )
        return place, not measure.additive

    return tuple(sorted(measures, key=priority)[:_MAX_MEASURES])


def _plan(table: LoadedTable, schema: Sequence[ColumnSchema]) -> _Plan:
    domain, match = detect_domain([table.relation_name, *(c.name for c in schema)])
    percent_columns = {
        note.column for note in table.value_notes if note.rule == "percent_sign"
    }
    measures: list[_Measure] = []
    dimensions: list[tuple[bool, str]] = []
    dates: list[_Time] = []
    years: list[_Time] = []
    repeated: str | None = None
    for column in schema:
        series = table.data[column.name]
        words = set(name_tokens(column.name))
        if column.logical_type is LogicalType.DATETIME:
            found = _date_time(column.name, series)
            dates.extend([found] if found is not None else [])
        elif _is_year(column, words, series):
            years.append(_Time(column.name, True, "year"))
        elif _is_identifier(column, words, series):
            present = series.dropna()
            if repeated is None and present.nunique() < 0.9 * len(present):
                repeated = column.name
        elif column.logical_type in _NUMERIC:
            if series.nunique() > 1:
                additive = _additive(words, column.name in percent_columns)
                measures.append(_Measure(column.name, additive))
        elif column.logical_type in (LogicalType.STRING, LogicalType.BOOLEAN):
            distinct = series.dropna().astype(str).str.strip().str.casefold().nunique()
            if 2 <= distinct <= _MAX_DIMENSION_VALUES:
                dimensions.append((distinct > _PREFERRED_DIMENSION_VALUES, column.name))
    totals = find_total_rows(table.data, schema)
    return _Plan(
        table=table,
        domain=match,
        measures=_ranked_measures(measures, domain),
        dimensions=tuple(
            name for _, name in sorted(dimensions, key=lambda item: item[0])
        ),
        time=next(iter(dates + years), None),
        repeated_identifier=repeated,
        exclusions=tuple((item.column, item.value) for item in totals),
    )


class DashboardBuilder:
    """Build dashboards for one loaded dataset; column roles are worked out once."""

    def __init__(self, dataset: LoadedDataset, executor: DuckDBExecutor) -> None:
        self._dataset = dataset
        self._executor = executor
        self._schema = SchemaInferer().infer_dataset(dataset)
        self._plans: dict[str, _Plan] = {}
        self._usable = sorted(
            (
                (table, columns)
                for table, columns in zip(
                    dataset.tables, self._schema.tables, strict=True
                )
                if table.row_count and table.column_count
            ),
            key=lambda pair: pair[0].row_count,
            reverse=True,
        )

    def build(
        self,
        relation: str | None = None,
        filters: Sequence[DashboardFilter] = (),
    ) -> Dashboard:
        """Compute one table's dashboard; the largest table is the default."""
        if not self._usable:
            raise DashboardRequestError("This dataset has no rows to chart.")
        name = self._usable[0][0].relation_name if relation is None else relation
        plan = self._plan_for(name)
        for item in filters:
            if item.column not in plan.dimensions:
                raise DashboardRequestError("That column cannot be filtered.")
        return _Build(self._executor, self._dataset, plan, tuple(filters)).dashboard(
            tuple(
                RelationSummary(table.relation_name, table.row_count)
                for table, _ in self._usable
            )
        )

    def _plan_for(self, relation: str) -> _Plan:
        if relation not in self._plans:
            match = next(
                (p for p in self._usable if p[0].relation_name == relation), None
            )
            if match is None:
                raise DashboardRequestError("That table is not in this dataset.")
            self._plans[relation] = _plan(match[0], match[1].columns)
        return self._plans[relation]


class _Build:
    """One dashboard computation under one set of filters."""

    def __init__(
        self,
        executor: DuckDBExecutor,
        dataset: LoadedDataset,
        plan: _Plan,
        filters: tuple[DashboardFilter, ...],
    ) -> None:
        self._executor = executor
        self._dataset = dataset
        self._plan = plan
        self._filters = filters
        self._source = _quote(plan.table.relation_name)

    def _conditions(self, *, ignoring: str | None = None) -> list[str]:
        excluded = [
            f"{_quote(column)} IS DISTINCT FROM {_literal(value)}"
            for column, value in self._plan.exclusions
        ]
        chosen = [
            f"{_normalised(item.column)} = {_literal(item.value)}"
            for item in self._filters
            if item.column != ignoring
        ]
        return excluded + chosen

    def _run(self, sql: str) -> QueryResult | None:
        """One figure that cannot be computed must not cost the whole page."""
        try:
            return self._executor.execute(self._dataset, sql)
        except QueryExecutionError:
            return None

    def _kpi(self, label: str, expression: str) -> KpiTile | None:
        sql = (
            f"SELECT {expression} AS value FROM {self._source}"
            f"{_where(self._conditions())}"
        )
        result = self._run(sql)
        return None if result is None else KpiTile(label, result.rows[0][0], sql)

    def _kpis(self) -> tuple[KpiTile, ...]:
        plan = self._plan
        wanted = [("Rows", "COUNT(*)")]
        if plan.repeated_identifier is not None:
            wanted.append(
                (
                    f"Distinct {_readable(plan.repeated_identifier)}",
                    f"COUNT(DISTINCT {_quote(plan.repeated_identifier)})",
                )
            )
        wanted += [(m.title, m.expression) for m in plan.measures]
        tiles = (self._kpi(label, expr) for label, expr in wanted[:_KPIS_SHOWN])
        return tuple(tile for tile in tiles if tile is not None)

    def _metric(self) -> tuple[str, str]:
        measures = self._plan.measures
        if measures:
            return measures[0].title, measures[0].expression
        return "Rows", "COUNT(*)"

    def _trend(self) -> Trend | None:
        time = self._plan.time
        if time is None:
            return None
        title, metric = self._metric()
        column = _quote(time.name)
        if time.is_year:
            period = f"CAST({column} AS VARCHAR)"
        else:
            formats = {"day": "%Y-%m-%d", "month": "%Y-%m", "year": "%Y"}
            period = (
                f"strftime(DATE_TRUNC('{time.grain}', {column}), "
                f"'{formats[time.grain]}')"
            )
        conditions = [f"{column} IS NOT NULL", *self._conditions()]
        sql = (
            f"SELECT {period} AS period, {metric} AS value, COUNT(*) AS row_count "
            f"FROM {self._source}{_where(conditions)} "
            f"GROUP BY 1 ORDER BY 1 LIMIT {_MAX_TREND_POINTS}"
        )
        result = self._run(sql)
        if result is None or len(result.rows) < 2:
            return None
        return Trend(
            title=f"{title} by {time.grain}",
            grain=time.grain,
            points=tuple(
                TrendPoint(str(row[0]), row[1], int(str(row[2]))) for row in result.rows
            ),
            sql=sql,
        )

    def _breakdown(self, column: str) -> Breakdown | None:
        title, metric = self._metric()
        label = _label(column)
        conditions = [
            f"{label} <> ''",
            *self._conditions(ignoring=column),
        ]
        sql = (
            f"SELECT {_normalised(column)} AS key, MODE({label}) AS label, "
            f"{metric} AS value, COUNT(*) AS row_count, "
            f"COUNT(*) OVER () AS categories "
            f"FROM {self._source}{_where(conditions)} "
            f"GROUP BY 1 ORDER BY value DESC NULLS LAST, 1 LIMIT {_BARS_SHOWN}"
        )
        result = self._run(sql)
        if result is None or not result.rows:
            return None
        return Breakdown(
            title=f"{title} by {_readable(column)}",
            column=column,
            bars=tuple(
                BreakdownBar(str(row[0]), str(row[1]), row[2], int(str(row[3])))
                for row in result.rows
            ),
            categories=int(str(result.rows[0][4])),
            sql=sql,
        )

    def _histogram(self, measure: _Measure) -> Histogram | None:
        value = f"CAST({_quote(measure.name)} AS DOUBLE)"
        conditions = [f"isfinite({value})", *self._conditions()]
        where = _where(conditions)
        bins = _HISTOGRAM_BINS
        sql = (
            f"WITH span AS (SELECT MIN({value}) AS low, "
            f"(MAX({value}) - MIN({value})) / {bins}.0 AS width "
            f"FROM {self._source}{where}) "
            f"SELECT LEAST(CAST(FLOOR(({value} - low) / width) AS INTEGER), "
            f"{bins - 1}) AS bin, COUNT(*) AS row_count, "
            f"ANY_VALUE(low) AS low, ANY_VALUE(width) AS width "
            f"FROM {self._source}, span{where} AND width > 0 GROUP BY 1 ORDER BY 1"
        )
        result = self._run(sql)
        if result is None or not result.rows:
            return None
        counts = {int(str(row[0])): int(str(row[1])) for row in result.rows}
        low = float(str(result.rows[0][2]))
        width = float(str(result.rows[0][3]))
        return Histogram(
            title=f"Spread of {_readable(measure.name)}",
            bins=tuple(
                HistogramBin(
                    low + index * width,
                    low + (index + 1) * width,
                    counts.get(index, 0),
                )
                for index in range(bins)
            ),
            sql=sql,
        )

    def _correlation(self, rows: float) -> Insight | None:
        names = [measure.name for measure in self._plan.measures]
        pairs = list(combinations(names, 2))
        if not pairs or rows < _MIN_CORRELATION_ROWS:
            return None
        columns = ", ".join(
            f"CORR(CAST({_quote(a)} AS DOUBLE), CAST({_quote(b)} AS DOUBLE)) AS c{i}"
            for i, (a, b) in enumerate(pairs)
        )
        sql = f"SELECT {columns} FROM {self._source}{_where(self._conditions())}"
        result = self._run(sql)
        if result is None:
            return None
        known = [
            (number, pair)
            for cell, pair in zip(result.rows[0], pairs, strict=True)
            if (number := _number(cell)) is not None and abs(number) <= 1
        ]
        if not known:
            return None
        value, (first, second) = max(known, key=lambda item: abs(item[0]))
        if abs(value) < _MIN_CORRELATION:
            return None
        direction = "rises" if value > 0 else "falls"
        return Insight(
            f"{_readable(second).capitalize()} {direction} as "
            f"{_readable(first)} rises (correlation {value:.2f}). "
            "This does not show that one causes the other.",
            sql,
        )

    def _insights(
        self,
        kpis: tuple[KpiTile, ...],
        trend: Trend | None,
        breakdowns: tuple[Breakdown, ...],
    ) -> tuple[Insight, ...]:
        found: list[Insight] = []
        measures = self._plan.measures
        lead = measures[0] if measures else None
        # A filtered column still lists all its categories, so its bars cover
        # different rows from the filtered total and cannot be divided by it.
        filtered = {item.column for item in self._filters}
        top = next((b for b in breakdowns if b.column not in filtered), None)
        if lead is not None and lead.additive and top is not None:
            total = next(
                (_number(k.value) for k in kpis if k.label == lead.title), None
            )
            value = _number(top.bars[0].value)
            if total and value is not None and total > 0 and value >= 0:
                found.append(
                    Insight(
                        f"{top.bars[0].label} makes up {value / total:.0%} of "
                        f"{lead.title.lower()}, the largest {_readable(top.column)}.",
                        top.sql,
                    )
                )
        if trend is not None and len(trend.points) >= _MIN_TREND_POINTS_FOR_PEAK:
            numbered = [
                (number, point.period)
                for point in trend.points
                if (number := _number(point.value)) is not None
            ]
            if numbered:
                best, period = max(numbered, key=lambda item: item[0])
                found.append(
                    Insight(
                        f"{self._metric()[0]} peaked in {period} at {_display(best)}.",
                        trend.sql,
                    )
                )
        rows = _number(kpis[0].value) if kpis else None
        correlation = self._correlation(rows or 0.0)
        found.extend([correlation] if correlation is not None else [])
        return tuple(found)

    def _suggestions(
        self, trend: Trend | None, breakdowns: tuple[Breakdown, ...]
    ) -> tuple[str, ...]:
        relation = self._plan.table.relation_name
        questions = [f"How many rows does {relation} have?"]
        measures = self._plan.measures
        lead = measures[0] if measures else None
        if lead is not None:
            questions.append(f"What is the {lead.title.lower()}?")
        if breakdowns:
            top = breakdowns[0]
            label = top.bars[0].label
            column = _readable(top.column)
            questions.append(f"How many rows have {column} equal to {label}?")
            if lead is not None:
                questions.append(
                    f"What is the {lead.title.lower()} where {column} is {label}?"
                )
        if lead is not None and trend is not None:
            questions.append(
                f"What is the {lead.title.lower()} in {trend.points[-1].period}?"
            )
        return tuple(questions)

    def dashboard(self, relations: tuple[RelationSummary, ...]) -> Dashboard:
        plan = self._plan
        kpis = self._kpis()
        trend = self._trend()
        computed = (self._breakdown(c) for c in plan.dimensions[:_MAX_BREAKDOWNS])
        breakdowns = tuple(item for item in computed if item is not None)
        spreads = (self._histogram(m) for m in plan.measures[:_HISTOGRAMS_SHOWN])
        return Dashboard(
            relation=plan.table.relation_name,
            relations=relations,
            domain=plan.domain,
            filters=self._filters,
            excluded_totals=tuple(
                f"{column} = {value}" for column, value in plan.exclusions
            ),
            kpis=kpis,
            trend=trend,
            breakdowns=breakdowns,
            histograms=tuple(item for item in spreads if item is not None),
            insights=self._insights(kpis, trend, breakdowns),
            suggestions=self._suggestions(trend, breakdowns),
        )
