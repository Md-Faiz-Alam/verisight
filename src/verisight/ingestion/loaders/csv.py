"""CSV loader for the VeriSight ingestion subsystem."""

import codecs
import csv
from dataclasses import replace
from decimal import Decimal
from io import StringIO
from pathlib import Path

import pandas as pd

from verisight.config import Settings
from verisight.ingestion.exceptions import DataLoadError
from verisight.ingestion.loaders.base import BaseTableLoader
from verisight.ingestion.models import CsvReadOptions, LoadedTable
from verisight.ingestion.validation import validate_file

_MAX_SAFE_FLOAT_INTEGER = 2**53 - 1
_BOOLEAN_LITERALS = frozenset({"true", "false"})

_INTEGER_PATTERN = r"[+-]?[0-9]+"
_NUMERIC_PATTERN = (
    r"[+-]?(?:"
    r"(?:[0-9]+(?:\.[0-9]*)?)"
    r"|(?:\.[0-9]+)"
    r")(?:[eE][+-]?[0-9]+)?"
)

_CSV_DELIMITERS = ",;\t|"
_CSV_SAMPLE_SIZE = 8192
_DEFAULT_CSV_DELIMITER = ","
_ENCODING_CHUNK_SIZE = 64 * 1024

_ENCODING_BOM_SAMPLE_SIZE = max(
    len(codecs.BOM_UTF8),
    len(codecs.BOM_UTF16_LE),
    len(codecs.BOM_UTF16_BE),
    len(codecs.BOM_UTF32_LE),
    len(codecs.BOM_UTF32_BE),
)


