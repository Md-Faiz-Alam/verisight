"""Loader dispatch for the VeriSight ingestion subsystem."""

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

from verisight.config import Settings
from verisight.ingestion.exceptions import (
    FileValidationError,
    UnsupportedFileTypeError,
)
from verisight.ingestion.loaders.csv import CsvLoader
from verisight.ingestion.loaders.excel import ExcelLoader
from verisight.ingestion.loaders.json import JsonLoader
from verisight.ingestion.models import CsvReadOptions, IngestionResult


class IngestionLoader(Protocol):
    """Interface required by the file loader registry."""

    def load(self, path: str | Path) -> IngestionResult:
        """Load an ingestion source."""
        ...


class FileLoader:
    """Dispatch supported files to their appropriate loader."""

    def __init__(
        self,
        settings: Settings,
        *,
        csv_options: Mapping[str | Path, CsvReadOptions] | None = None,
    ) -> None:
        self._csv_options: dict[Path, CsvReadOptions] = {}
        if csv_options is not None:
            if not isinstance(csv_options, Mapping):
                raise FileValidationError(
                    "CSV options must be a path-to-options mapping."
                )
            for path, options in csv_options.items():
                if not isinstance(path, (str, Path)) or not str(path).strip():
                    raise FileValidationError(
                        "CSV option keys must be nonblank file paths."
                    )
                if not isinstance(options, CsvReadOptions):
                    raise FileValidationError(
                        "CSV option values must be CsvReadOptions objects."
                    )
                resolved = Path(path).expanduser().resolve()
                if resolved.suffix.lower() != ".csv":
                    raise FileValidationError("CSV options require a .csv input path.")
                if resolved in self._csv_options:
                    raise FileValidationError(
                        "CSV options contain duplicate resolved paths."
                    )
                self._csv_options[resolved] = options
        self._loaders: dict[str, IngestionLoader] = {
            ".csv": CsvLoader(settings),
            ".json": JsonLoader(settings),
            ".xls": ExcelLoader(settings),
            ".xlsx": ExcelLoader(settings),
        }

    def load(self, path: str | Path) -> IngestionResult:
        """Load a supported file using its registered loader."""

        try:
            file_path = Path(path).expanduser()
        except TypeError as exc:
            raise FileValidationError(
                "Dataset file path must be a string or path."
            ) from exc

        if file_path.is_dir():
            raise FileValidationError(f"Path is not a file: {file_path}")

        extension = file_path.suffix.lower()

        try:
            loader = self._loaders[extension]
        except KeyError as exc:
            raise UnsupportedFileTypeError(
                f"Unsupported file type '{extension or '<none>'}'. "
                f"Supported types: {', '.join(sorted(self._loaders))}"
            ) from exc

        if isinstance(loader, CsvLoader):
            return loader.load(
                file_path,
                options=self._csv_options.get(file_path.resolve()),
            )
        return loader.load(file_path)
