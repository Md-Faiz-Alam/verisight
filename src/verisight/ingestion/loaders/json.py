"""JSON loader for the VeriSight ingestion subsystem."""

import json
import math
from decimal import Decimal, DecimalException
from pathlib import Path
from typing import Any

import pandas as pd

from verisight.config import Settings
from verisight.ingestion.exceptions import DataLoadError
from verisight.ingestion.loaders.base import BaseTableLoader
from verisight.ingestion.models import LoadedTable
from verisight.ingestion.validation import validate_file

_MIN_INT64 = -(2**63)
_MAX_INT64 = 2**63 - 1
_MAX_UINT64 = 2**64 - 1
_MAX_SAFE_FLOAT_INTEGER = 2**53 - 1


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject duplicate keys before a JSON object can discard source fields."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key.")
        result[key] = value
    return result


def _parse_decimal(token: str) -> float | Decimal:
    """Keep decimals exact when normal float conversion changes their value.

    Ordinary floats retain existing inference only when their decimal string
    round trip equals the source number, matching the CSV precision policy.
    This does not make floating-point SQL arithmetic exact.
    """
    exact = Decimal(token)
    approximate = float(exact)
    if math.isfinite(approximate) and Decimal(str(approximate)) == exact:
        return approximate
    return exact


def _reject_constant(token: str) -> None:
    """Reject nonstandard JSON NaN and infinity literals."""
    raise ValueError("Nonstandard JSON numeric constant.")


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
                payload: Any = json.load(
                    file,
                    parse_float=_parse_decimal,
                    parse_constant=_reject_constant,
                    object_pairs_hook=_unique_object,
                )
        except (
            OSError,
            UnicodeError,
            ValueError,
            DecimalException,
            RecursionError,
        ) as exc:
            raise DataLoadError(f"Could not load JSON file: {metadata.path}") from exc

        try:
            data = self._to_dataframe(
                payload,
                path=metadata.path,
            )
        except DataLoadError:
            raise
        except (ValueError, TypeError, OverflowError) as exc:
            raise DataLoadError(
                f"Could not convert JSON data into a table: {metadata.path}"
            ) from exc

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
            return JsonLoader._records_to_dataframe([payload])

        if isinstance(payload, list):
            if not payload:
                return pd.DataFrame()

            if not all(isinstance(item, dict) for item in payload):
                raise DataLoadError(f"JSON array must contain objects: {path}")

            return JsonLoader._records_to_dataframe(payload)

        raise DataLoadError(f"JSON root must be an object or array of objects: {path}")

    @staticmethod
    def _records_to_dataframe(records: list[dict[str, Any]]) -> pd.DataFrame:
        """Infer columns without first coercing source integers to floats."""

        columns = dict.fromkeys(key for record in records for key in record)

        return pd.DataFrame(
            {
                column: JsonLoader._to_series(
                    [record.get(column) for record in records]
                )
                for column in columns
            },
            index=range(len(records)),
        )

    @staticmethod
    def _to_series(values: list[Any]) -> pd.Series:
        """Preserve booleans and exact numbers, including nullable columns."""

        non_null = [value for value in values if value is not None]

        if non_null and all(type(value) is bool for value in non_null):
            boolean_dtype = "boolean" if len(non_null) != len(values) else "bool"
            return pd.Series(values, dtype=boolean_dtype)

        if non_null and all(type(value) is int for value in non_null):
            minimum = min(non_null)
            maximum = max(non_null)
            has_null = len(non_null) != len(values)

            if minimum >= _MIN_INT64 and maximum <= _MAX_INT64:
                dtype = "Int64" if has_null else "int64"
                return pd.Series(values, dtype=dtype)

            if minimum >= 0 and maximum <= _MAX_UINT64:
                dtype = "UInt64" if has_null else "uint64"
                return pd.Series(values, dtype=dtype)

            return pd.Series(values, dtype=object)

        if any(
            type(value) is Decimal
            or (type(value) is int and abs(value) > _MAX_SAFE_FLOAT_INTEGER)
            for value in non_null
        ):
            return pd.Series(values, dtype=object)

        return pd.Series(values)
