"""Table-level profiling orchestration for VeriSight."""

from verisight.ingestion.models import LoadedTable
from verisight.ingestion.schema import TableSchema
from verisight.profiling.column import ColumnProfiler
from verisight.profiling.duplicates import DuplicateAnalyzer
from verisight.profiling.missing import MissingValueAnalyzer
from verisight.profiling.models import ColumnProfile, TableProfile


class TableProfiler:
    """Coordinate profiling across a loaded table."""

    def __init__(self) -> None:
        self._column_profiler = ColumnProfiler()
        self._missing_value_analyzer = MissingValueAnalyzer()
        self._duplicate_analyzer = DuplicateAnalyzer()

    def profile(
        self,
        *,
        table: LoadedTable,
        schema: TableSchema,
    ) -> TableProfile:
        """Build a complete profile for a loaded table."""

        columns = self.profile_columns(
            table=table,
            schema=schema,
        )

        missing_value_statistics = self._missing_value_analyzer.analyze(table.data)
        duplicate_statistics = self._duplicate_analyzer.analyze(table.data)

        return TableProfile(
            name=table.name,
            row_count=len(table.data),
            column_count=len(table.data.columns),
            duplicate_row_count=duplicate_statistics.duplicate_row_count,
            duplicate_row_ratio=duplicate_statistics.duplicate_row_ratio,
            columns=columns,
            missing_value_statistics=missing_value_statistics,
            duplicate_statistics=duplicate_statistics,
        )

    def profile_columns(
        self,
        *,
        table: LoadedTable,
        schema: TableSchema,
    ) -> tuple[ColumnProfile, ...]:
        """Profile table columns using their inferred schema."""

        schema_columns = {column.name: column for column in schema.columns}

        profiles: list[ColumnProfile] = []

        for column_name in table.data.columns:
            name = str(column_name)

            try:
                column_schema = schema_columns[name]
            except KeyError as exc:
                raise ValueError(
                    f"Schema does not contain column '{name}' "
                    f"from table '{table.name}'."
                ) from exc

            profiles.append(
                self._column_profiler.profile(
                    name=name,
                    series=table.data[column_name],
                    logical_type=column_schema.logical_type,
                )
            )

        return tuple(profiles)
