"""Domain models for the VeriSight ingestion subsystem."""

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Metadata describing the source of an ingested table."""

    path: Path
    file_name: str
    file_extension: str
    file_size_bytes: int
    sheet_name: str | None = None


@dataclass(slots=True)
class LoadedTable:
    """A tabular dataset loaded into VeriSight."""

    name: str
    data: pd.DataFrame
    source: SourceMetadata
    relation_name: str = field(init=False)

    def __post_init__(self) -> None:
        """Initialize the table's machine-facing relation identity."""

        self.relation_name = self.name

    @property
    def row_count(self) -> int:
        """Return the number of rows in the table."""

        return len(self.data)

    @property
    def column_count(self) -> int:
        """Return the number of columns in the table."""

        return len(self.data.columns)


@dataclass(slots=True)
class LoadedWorkbook:
    """An Excel workbook loaded into VeriSight."""

    source: SourceMetadata
    tables: list[LoadedTable]

    @property
    def table_count(self) -> int:
        """Return the number of loaded worksheet tables."""

        return len(self.tables)


@dataclass(slots=True)
class LoadedDataset:
    """A collection of tables loaded from one or more source files."""

    tables: list[LoadedTable]

    @property
    def table_count(self) -> int:
        """Return the total number of loaded tables."""

        return len(self.tables)

    @property
    def source_count(self) -> int:
        """Return the number of distinct source files."""

        return len({table.source.path for table in self.tables})


IngestionResult = LoadedTable | LoadedWorkbook
