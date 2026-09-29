"""Loader dispatch for the VeriSight ingestion subsystem."""

from pathlib import Path
from typing import Protocol

from verisight.config import Settings
from verisight.ingestion.exceptions import UnsupportedFileTypeError
from verisight.ingestion.loaders.csv import CsvLoader
from verisight.ingestion.loaders.excel import ExcelLoader
from verisight.ingestion.loaders.json import JsonLoader
from verisight.ingestion.models import IngestionResult


class IngestionLoader(Protocol):
    """Interface required by the file loader registry."""

    def load(self, path: str | Path) -> IngestionResult:
        """Load an ingestion source."""
        ...


class FileLoader:
    """Dispatch supported files to their appropriate loader."""

    def __init__(self, settings: Settings) -> None:
        self._loaders: dict[str, IngestionLoader] = {
            ".csv": CsvLoader(settings),
            ".json": JsonLoader(settings),
            ".xls": ExcelLoader(settings),
            ".xlsx": ExcelLoader(settings),
        }

    def load(self, path: str | Path) -> IngestionResult:
        """Load a supported file using its registered loader."""

        file_path = Path(path).expanduser()
        extension = file_path.suffix.lower()

        try:
            loader = self._loaders[extension]
        except KeyError as exc:
            raise UnsupportedFileTypeError(
                f"Unsupported file type '{extension or '<none>'}'. "
                f"Supported types: {', '.join(sorted(self._loaders))}"
            ) from exc

        return loader.load(file_path)
