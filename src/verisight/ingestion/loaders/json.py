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
from verisight.ingestion.models import LoadedTable, ValueNote
from verisight.ingestion.temporal import parse_iso_datetimes
from verisight.ingestion.validation import validate_file

_JSON_EXTENSIONS = frozenset({".json", ".jsonl", ".ndjson"})
_MAX_JSON_DEPTH = 4
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

        if metadata.file_extension not in _JSON_EXTENSIONS:
            raise DataLoadError(
                f"JsonLoader cannot load file type '{metadata.file_extension}'."
            )

        changes: list[str] = []
        try:
            text = metadata.path.read_text(encoding="utf-8-sig")
            payload = self._parse(text, metadata.file_extension, changes)
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
                self._unwrapped(payload, changes),
                path=metadata.path,
                changes=changes,
            )
        except DataLoadError:
            raise
        except (ValueError, TypeError, OverflowError) as exc:
            raise DataLoadError(
                f"Could not convert JSON data into a table: {metadata.path}"
            ) from exc

        table = LoadedTable(
            name=metadata.path.stem,
            data=data,
            source=metadata,
        )
        if changes and len(data.columns):
            table.value_notes = (
                ValueNote(
                    column=str(data.columns[0]),
                    rule="reshaped_json",
                    affected_count=len(data),
                    examples=(),
                    detail="; ".join(changes),
                ),
            )
        return table

    @staticmethod
    def _decode(text: str) -> Any:
        return json.loads(
            text,
            parse_float=_parse_decimal,
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )

    @classmethod
    def _parse(cls, text: str, extension: str, changes: list[str]) -> Any:
        """Read one JSON document, or one object per line for JSON Lines."""
        if extension != ".json":
            changes.append("read one JSON object per line")
            return [cls._decode(line) for line in text.splitlines() if line.strip()]
        try:
            return cls._decode(text)
        except json.JSONDecodeError as error:
            if not error.msg.startswith("Extra data"):
                raise
        changes.append("read one JSON object per line")
        return [cls._decode(line) for line in text.splitlines() if line.strip()]

    @staticmethod
    def _unwrapped(payload: Any, changes: list[str]) -> Any:
        """Use the rows inside a wrapper such as ``{"data": [...], "meta": {}}``."""
        if isinstance(payload, dict):
            rows = [
                (key, value)
                for key, value in payload.items()
                if isinstance(value, list)
                and value
                and all(isinstance(item, dict) for item in value)
            ]
            if len(rows) == 1:
                changes.append(f"used the rows inside '{rows[0][0]}'")
                return rows[0][1]
        return payload

    @staticmethod
    def _to_dataframe(
        payload: Any,
        *,
        path: Path,
        changes: list[str],
    ) -> pd.DataFrame:
        """Convert a supported JSON structure into a DataFrame."""

        if isinstance(payload, dict):
            if JsonLoader._is_columnar(payload):
                return JsonLoader._columns_to_dataframe(payload)
            return JsonLoader._records_to_dataframe(
                JsonLoader._flattened([payload], changes)
            )

        if isinstance(payload, list):
            if not payload:
                return pd.DataFrame()

            if not all(isinstance(item, dict) for item in payload):
                raise DataLoadError(f"JSON array must contain objects: {path}")

            return JsonLoader._records_to_dataframe(
                JsonLoader._flattened(payload, changes)
            )

        raise DataLoadError(
            "JSON root must be an object, an array of objects, or an object of "
            f"column arrays: {path}"
        )

    @staticmethod
    def _flattened(
        records: list[dict[str, Any]], changes: list[str]
    ) -> list[dict[str, Any]]:
        """Turn nested objects into columns such as ``user.age``.

        A field is expanded only when every present value of it is an object,
        so one column never mixes shapes. Lists stay in one cell, and records
        are left alone if a new name would collide with an existing field.
        """
        flat = records
        for _ in range(_MAX_JSON_DEPTH):
            names = dict.fromkeys(key for record in flat for key in record)
            objects = [
                key
                for key in names
                if any(record.get(key) is not None for record in flat)
                and all(
                    isinstance(record[key], dict)
                    for record in flat
                    if record.get(key) is not None
                )
            ]
            if not objects:
                break
            inner = {
                f"{k}.{i}" for r in flat for k in objects for i in (r.get(k) or {})
            }
            if inner & names.keys() or any(
                not n.split(".", 1)[1].strip() or "\x00" in n for n in inner
            ):
                return records
            flat = [
                {
                    new: value
                    for key, item in record.items()
                    for new, value in (
                        [(f"{key}.{i}", v) for i, v in (item or {}).items()]
                        if key in objects
                        else [(key, item)]
                    )
                }
                for record in flat
            ]
        if flat is not records:
            changes.append("nested fields became columns such as a.b")
        return flat

    @staticmethod
    def _is_columnar(payload: dict[str, Any]) -> bool:
        """Detect column-oriented JSON such as ``{"a": [1, 2], "b": [3, 4]}``.

        Every value must be an array of scalar values. A single record whose
        fields hold nested objects or arrays keeps the one-row interpretation.
        """
        return bool(payload) and all(
            isinstance(values, list)
            and not any(isinstance(value, dict | list) for value in values)
            for values in payload.values()
        )

    @staticmethod
    def _columns_to_dataframe(payload: dict[str, list[Any]]) -> pd.DataFrame:
        """Convert equal-length column arrays into rows, keeping source order."""
        lengths = {len(values) for values in payload.values()}
        if len(lengths) != 1:
            raise DataLoadError(
                "JSON column arrays must all have the same number of values."
            )
        row_count = lengths.pop()
        records = [
            {column: values[index] for column, values in payload.items()}
            for index in range(row_count)
        ]
        return JsonLoader._records_to_dataframe(records)

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

        if non_null and all(type(value) is str for value in non_null):
            dates = parse_iso_datetimes(pd.Series(values, dtype=object))
            if dates is not None:
                return dates

        return pd.Series(values)
