"""DuckDB-backed analytical execution for VeriSight."""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from threading import TIMEOUT_MAX, Event, Timer
from time import monotonic
from uuid import UUID

import duckdb
import pandas as pd
from pandas.api.types import is_object_dtype

from verisight.execution.context import PopulationFilter, QueryContextBuilder
from verisight.execution.deadline import (
    InvestigationDeadlineExceeded,
    check_deadline,
    remaining_seconds,
)
from verisight.execution.exceptions import (
    QueryDataBindingError,
    QueryResultLimitError,
    QueryRuntimeError,
    QueryTimeoutError,
    QueryValidationError,
)
from verisight.execution.models import QueryResult, QueryRow, QueryScalar
from verisight.execution.validation import (
    AnalyticalQueryValidator,
    validate_dataset_relations,
)
from verisight.ingestion.models import LoadedDataset, LoadedTable
from verisight.ingestion.schema import SchemaInferer
from verisight.serialization import to_jsonable


class DuckDBExecutor:
    """Execute analytical queries against a loaded VeriSight dataset."""

    def __init__(
        self,
        *,
        max_result_rows: int = 10_000,
        max_result_bytes: int = 1_048_576,
        memory_limit_mb: int = 512,
        execution_timeout_seconds: float = 30.0,
        temp_storage_limit_mb: int = 1_024,
        population: tuple[PopulationFilter, ...] = (),
    ) -> None:
        """Initialize the executor with analytical execution guardrails."""

        if max_result_rows <= 0:
            raise ValueError("Maximum query result rows must be positive.")

        if type(max_result_bytes) is not int or max_result_bytes <= 0:
            raise ValueError("Maximum query result bytes must be a positive integer.")

        if memory_limit_mb <= 0:
            raise ValueError("Query memory limit must be positive.")

        if not 0 < execution_timeout_seconds <= TIMEOUT_MAX:
            raise ValueError(
                "Query execution timeout must be finite, positive, and within "
                "the platform timer limit."
            )

        if temp_storage_limit_mb <= 0:
            raise ValueError("Query temporary storage limit must be positive.")

        self._population = population
        self._query_validator = AnalyticalQueryValidator()
        self._max_result_rows = max_result_rows
        self._max_result_bytes = max_result_bytes
        self._memory_limit_mb = memory_limit_mb
        self._execution_timeout_seconds = execution_timeout_seconds
        self._temp_storage_limit_mb = temp_storage_limit_mb

    def execute(
        self,
        dataset: LoadedDataset,
        query: str,
    ) -> QueryResult:
        """Execute within row and compact UTF-8 JSON result limits.

        Bytes include column names, scalar values, and JSON structure, using
        ensure_ascii=False and no optional whitespace. Reject oversized output
        without truncating it. The budget applies after DuckDB produces cells;
        it is not a bound on native allocations or total process memory.
        Cancellation is cooperative: expired queries are rejected at dispatch,
        fetch, and completion boundaries, with repeated native interrupts until
        execution unwinds. This is not a hard process termination deadline.
        """

        check_deadline()
        # Loaded datasets remain mutable; recheck identities before registration.
        dataset.validate_relation_names()
        for table in dataset.tables:
            table.validate_column_names()
        if self._population != ():
            QueryContextBuilder().build(
                SchemaInferer().infer_dataset(dataset), population=self._population
            )
        self._query_validator.validate(query)
        allowed_relations = frozenset(
            table.relation_name.lower() for table in dataset.tables
        )

        validate_dataset_relations(query, allowed_relations)

        try:
            with self._connection(dataset) as connection:
                timed_out = Event()
                finished = Event()

                def interrupt_query() -> None:
                    timed_out.set()
                    connection.interrupt()
                    # An interrupt before DuckDB starts a query can be lost.
                    # Keep interrupting until the owning thread stops using it.
                    while not finished.wait(0.01):
                        connection.interrupt()

                timeout_seconds = remaining_seconds(self._execution_timeout_seconds)
                shared_deadline_limited = (
                    timeout_seconds < self._execution_timeout_seconds
                )
                expires = monotonic() + timeout_seconds

                def check_timeout() -> None:
                    check_deadline()
                    if timed_out.is_set() or monotonic() >= expires:
                        if shared_deadline_limited:
                            raise InvestigationDeadlineExceeded(
                                "Investigation time budget was exhausted."
                            ) from None
                        raise QueryTimeoutError(
                            "Analytical query exceeded the execution timeout "
                            f"of {self._execution_timeout_seconds:g} seconds."
                        )

                timer = Timer(timeout_seconds, interrupt_query)
                timer.daemon = True
                timer.start()

                try:
                    check_timeout()
                    cursor = connection.execute(query)
                    check_timeout()

                    columns = tuple(
                        description[0] for description in cursor.description
                    )

                    # Account for both empty arrays and the enclosing object.
                    size = len(b'{"columns":[],"rows":[]}')
                    self._check_result_bytes(size)
                    for index, column in enumerate(columns):
                        size = self._add_result_bytes(size + int(index > 0), column)

                    rows: list[QueryRow] = []
                    while True:
                        check_timeout()
                        fetched = cursor.fetchone()
                        check_timeout()
                        if fetched is None:
                            break
                        if len(rows) >= self._max_result_rows:
                            raise QueryResultLimitError(
                                "Analytical query result exceeded the maximum "
                                f"of {self._max_result_rows} rows."
                            )
                        row = tuple(self._query_scalar(value) for value in fetched)
                        size += 2 + int(bool(rows))
                        for index, value in enumerate(row):
                            size = self._add_result_bytes(size + int(index > 0), value)
                        self._check_result_bytes(size)
                        rows.append(row)
                    check_timeout()
                except duckdb.Error as exc:
                    check_timeout()
                    raise QueryRuntimeError(
                        f"Analytical query execution failed: {exc}"
                    ) from exc
                finally:
                    finished.set()
                    timer.cancel()
                    timer.join()

        except (QueryRuntimeError, QueryTimeoutError):
            raise

        check_deadline()
        return QueryResult(
            columns=columns,
            rows=tuple(rows),
        )

    def _add_result_bytes(self, used: int, value: QueryScalar) -> int:
        """Count the public scalar representation without encoding huge strings."""
        if isinstance(value, str):
            # UTF-8 JSON is never shorter than the source character count.
            self._check_result_bytes(used + len(value))
        encoded = json.dumps(
            to_jsonable(value),
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        total = used + len(encoded)
        self._check_result_bytes(total)
        return total

    def _check_result_bytes(self, size: int) -> None:
        if size > self._max_result_bytes:
            raise QueryResultLimitError(
                "Analytical query result exceeded the maximum "
                f"of {self._max_result_bytes} bytes of compact UTF-8 JSON."
            )

    @staticmethod
    def _query_scalar(value: object) -> QueryScalar:
        """Reject unsupported SQL values before they become observations."""
        if value is None or isinstance(
            value,
            (str, int, float, bool, date, datetime, time, timedelta, Decimal, UUID),
        ):
            return value
        raise QueryValidationError(
            "Analytical query returned an unsupported result type. "
            "Return scalar columns instead of nested or binary values."
        )

    @contextmanager
    def _connection(
        self,
        dataset: LoadedDataset,
    ) -> Iterator[duckdb.DuckDBPyConnection]:
        """Create an isolated guarded connection with dataset tables registered."""

        connection = duckdb.connect(
            database=":memory:",
            config={
                "enable_external_access": "false",
                "autoload_known_extensions": "false",
                "autoinstall_known_extensions": "false",
                "memory_limit": f"{self._memory_limit_mb}MB",
                "max_temp_directory_size": (f"{self._temp_storage_limit_mb}MB"),
            },
        )

        try:
            for table in dataset.tables:
                filters = tuple(
                    item
                    for item in self._population
                    if item.relation == table.relation_name
                )
                if filters:
                    self._register_table(connection, table, filters)
                else:
                    self._register_table(connection, table)

            yield connection
        finally:
            connection.close()

    @staticmethod
    def _register_table(
        connection: duckdb.DuckDBPyConnection,
        table: LoadedTable,
        population: tuple[PopulationFilter, ...] = (),
    ) -> None:
        """Bind object-backed numbers through explicit lossless decimal types.

        DuckDB may infer DOUBLE for mixed integers/floats or even Decimal
        columns. Bind decimal text and cast to an explicitly checked common
        precision and scale instead. Source frames are never modified.
        """
        prepared: pd.DataFrame | None = None
        projections: list[str] = []
        for column in table.data.columns:
            quoted = '"' + str(column).replace('"', '""') + '"'
            series = table.data[column]
            if not is_object_dtype(series.dtype):
                projections.append(quoted)
                continue
            values = series.dropna()
            if values.empty or not all(
                type(value) in (int, float, Decimal) for value in values
            ):
                projections.append(quoted)
                continue

            decimals = [Decimal(str(value)) for value in values]
            if not all(value.is_finite() for value in decimals):
                raise QueryDataBindingError(
                    "Object-backed numerical data must be finite for exact SQL binding."
                )
            decimals = [value if value else Decimal(0) for value in decimals]
            scale = max(max(0, -int(value.as_tuple().exponent)) for value in decimals)
            integer_digits = max(
                (max(0, value.adjusted() + 1) for value in decimals if value),
                default=0,
            )
            precision = max(1, integer_digits + scale)
            if precision > 38:
                raise QueryDataBindingError(
                    "Object-backed numerical data exceeds DuckDB's exact "
                    "decimal precision limit of 38 digits."
                )

            if prepared is None:
                prepared = table.data.copy(deep=True)
            formatted = iter(format(value, "f") for value in decimals)
            prepared[column] = [
                None if missing else next(formatted) for missing in series.isna()
            ]
            projections.append(
                f"CAST({quoted} AS DECIMAL({precision},{scale})) AS {quoted}"
            )

        if prepared is None and not population:
            connection.register(table.relation_name, table.data)
            return
        relation = connection.from_df(prepared if prepared is not None else table.data)
        if prepared is not None:
            relation = relation.project(", ".join(projections))
        for item in population:
            column_expression = duckdb.SQLExpression(
                '"' + item.column.replace('"', '""') + '"'
            )
            predicate = column_expression == duckdb.ConstantExpression(item.values[0])
            for value in item.values[1:]:
                predicate = predicate | (
                    column_expression == duckdb.ConstantExpression(value)
                )
            relation = relation.filter(predicate)
        relation.create_view(table.relation_name, replace=True)
