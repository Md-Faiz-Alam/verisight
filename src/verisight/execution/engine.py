"""DuckDB-backed analytical execution for VeriSight."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import duckdb

from verisight.execution.exceptions import (
    QueryResultLimitError,
    QueryRuntimeError,
)
from verisight.execution.models import QueryResult, QueryRow
from verisight.execution.validation import AnalyticalQueryValidator
from verisight.ingestion.models import LoadedDataset


class DuckDBExecutor:
    """Execute analytical queries against a loaded VeriSight dataset."""

    def __init__(
        self,
        *,
        max_result_rows: int = 10_000,
        memory_limit_mb: int = 512,
    ) -> None:
        """Initialize the executor with analytical execution guardrails."""

        if max_result_rows <= 0:
            raise ValueError("Maximum query result rows must be positive.")

        if memory_limit_mb <= 0:
            raise ValueError("Query memory limit must be positive.")

        self._query_validator = AnalyticalQueryValidator()
        self._max_result_rows = max_result_rows
        self._memory_limit_mb = memory_limit_mb

    def execute(
        self,
        dataset: LoadedDataset,
        query: str,
    ) -> QueryResult:
        """Execute a query against dataset relations."""

        self._query_validator.validate(query)

        try:
            with self._connection(dataset) as connection:
                cursor = connection.execute(query)

                columns = tuple(description[0] for description in cursor.description)

                fetched_rows = cursor.fetchmany(self._max_result_rows + 1)
        except duckdb.Error as exc:
            raise QueryRuntimeError(
                f"Analytical query execution failed: {exc}"
            ) from exc

        if len(fetched_rows) > self._max_result_rows:
            raise QueryResultLimitError(
                "Analytical query result exceeded the maximum "
                f"of {self._max_result_rows} rows."
            )

        rows = tuple(cast(QueryRow, tuple(row)) for row in fetched_rows)

        return QueryResult(
            columns=columns,
            rows=rows,
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
                "memory_limit": f"{self._memory_limit_mb}MB",
            },
        )

        try:
            for table in dataset.tables:
                connection.register(
                    table.relation_name,
                    table.data,
                )

            yield connection
        finally:
            connection.close()
