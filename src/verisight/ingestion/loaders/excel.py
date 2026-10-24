"""Excel loader for the VeriSight ingestion subsystem."""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast
from xml.etree import ElementTree
from zipfile import ZipFile

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
# xlrd's public XL_CELL_ERROR cell type, before pandas converts it to NaN.
_XLS_ERROR_CELL_TYPE = 5


class _XlsSheet(Protocol):
    """The xlrd sheet attributes used for source-cell validation."""

    @property
    def nrows(self) -> int: ...

    def row_types(self, rowx: int) -> Sequence[int]: ...


class _XlsBook(Protocol):
    """The xlrd workbook operation used by the legacy Excel path."""

    def sheet_by_name(self, sheet_name: str) -> _XlsSheet: ...


@dataclass(frozen=True, slots=True, eq=False)
class _ExcelCell:
    """Prevent parser inference and equality caching from merging source types."""

    value: object


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
            if metadata.file_extension == ".xlsx":
                _validate_xlsx_cells(metadata.path)
            with pd.ExcelFile(metadata.path) as workbook:
                for sheet_name in workbook.sheet_names:
                    if not isinstance(sheet_name, str):
                        raise DataLoadError(
                            "Excel workbook contains a non-string sheet name."
                        )

                    if metadata.file_extension == ".xls":
                        legacy_book = cast(_XlsBook, workbook.book)
                        sheet = legacy_book.sheet_by_name(sheet_name)
                        for row in range(sheet.nrows):
                            if _XLS_ERROR_CELL_TYPE in sheet.row_types(row):
                                raise DataLoadError(
                                    "Excel worksheet contains error cells."
                                )

                    # header=None exposes source cells before pandas renames them.
                    headers = workbook.parse(
                        sheet_name=sheet_name,
                        header=None,
                        nrows=1,
                        dtype=object,
                        keep_default_na=False,
                        na_filter=False,
                    )
                    source_columns = [] if headers.empty else headers.iloc[0].tolist()
                    if any(not str(column).strip() for column in source_columns):
                        raise DataLoadError("Excel column headers must not be blank.")
                    if not pd.Index(source_columns).is_unique:
                        raise DataLoadError(
                            "Excel contains duplicate source column headers."
                        )
                    data = workbook.parse(
                        sheet_name=sheet_name,
                        converters={
                            index: _ExcelCell for index in range(len(source_columns))
                        },
                        keep_default_na=False,
                        na_filter=False,
                    )
                    if len(data.columns) != len(source_columns):
                        raise DataLoadError(
                            "Excel data contains fields without source headers."
                        )
                    for column in data.columns:
                        data[column] = _infer_column(_restore_cells(data[column]))

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


def _validate_xlsx_cells(path: Path) -> None:
    """Inspect source cells before pandas hides formulas and Excel errors.

    Saved formula results are used without recalculation or freshness checks.
    An explicitly cached empty string is supported; a missing cache is not.
    Inspect worksheet roots rather than assuming particular ZIP entry paths.
    """
    with ZipFile(path) as archive:
        for entry in archive.infolist():
            with archive.open(entry) as source:
                events = ElementTree.iterparse(source, events=("start", "end"))
                try:
                    _, root = next(events)
                except ElementTree.ParseError:
                    continue
                if root.tag.rsplit("}", 1)[-1] != "worksheet":
                    continue
                namespace = root.tag.removesuffix("worksheet")
                parents = [root]
                for event, element in events:
                    if event == "start":
                        parents.append(element)
                        continue
                    if element.tag == namespace + "c":
                        if element.get("t") == "e":
                            raise DataLoadError("Excel worksheet contains error cells.")
                        if element.find(namespace + "f") is not None:
                            cached = element.find(namespace + "v")
                            if cached is None or (
                                cached.text is None and element.get("t") != "str"
                            ):
                                raise DataLoadError(
                                    "Excel formula has no saved result. Recalculate "
                                    "and save the workbook or export values "
                                    "before loading."
                                )
                    if element.tag == namespace + "row":
                        parents[-2].remove(element)
                    parents.pop()


def _restore_cells(series: pd.Series) -> pd.Series:
    """Restore scalars into an object series before applying application inference."""
    values = [
        value.value if isinstance(value, _ExcelCell) else value
        for value in series.tolist()
    ]
    return pd.Series(
        [None if type(value) is str and value == "" else value for value in values],
        index=series.index,
        name=series.name,
        dtype=object,
    )


def _infer_column(series: pd.Series) -> pd.Series:
    """Infer native types without routing exact integers through floats."""
    values = series.dropna().tolist()
    booleans = [value for value in values if type(value) is bool]
    if booleans:
        if len(booleans) == len(values):
            return series.astype("boolean" if series.isna().any() else "bool")
        return series
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
