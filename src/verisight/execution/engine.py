"""DuckDB-backed analytical execution for VeriSight."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from threading import Event, Timer
from uuid import UUID

import duckdb
import pandas as pd
from pandas.api.types import is_object_dtype

from verisight.execution.deadline import check_deadline, remaining_seconds
from verisight.execution.exceptions import (
    QueryResultLimitError,
    QueryRuntimeError,
    QueryTimeoutError,
    QueryValidationError,
)
from verisight.execution.models import QueryResult, QueryScalar
from verisight.execution.validation import (
    AnalyticalQueryValidator,
    validate_dataset_relations,
)
from verisight.ingestion.models import LoadedDataset, LoadedTable


class DuckDBExecutor:
    """Execute analytical queries against a loaded VeriSight dataset."""

    def __init__(
        self,
        *,
        max_result_rows: int = 10_000,
        memory_limit_mb: int = 512,
        execution_timeout_seconds: float = 30.0,
        temp_storage_limit_mb: int = 1_024,
    ) -> None:
        """Initialize the executor with analytical execution guardrails."""

        if max_result_rows <= 0:
            raise ValueError("Maximum query result rows must be positive.")

        if memory_limit_mb <= 0:
            raise ValueError("Query memory limit must be positive.")

        if execution_timeout_seconds <= 0:
            raise ValueError("Query execution timeout must be positive.")

        if temp_storage_limit_mb <= 0:
            raise ValueError("Query temporary storage limit must be positive.")

        self._query_validator = AnalyticalQueryValidator()
        self._max_result_rows = max_result_rows
        self._memory_limit_mb = memory_limit_mb
        self._execution_timeout_seconds = execution_timeout_seconds
        self._temp_storage_limit_mb = temp_storage_limit_mb

    def execute(
        self,
        dataset: LoadedDataset,
        query: str,
    ) -> QueryResult:
        """Execute a query against dataset relations."""

        check_deadline()
        # Loaded datasets remain mutable; recheck identities before registration.
        dataset.validate_relation_names()
        self._query_validator.validate(query)
        allowed_relations = frozenset(
            table.relation_name.lower() for table in dataset.tables
        )

        validate_dataset_relations(query, allowed_relations)

        try:
            with self._connection(dataset) as connection:
                timed_out = Event()

                def interrupt_query() -> None:
                    timed_out.set()
                    connection.interrupt()

                timer = Timer(
                    remaining_seconds(self._execution_timeout_seconds),
                    interrupt_query,
                )
                timer.daemon = True
                timer.start()

                try:
                    cursor = connection.execute(query)

                    columns = tuple(
                        description[0] for description in cursor.description
                    )

                    fetched_rows = cursor.fetchmany(self._max_result_rows + 1)
                except duckdb.Error as exc:
                    check_deadline()
                    if timed_out.is_set():
                        raise QueryTimeoutError(
                            "Analytical query exceeded the execution timeout "
                            f"of {self._execution_timeout_seconds:g} seconds."
                        ) from exc

                    raise QueryRuntimeError(
                        f"Analytical query execution failed: {exc}"
                    ) from exc
                finally:
                    timer.cancel()
                    timer.join()

        except (QueryRuntimeError, QueryTimeoutError):
            raise

        check_deadline()
        if len(fetched_rows) > self._max_result_rows:
            raise QueryResultLimitError(
                "Analytical query result exceeded the maximum "
                f"of {self._max_result_rows} rows."
            )

        rows = tuple(
            tuple(self._query_scalar(value) for value in row) for row in fetched_rows
        )

        return QueryResult(
            columns=columns,
            rows=rows,
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
                self._register_table(connection, table)

            yield connection
        finally:
            connection.close()

    @staticmethod
    def _register_table(
        connection: duckdb.DuckDBPyConnection, table: LoadedTable
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
                raise QueryRuntimeError(
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
                raise QueryRuntimeError(
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

        if prepared is None:
            connection.register(table.relation_name, table.data)
        else:
            connection.from_df(prepared).project(", ".join(projections)).create_view(
                table.relation_name, replace=True
            )
