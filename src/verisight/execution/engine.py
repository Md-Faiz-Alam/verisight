"""DuckDB-backed analytical execution for VeriSight."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import cast

import duckdb

from verisight.execution.exceptions import QueryExecutionError
from verisight.execution.models import QueryResult, QueryRow
from verisight.execution.validation import AnalyticalQueryValidator
from verisight.ingestion.models import LoadedDataset


class DuckDBExecutor:
    """Execute analytical queries against a loaded VeriSight dataset."""

    def __init__(self) -> None:
        self._query_validator = AnalyticalQueryValidator()

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

                rows = tuple(cast(QueryRow, tuple(row)) for row in cursor.fetchall())
        except duckdb.Error as exc:
            raise QueryExecutionError(
                f"Analytical query execution failed: {exc}"
            ) from exc

        return QueryResult(
            columns=columns,
            rows=rows,
        )

    @contextmanager
    def _connection(
        self,
        dataset: LoadedDataset,
    ) -> Iterator[duckdb.DuckDBPyConnection]:
        """Create a temporary connection with dataset tables registered."""

        connection = duckdb.connect(database=":memory:")

        try:
            for table in dataset.tables:
                connection.register(
                    table.relation_name,
                    table.data,
                )

            yield connection
        finally:
            connection.close()
