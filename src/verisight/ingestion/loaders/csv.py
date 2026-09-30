"""CSV loader for the VeriSight ingestion subsystem."""

from pathlib import Path

import pandas as pd

from verisight.config import Settings
from verisight.ingestion.exceptions import DataLoadError
from verisight.ingestion.loaders.base import BaseTableLoader
from verisight.ingestion.models import LoadedTable
from verisight.ingestion.validation import validate_file

_MAX_SAFE_FLOAT_INTEGER = 2**53 - 1
_BOOLEAN_LITERALS = frozenset({"true", "false"})


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
            data = pd.read_csv(
                metadata.path,
                dtype=str,
            )
            data = self._infer_safe_column_types(data)
        except Exception as exc:
            raise DataLoadError(f"Could not load CSV file: {metadata.path}") from exc

        return LoadedTable(
            name=metadata.path.stem,
            data=data,
            source=metadata,
        )

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

            if cls._is_boolean_column(values):
                converted[column] = cls._convert_boolean_series(series)
                continue

            if not values.map(cls._is_numeric_literal).all():
                continue

            integer_values = values.map(cls._is_integer_literal)

            if integer_values.all():
                if values.map(cls._has_significant_leading_zero).any():
                    continue

                if values.map(cls._exceeds_safe_float_integer).any():
                    continue

            converted[column] = pd.to_numeric(
                series,
                errors="raise",
            )

        return converted

    @staticmethod
    def _is_boolean_column(values: pd.Series) -> bool:
        """Return whether all values are unambiguous boolean literals."""

        normalized = values.str.lower()

        return bool(normalized.isin(_BOOLEAN_LITERALS).all())

    @staticmethod
    def _convert_boolean_series(series: pd.Series) -> pd.Series:
        """Convert unambiguous boolean literals while preserving missing values."""

        normalized = series.str.lower()

        if series.isna().any():
            return normalized.map(
                {
                    "true": True,
                    "false": False,
                }
            ).astype("boolean")

        return normalized.map(
            {
                "true": True,
                "false": False,
            }
        ).astype(bool)

    @staticmethod
    def _is_numeric_literal(value: str) -> bool:
        """Return whether a value is a finite numeric literal."""

        try:
            numeric_value = float(value)
        except ValueError:
            return False

        return pd.notna(numeric_value) and numeric_value not in {
            float("inf"),
            float("-inf"),
        }

    @staticmethod
    def _is_integer_literal(value: str) -> bool:
        """Return whether a value is a base-10 integer literal."""

        unsigned = value

        if value.startswith(("+", "-")):
            unsigned = value[1:]

        return bool(unsigned) and unsigned.isdigit()

    @staticmethod
    def _has_significant_leading_zero(value: str) -> bool:
        """Return whether an integer literal contains significant leading zeros."""

        unsigned = value

        if value.startswith(("+", "-")):
            unsigned = value[1:]

        return len(unsigned) > 1 and unsigned.startswith("0")

    @staticmethod
    def _exceeds_safe_float_integer(value: str) -> bool:
        """Return whether an integer exceeds exact IEEE-754 float precision."""

        return abs(int(value)) > _MAX_SAFE_FLOAT_INTEGER
