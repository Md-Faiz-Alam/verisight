"""JSON loader for the VeriSight ingestion subsystem."""

import json
from pathlib import Path
from typing import Any

import pandas as pd

from verisight.config import Settings
from verisight.ingestion.exceptions import DataLoadError
from verisight.ingestion.loaders.base import BaseTableLoader
from verisight.ingestion.models import LoadedTable
from verisight.ingestion.validation import validate_file


class JsonLoader(BaseTableLoader):
    """Load tabular JSON files into VeriSight."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def load(self, path: str | Path) -> LoadedTable:
        """Validate and load a JSON file."""

        metadata = validate_file(
            path,
            max_size_mb=self._settings.max_upload_size_mb,
        )

        if metadata.file_extension != ".json":
            raise DataLoadError(
                f"JsonLoader cannot load file type '{metadata.file_extension}'."
            )

        try:
            with metadata.path.open(
                "r",
                encoding="utf-8-sig",
            ) as file:
                payload: Any = json.load(file)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise DataLoadError(f"Could not load JSON file: {metadata.path}") from exc

        data = self._to_dataframe(
            payload,
            path=metadata.path,
        )

        return LoadedTable(
            name=metadata.path.stem,
            data=data,
            source=metadata,
        )

    @staticmethod
    def _to_dataframe(
        payload: Any,
        *,
        path: Path,
    ) -> pd.DataFrame:
        """Convert a supported JSON structure into a DataFrame."""

        if isinstance(payload, dict):
            return pd.DataFrame([payload])

        if isinstance(payload, list):
            if not payload:
                return pd.DataFrame()

            if not all(isinstance(item, dict) for item in payload):
                raise DataLoadError(f"JSON array must contain objects: {path}")

            return pd.DataFrame(payload)

        raise DataLoadError(f"JSON root must be an object or array of objects: {path}")
