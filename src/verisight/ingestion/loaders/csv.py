"""CSV loader for the VeriSight ingestion subsystem."""

from pathlib import Path

import pandas as pd

from verisight.config import Settings
from verisight.ingestion.exceptions import DataLoadError
from verisight.ingestion.loaders.base import BaseTableLoader
from verisight.ingestion.models import LoadedTable
from verisight.ingestion.validation import validate_file


class CsvLoader(BaseTableLoader):
    """Load CSV files into VeriSight."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def load(self, path: str | Path) -> LoadedTable:
        """Validate and load a CSV file."""

        metadata = validate_file(
            path,
            max_size_mb=self._settings.max_upload_size_mb,
        )

        if metadata.file_extension != ".csv":
            raise DataLoadError(
                f"CsvLoader cannot load file type '{metadata.file_extension}'."
            )

        try:
            data = pd.read_csv(metadata.path)
        except Exception as exc:
            raise DataLoadError(f"Could not load CSV file: {metadata.path}") from exc

        return LoadedTable(
            name=metadata.path.stem,
            data=data,
            source=metadata,
        )
