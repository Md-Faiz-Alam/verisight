"""Domain models for the VeriSight ingestion subsystem."""

import codecs
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from verisight.ingestion.exceptions import DataLoadError, TableValidationError

_ASCII_LOWERCASE = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"
)


@dataclass(frozen=True, slots=True)
class CsvReadOptions:
    """Explicit CSV parsing choices for one input; None selects automatic mode."""

    encoding: str | None = None
    delimiter: str | None = None

    def __post_init__(self) -> None:
        if self.encoding is not None:
            if not isinstance(self.encoding, str) or not self.encoding.strip():
                raise DataLoadError("CSV encoding must be a nonblank codec name.")
            try:
                codecs.lookup(self.encoding)
            except LookupError as exc:
                raise DataLoadError("CSV encoding is not recognized.") from exc
        if self.delimiter is not None and (
            not isinstance(self.delimiter, str)
            or len(self.delimiter) != 1
            or self.delimiter in '\r\n\x00"'
        ):
            raise DataLoadError(
                "CSV delimiter must be one character other than "
                "a quote, NUL, or newline."
            )


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    """Metadata describing the source of an ingested table."""

    path: Path
    file_name: str
    file_extension: str
    file_size_bytes: int
    sheet_name: str | None = None
    csv_encoding: str | None = None
    csv_delimiter: str | None = None


@dataclass(slots=True)
class LoadedTable:
    """A tabular dataset loaded into VeriSight."""

    name: str
    data: pd.DataFrame
    source: SourceMetadata
    relation_name: str = field(init=False)

    def __post_init__(self) -> None:
        """Validate the table and initialize its relation identity."""

        self.validate_column_names()
        self.relation_name = self.name

    def validate_column_names(self) -> None:
        """Reject unusable or ambiguous SQL names without changing source labels."""

        duplicated = self.data.columns.duplicated(keep=False)

        if duplicated.any():
            duplicate_columns = self.data.columns[duplicated].unique().tolist()
            formatted_columns = ", ".join(repr(column) for column in duplicate_columns)
            raise TableValidationError(
                f"Table '{self.name}' contains duplicate column names: "
                f"{formatted_columns}."
            )

        names = tuple(str(column) for column in self.data.columns)
        if any(not name.strip() for name in names):
            raise TableValidationError("Table column names must not be blank.")
        if any("\x00" in name for name in names):
            raise TableValidationError(
                "Table column names must not contain NUL characters."
            )

        # DuckDB stringifies column labels and compares identifiers using
        # ASCII case-insensitive matching, even when they are quoted.
        # Unicode casefolding would incorrectly merge distinct identifiers.
        identifiers = pd.Index(name.translate(_ASCII_LOWERCASE) for name in names)
        ambiguous = identifiers.duplicated(keep=False)
        if ambiguous.any():
            formatted_columns = ", ".join(
                repr(column) for column in self.data.columns[ambiguous]
            )
            raise TableValidationError(
                f"Table '{self.name}' contains ambiguous SQL column names: "
                f"{formatted_columns}. Column names must remain distinct after "
                "conversion to strings and ASCII case-insensitive matching."
            )

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
    """A collection of tables loaded from one or more source files.

    Callers must synchronize mutations with execution; validation does not
    lock the table list, relation names, or DataFrames.
    """

    tables: list[LoadedTable]

    def __post_init__(self) -> None:
        """Validate dataset-level table invariants."""

        self.validate_relation_names()

    def validate_relation_names(self) -> None:
        """Reject ASCII case-insensitive collisions without renaming tables."""

        seen: set[str] = set()
        duplicates: list[str] = []

        for table in self.tables:
            relation_name = table.relation_name.translate(_ASCII_LOWERCASE)

            if relation_name in seen and relation_name not in duplicates:
                duplicates.append(relation_name)

            seen.add(relation_name)

        if not duplicates:
            return

        formatted_names = ", ".join(repr(name) for name in duplicates)

        raise TableValidationError(
            f"Dataset contains duplicate relation names: {formatted_names}."
        )

    @property
    def table_count(self) -> int:
        """Return the total number of loaded tables."""

        return len(self.tables)

    @property
    def source_count(self) -> int:
        """Return the number of distinct source files."""

        return len({table.source.path for table in self.tables})


IngestionResult = LoadedTable | LoadedWorkbook