class CsvLoader(BaseTableLoader):
    """Load CSV files into VeriSight."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def load(
        self, path: str | Path, *, options: CsvReadOptions | None = None
    ) -> LoadedTable:
        """Validate and load a CSV file."""

        metadata = validate_file(
            path,
            max_size_mb=self._settings.max_upload_size_mb,
        )

        if metadata.file_extension != ".csv":
            raise DataLoadError(
                f"CsvLoader cannot load file type '{metadata.file_extension}'."
            )

        if options is not None and not isinstance(options, CsvReadOptions):
            raise DataLoadError("CSV options must be a CsvReadOptions object.")
        choices = options if options is not None else CsvReadOptions()

        try:
            if choices.encoding is None:
                encoding = self._detect_encoding(metadata.path)
            else:
                encoding = codecs.lookup(choices.encoding).name
                self._validate_decoded_content(metadata.path, encoding=encoding)

            delimiter = (
                choices.delimiter
                if choices.delimiter is not None
                else self._detect_delimiter(metadata.path, encoding=encoding)
            )

            # Read the source header as values before pandas can rename it.
            header = pd.read_csv(
                metadata.path,
                sep=delimiter,
                encoding=encoding,
                header=None,
                nrows=1,
                dtype=str,
                keep_default_na=False,
                na_filter=False,
            )
            source_columns = header.iloc[0].tolist()
            if any(not str(column).strip() for column in source_columns):
                raise DataLoadError("CSV column headers must not be blank.")
            if not pd.Index(source_columns).is_unique:
                raise DataLoadError("CSV contains duplicate source column headers.")

            data = pd.read_csv(
                metadata.path,
                sep=delimiter,
                encoding=encoding,
                dtype=str,
                keep_default_na=False,
                na_values=[""],
            )

            if not isinstance(data.index, pd.RangeIndex):
                raise DataLoadError(
                    "CSV rows contain more fields than the header. "
                    "Implicit row indexes are not supported."
                )

            data = self._infer_safe_column_types(data)

        except DataLoadError:
            raise
        except Exception as exc:
            raise DataLoadError(f"Could not load CSV file: {metadata.path}") from exc

        return LoadedTable(
            name=metadata.path.stem,
            data=data,
            source=replace(metadata, csv_encoding=encoding, csv_delimiter=delimiter),
        )

    @staticmethod
    def _detect_encoding(path: Path) -> str:
        """Detect Unicode BOMs and validate encoding in bounded chunks."""

        with path.open("rb") as file:
            prefix = file.read(_ENCODING_BOM_SAMPLE_SIZE)

            if prefix.startswith(codecs.BOM_UTF8):
                CsvLoader._validate_decoded_content(path, encoding="utf-8-sig")
                return "utf-8-sig"

            if prefix.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
                raise DataLoadError(
                    "CSV file uses UTF-32 encoding, which is not supported."
                )

            if prefix.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
                CsvLoader._validate_decoded_content(path, encoding="utf-16")
                return "utf-16"

            file.seek(0)

            utf8_decoder = codecs.getincrementaldecoder("utf-8")()
            utf8_valid = True

            while chunk := file.read(_ENCODING_CHUNK_SIZE):
                if b"\x00" in chunk:
                    raise DataLoadError(
                        "CSV file contains NUL bytes and may use an "
                        "unsupported Unicode encoding without a BOM."
                    )

                if utf8_valid:
                    try:
                        utf8_decoder.decode(chunk, final=False)
                    except UnicodeDecodeError:
                        utf8_valid = False

            if utf8_valid:
                try:
                    utf8_decoder.decode(b"", final=True)
                except UnicodeDecodeError:
                    utf8_valid = False

            if utf8_valid:
                return "utf-8"

            raise DataLoadError(
                "CSV encoding could not be established as UTF-8 or BOM-marked UTF-16. "
                "Supply an explicit CsvReadOptions encoding; "
                "no legacy fallback was used."
            )

    @staticmethod
    def _validate_decoded_content(path: Path, *, encoding: str) -> None:
        """Reject NUL characters before pandas can silently truncate fields."""
        with path.open("r", encoding=encoding, newline="") as file:
            while chunk := file.read(_ENCODING_CHUNK_SIZE):
                if "\x00" in chunk:
                    raise DataLoadError("CSV file contains NUL characters.")

    @staticmethod
    def _detect_delimiter(
        path: Path,
        *,
        encoding: str,
    ) -> str:
        """Detect a supported delimiter or reject an inconclusive sample."""

        # Normalize line endings only for inference. Pandas still reads the
        # original file, preserving newlines embedded in quoted field values.
        with path.open(
            "r",
            encoding=encoding,
            newline=None,
        ) as file:
            sample = file.read(_CSV_SAMPLE_SIZE + 1)

        if len(sample) > _CSV_SAMPLE_SIZE:
            # Exclude a partial physical line, then let the CSV parser identify
            # complete logical records, including quoted multiline fields.
            sample = sample[:_CSV_SAMPLE_SIZE]
            sample = sample[: sample.rfind("\n") + 1]
            candidates: list[str] = []
            single_column = False
            for delimiter in _CSV_DELIMITERS:
                widths: list[int] = []
                try:
                    for row in csv.reader(
                        StringIO(sample), delimiter=delimiter, strict=True
                    ):
                        if row:
                            widths.append(len(row))
                except csv.Error:
                    # The final quoted record may extend beyond the sample.
                    # Only records returned before it are evidence for inference.
                    pass
                if len(widths) >= 2 and min(widths) == max(widths):
                    if widths[0] > 1:
                        candidates.append(delimiter)
                    else:
                        single_column = True
            if len(candidates) == 1:
                return candidates[0]
            if single_column and not any(
                character in sample for character in _CSV_DELIMITERS
            ):
                return _DEFAULT_CSV_DELIMITER
            raise DataLoadError(
                "CSV delimiter detection was inconclusive. "
                "Supply an explicit CsvReadOptions delimiter."
            )

        try:
            dialect = csv.Sniffer().sniff(
                sample,
                delimiters=_CSV_DELIMITERS,
            )
        except csv.Error as exc:
            # A complete file with no supported separator is a single-column CSV.
            # Never reinterpret an inconclusive multi-column sample as comma CSV.
            if not any(character in sample for character in _CSV_DELIMITERS):
                return _DEFAULT_CSV_DELIMITER
            raise DataLoadError(
                "CSV delimiter detection was inconclusive. "
                "Supply an explicit CsvReadOptions delimiter."
            ) from exc

        return dialect.delimiter

    @classmethod
    def _infer_safe_column_types(
        cls,
        data: pd.DataFrame,
    ) -> pd.DataFrame:
        """Infer safe physical types while preserving lexical identifiers."""

        for column in data.columns:
            series = data[column]
            non_missing = series.dropna()

            if non_missing.empty:
                continue

            values = non_missing.astype(str)
            normalized = values.str.lower()

            if normalized.isin(_BOOLEAN_LITERALS).all():
                data[column] = cls._convert_boolean_series(series)
                continue

            numeric_mask = values.str.fullmatch(_NUMERIC_PATTERN)

            if not bool(numeric_mask.all()):
                continue

            integer_mask = values.str.fullmatch(_INTEGER_PATTERN)

            if bool(integer_mask.all()):
                unsigned = values.str.removeprefix("+").str.removeprefix("-")

                has_leading_zero = (
                    unsigned.str.len().gt(1) & unsigned.str.startswith("0")
                ).any()

                if bool(has_leading_zero):
                    continue

                limit = str(_MAX_SAFE_FLOAT_INTEGER)
                digit_counts = unsigned.str.len()
                exceeds_safe_range = digit_counts.gt(len(limit)) | (
                    digit_counts.eq(len(limit)) & unsigned.gt(limit)
                )

                if bool(exceeds_safe_range.any()):
                    continue

                numeric = pd.to_numeric(series, errors="raise")

                if series.isna().any():
                    data[column] = numeric.astype("Int64")
                else:
                    data[column] = numeric

                continue

            numeric = pd.to_numeric(
                series,
                errors="raise",
            )
            if any(
                Decimal(original) != Decimal(str(converted))
                for original, converted in zip(values, numeric.dropna(), strict=True)
            ):
                data[column] = series.map(
                    lambda value: None if pd.isna(value) else Decimal(value)
                )
            else:
                data[column] = numeric

        return data

    @staticmethod
    def _convert_boolean_series(series: pd.Series) -> pd.Series:
        """Convert unambiguous boolean literals while preserving missing values."""

        normalized = series.str.lower()

        converted = normalized.map(
            {
                "true": True,
                "false": False,
            }
        )

        if series.isna().any():
            return converted.astype("boolean")

        return converted.astype(bool)
