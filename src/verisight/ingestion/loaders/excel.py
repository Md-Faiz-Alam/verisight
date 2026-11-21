"""Excel loader for the VeriSight ingestion subsystem."""

import math
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from typing import Literal, cast
from xml.etree import ElementTree
from zipfile import ZipFile

import pandas as pd
import xlrd
from xlrd.sheet import Sheet

from verisight.config import Settings
from verisight.ingestion.dtypes import infer_types
from verisight.ingestion.exceptions import DataLoadError
from verisight.ingestion.loaders.csv import CsvLoader
from verisight.ingestion.models import (
    LoadedTable,
    LoadedWorkbook,
    SourceMetadata,
    ValueNote,
)
from verisight.ingestion.temporal import parse_iso_datetimes
from verisight.ingestion.validation import validate_file

EXCEL_EXTENSIONS = frozenset({".xls", ".xlsx"})
_TOP_ROWS = 20

# One worksheet: its name, its first rows as source cells, and a reader that
# takes the header row's position and the column count and returns the data.
_Sheet = tuple[str, pd.DataFrame, Callable[[int, int], pd.DataFrame]]


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
        blank_sheets: list[str] = []

        try:
            if metadata.file_extension == ".xlsx":
                _validate_xlsx_cells(
                    metadata.path,
                    max_unpacked_bytes=self._settings.max_excel_uncompressed_mb
                    * 1024
                    * 1024,
                )
                sheets = _xlsx_sheets(metadata.path)
            else:
                sheets = _xls_sheets(metadata.path)
            for sheet_name, top, read_data in sheets:
                if _is_blank(top):
                    blank_sheets.append(sheet_name)
                    continue
                skipped = _header_row(top)
                source_columns = top.iloc[skipped].tolist()
                named, blank_notes = CsvLoader._name_blank_headers(
                    [str(column) for column in source_columns]
                )
                columns, renamed_notes = CsvLoader._rename_duplicates(named)
                data = read_data(skipped, len(source_columns))
                if len(data.columns) != len(source_columns):
                    raise DataLoadError(
                        "Excel data contains fields without source headers."
                    )
                data.columns = pd.Index(columns)
                for column in data.columns:
                    data[column] = _infer_column(_restore_cells(data[column]))

                table = LoadedTable(
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
                title_notes: tuple[ValueNote, ...] = ()
                if skipped:
                    title_notes = (_title_note(top, skipped, columns[0]),)
                table.value_notes = (*blank_notes, *renamed_notes, *title_notes)
                tables.append(table)

        except DataLoadError:
            raise
        except Exception as exc:
            raise DataLoadError(f"Could not load Excel file: {metadata.path}") from exc

        if not tables:
            raise DataLoadError("Excel workbook has no data in any worksheet.")
        if blank_sheets:
            first = tables[0]
            first.value_notes = (
                *first.value_notes,
                ValueNote(
                    column=str(first.data.columns[0]),
                    rule="skipped_blank_sheets",
                    affected_count=len(blank_sheets),
                    examples=tuple(blank_sheets[:3]),
                ),
            )

        return LoadedWorkbook(
            source=metadata,
            tables=tables,
        )


def _xlsx_sheets(path: Path) -> Iterator[_Sheet]:
    """Read ``.xlsx`` worksheets with openpyxl, named so a default cannot change."""
    with pd.ExcelFile(path, engine="openpyxl") as workbook:
        for sheet_name in workbook.sheet_names:
            if not isinstance(sheet_name, str):
                raise DataLoadError("Excel workbook contains a non-string sheet name.")

            def read_data(
                skipped: int, width: int, name: str = sheet_name
            ) -> pd.DataFrame:
                return pd.read_excel(
                    workbook,
                    sheet_name=name,
                    skiprows=skipped,
                    converters={index: _ExcelCell for index in range(width)},
                    keep_default_na=False,
                    na_filter=False,
                )

            # header=None exposes source cells before pandas renames them.
            top = pd.read_excel(
                workbook,
                sheet_name=sheet_name,
                header=None,
                nrows=_TOP_ROWS,
                dtype=object,
                keep_default_na=False,
                na_filter=False,
            )
            yield sheet_name, top, read_data


def _xls_sheets(path: Path) -> Iterator[_Sheet]:
    """Read legacy ``.xls`` worksheets with xlrd directly.

    pandas is retiring its xlrd engine, and no other reader handles the oldest
    BIFF formats, so the cells are read here and converted as that engine did.
    Building object columns directly keeps every source type, as the converters
    do on the ``.xlsx`` path.
    """
    book = xlrd.open_workbook(str(path))
    try:
        for sheet in book.sheets():
            rows = _xls_rows(sheet, book.datemode)

            def read_data(
                skipped: int, width: int, rows: list[list[object]] = rows
            ) -> pd.DataFrame:
                return pd.DataFrame(
                    rows[skipped + 1 :], columns=range(width), dtype=object
                )

            yield sheet.name, pd.DataFrame(rows[:_TOP_ROWS], dtype=object), read_data
    finally:
        book.release_resources()


def _xls_rows(sheet: Sheet, datemode: Literal[0, 1]) -> list[list[object]]:
    """A worksheet's cells, rejecting Excel error values such as ``#DIV/0!``."""
    rows: list[list[object]] = []
    for index in range(sheet.nrows):
        types = sheet.row_types(index)
        if xlrd.XL_CELL_ERROR in types:
            raise DataLoadError("Excel worksheet contains error cells.")
        values = sheet.row_values(index)
        rows.append(
            [
                _xls_cell(value, cell_type, datemode)
                for value, cell_type in zip(values, types, strict=True)
            ]
        )
    return rows


def _xls_cell(value: object, cell_type: int, datemode: Literal[0, 1]) -> object:
    """Convert one ``.xls`` cell exactly as pandas' xlrd engine did.

    Dates become datetimes, and a date on the workbook's epoch day is a time of
    day. Booleans become ``bool``, and whole numbers become ``int``, because
    Excel stores every number as a float. Text and empty cells are unchanged.
    """
    if cell_type == xlrd.XL_CELL_DATE:
        try:
            moment = xlrd.xldate.xldate_as_datetime(cast(float, value), datemode)
        except OverflowError:
            return value
        epoch_day = (1904, 1, 1) if datemode else (1899, 12, 31)
        if moment.timetuple()[:3] == epoch_day:
            return time(moment.hour, moment.minute, moment.second, moment.microsecond)
        return moment
    if cell_type == xlrd.XL_CELL_BOOLEAN:
        return bool(value)
    if cell_type == xlrd.XL_CELL_NUMBER:
        number = cast(float, value)
        if math.isfinite(number) and int(number) == number:
            return int(number)
    return value


def _is_blank(top: pd.DataFrame) -> bool:
    """A sheet with no cells, or only empty ones, holds no table."""
    return top.empty or bool((top == "").to_numpy().all())


def _header_row(top: pd.DataFrame) -> int:
    """Find the header below any title rows; 0 unless one is clearly lower.

    The first row counts as a title only if a later row fills more cells, and
    that row must hold only text, so data is never promoted to column names.
    """
    filled = [sum(cell != "" for cell in row) for row in top.itertuples(index=False)]
    if not filled or filled[0] >= max(filled):
        return 0
    for index in range(1, len(filled)):
        cells = [cell for cell in top.iloc[index].tolist() if cell != ""]
        if filled[index] == max(filled) and all(type(c) is str for c in cells):
            return index
    return 0


def _title_note(top: pd.DataFrame, skipped: int, column: str) -> ValueNote:
    titles = [str(c) for c in top.iloc[:skipped].to_numpy().ravel() if c != ""]
    return ValueNote(
        column=column,
        rule="skipped_title_rows",
        affected_count=skipped,
        examples=tuple(title[:80] for title in titles)[:3],
    )


def _validate_xlsx_cells(path: Path, *, max_unpacked_bytes: int) -> None:
    """Inspect source cells before pandas hides formulas and Excel errors.

    Saved formula results are used without recalculation or freshness checks.
    An explicitly cached empty string is supported; a missing cache is not.
    Inspect worksheet roots rather than assuming particular ZIP entry paths.
    The archive's declared unpacked size is checked first; Python's zipfile
    never reads past a member's declared size, so this bounds parsing memory.
    """
    with ZipFile(path) as archive:
        unpacked = sum(entry.file_size for entry in archive.infolist())
        if unpacked > max_unpacked_bytes:
            raise DataLoadError(
                "Excel workbook expands to more than "
                f"{max_unpacked_bytes // (1024 * 1024)} MB when unpacked."
            )
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
    # ISO date text becomes a date, as it does in a CSV file.
    dates = parse_iso_datetimes(series)
    if dates is not None:
        return dates
    return infer_types(series.to_frame()).iloc[:, 0]
