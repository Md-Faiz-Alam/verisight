"""CSV loader for the VeriSight ingestion subsystem."""

import codecs
import csv
from pathlib import Path

import pandas as pd

from verisight.config import Settings
from verisight.ingestion.exceptions import DataLoadError
from verisight.ingestion.loaders.base import BaseTableLoader
from verisight.ingestion.models import LoadedTable
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
            encoding = self._detect_encoding(metadata.path)

            delimiter = self._detect_delimiter(
                metadata.path,
                encoding=encoding,
            )

            data = pd.read_csv(
                metadata.path,
                sep=delimiter,
                encoding=encoding,
                dtype=str,
                keep_default_na=False,
                na_values=[""],
            )

            data = self._infer_safe_column_types(data)

        except DataLoadError:
            raise
        except Exception as exc:
            raise DataLoadError(f"Could not load CSV file: {metadata.path}") from exc

        return LoadedTable(
            name=metadata.path.stem,
            data=data,
            source=metadata,
        )

    @staticmethod
    def _detect_encoding(path: Path) -> str:
        """Detect Unicode BOMs and validate encoding in bounded chunks."""

        with path.open("rb") as file:
            prefix = file.read(_ENCODING_BOM_SAMPLE_SIZE)

            if prefix.startswith(codecs.BOM_UTF8):
                return "utf-8-sig"

            if prefix.startswith((codecs.BOM_UTF32_LE, codecs.BOM_UTF32_BE)):
                raise DataLoadError(
                    "CSV file uses UTF-32 encoding, which is not supported."
                )

            if prefix.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
                return "utf-16"

            file.seek(0)

            utf8_decoder = codecs.getincrementaldecoder("utf-8")()
            utf8_valid = True
            cp1252_decoder = codecs.getincrementaldecoder("cp1252")()
            cp1252_valid = True

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

                if cp1252_valid:
                    try:
                        cp1252_decoder.decode(chunk, final=False)
                    except UnicodeDecodeError:
                        cp1252_valid = False

            if utf8_valid:
                try:
                    utf8_decoder.decode(b"", final=True)
                except UnicodeDecodeError:
                    utf8_valid = False

            if utf8_valid:
                return "utf-8"

            if cp1252_valid:
                return "cp1252"

            return "latin-1"

    @staticmethod
    def _detect_delimiter(
        path: Path,
        *,
        encoding: str,
    ) -> str:
        """Detect a supported delimiter, defaulting to comma when ambiguous."""

        with path.open(
            "r",
            encoding=encoding,
            newline="",
        ) as file:
            sample = file.read(_CSV_SAMPLE_SIZE)

        try:
            dialect = csv.Sniffer().sniff(
                sample,
                delimiters=_CSV_DELIMITERS,
            )
        except csv.Error:
            return _DEFAULT_CSV_DELIMITER

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

                integers = pd.to_numeric(values, errors="raise")

                if bool(integers.abs().gt(_MAX_SAFE_FLOAT_INTEGER).any()):
                    continue

                numeric = pd.to_numeric(series, errors="raise")

                if series.isna().any():
                    data[column] = numeric.astype("Int64")
                else:
                    data[column] = numeric

                continue

            data[column] = pd.to_numeric(
                series,
                errors="raise",
            )

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
