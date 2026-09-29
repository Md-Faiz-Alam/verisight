"""Excel loader for the VeriSight ingestion subsystem."""

from pathlib import Path

import pandas as pd

from verisight.config import Settings
from verisight.ingestion.exceptions import DataLoadError
from verisight.ingestion.models import (
    LoadedTable,
    LoadedWorkbook,
    SourceMetadata,
)
from verisight.ingestion.validation import validate_file

EXCEL_EXTENSIONS = frozenset({".xls", ".xlsx"})


class ExcelLoader:
    """Load Excel workbooks into VeriSight."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def load(self, path: str | Path) -> LoadedWorkbook:
        """Validate and load all worksheets from an Excel workbook."""

        metadata = validate_file(
            path,
            max_size_mb=self._settings.max_upload_size_mb,
        )

        if metadata.file_extension not in EXCEL_EXTENSIONS:
            raise DataLoadError(
                f"ExcelLoader cannot load file type '{metadata.file_extension}'."
            )

        try:
            sheets = pd.read_excel(
                metadata.path,
                sheet_name=None,
            )
        except Exception as exc:
            raise DataLoadError(f"Could not load Excel file: {metadata.path}") from exc

        tables = [
            LoadedTable(
                name=sheet_name,
                data=data,
                source=SourceMetadata(
                    path=metadata.path,
                    file_name=metadata.file_name,
                    file_extension=metadata.file_extension,
                    file_size_bytes=metadata.file_size_bytes,
                    sheet_name=sheet_name,
                ),
            )
            for sheet_name, data in sheets.items()
        ]

        return LoadedWorkbook(
            source=metadata,
            tables=tables,
        )
