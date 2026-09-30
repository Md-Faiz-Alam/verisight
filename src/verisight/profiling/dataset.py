"""Dataset-level profiling orchestration for VeriSight."""

from verisight.ingestion.models import LoadedDataset
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile, TableProfile
from verisight.profiling.table import TableProfiler


class DatasetProfiler:
    """Coordinate profiling across all tables in a loaded dataset."""

    def __init__(self) -> None:
        self._table_profiler = TableProfiler()

    def profile(
        self,
        *,
        dataset: LoadedDataset,
        schema: DatasetSchema,
    ) -> DatasetProfile:
        """Build a complete profile for a loaded dataset."""

        schema_tables = {
            table_schema.relation_name: table_schema for table_schema in schema.tables
        }

        profiles: list[TableProfile] = []

        for table in dataset.tables:
            try:
                table_schema = schema_tables[table.relation_name]
            except KeyError as exc:
                raise ValueError(
                    f"Schema does not contain table '{table.name}' "
                    f"with relation name '{table.relation_name}'."
                ) from exc

            profiles.append(
                self._table_profiler.profile(
                    table=table,
                    schema=table_schema,
                )
            )

        return DatasetProfile(tables=tuple(profiles))
