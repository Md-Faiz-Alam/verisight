"""CSV loader for the VeriSight ingestion subsystem."""

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

        except Exception as exc:
            raise DataLoadError(f"Could not load CSV file: {metadata.path}") from exc

        return LoadedTable(
            name=metadata.path.stem,
            data=data,
            source=metadata,
        )

    @staticmethod
    def _detect_encoding(path: Path) -> str:
        """Return UTF-8 when valid, otherwise fall back to Windows-1252."""

        try:
            with path.open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as file:
                file.read()
        except UnicodeDecodeError:
            return "cp1252"

        return "utf-8-sig"

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

        converted = data.copy()

        for column in converted.columns:
            series = converted[column]
            non_missing = series.dropna()

            if non_missing.empty:
                continue

            values = non_missing.astype(str)
            normalized = values.str.lower()

            if normalized.isin(_BOOLEAN_LITERALS).all():
                converted[column] = cls._convert_boolean_series(series)
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
                    converted[column] = numeric.astype("Int64")
                else:
                    converted[column] = numeric

                continue

            converted[column] = pd.to_numeric(
                series,
                errors="raise",
            )

        return converted

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
