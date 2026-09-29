"""High-level ingestion services for VeriSight."""

from collections.abc import Iterable
from pathlib import Path

from verisight.config import Settings
from verisight.ingestion.dispatcher import FileLoader
from verisight.ingestion.models import (
    LoadedDataset,
    LoadedTable,
    LoadedWorkbook,
)


class DatasetLoader:
    """Load one or more files into a normalized dataset."""

    def __init__(self, settings: Settings) -> None:
        self._file_loader = FileLoader(settings)

    def load(self, paths: Iterable[str | Path]) -> LoadedDataset:
        """Load files and normalize their tables into one dataset."""

        tables: list[LoadedTable] = []

        for path in paths:
            result = self._file_loader.load(path)

            if isinstance(result, LoadedWorkbook):
                tables.extend(result.tables)
            else:
                tables.append(result)

        return LoadedDataset(tables=tables)
