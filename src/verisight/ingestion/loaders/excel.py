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

        tables: list[LoadedTable] = []

        try:
            with pd.ExcelFile(metadata.path) as workbook:
                for sheet_name in workbook.sheet_names:
                    if not isinstance(sheet_name, str):
                        raise DataLoadError(
                            "Excel workbook contains a non-string sheet name."
                        )

                    data = workbook.parse(
                        sheet_name=sheet_name,
                        dtype=object,
                        keep_default_na=False,
                        na_values=[""],
                    )
                    for column in data.columns:
                        data[column] = _infer_column(data[column])

                    tables.append(
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
                    )

        except DataLoadError:
            raise
        except Exception as exc:
            raise DataLoadError(f"Could not load Excel file: {metadata.path}") from exc

        return LoadedWorkbook(
            source=metadata,
            tables=tables,
        )


def _infer_column(series: pd.Series) -> pd.Series:
    """Infer native types without routing exact integers through floats."""
    values = series.dropna().tolist()
    integers = [value for value in values if type(value) is int]

    if integers and len(integers) == len(values):
        minimum = min(integers)
        maximum = max(integers)
        has_missing = bool(series.isna().any())
        if minimum >= -(2**63) and maximum <= 2**63 - 1:
            return series.astype("Int64" if has_missing else "int64")
        if minimum >= 0 and maximum <= 2**64 - 1:
            return series.astype("UInt64" if has_missing else "uint64")
        return series

    if any(abs(value) > 2**53 - 1 for value in integers):
        return series
    return series.infer_objects()
