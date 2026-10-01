"""JSON-safe serialization for VeriSight domain objects."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from typing import TypeAlias

import numpy as np

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def to_jsonable(value: object) -> JsonValue:
    """Convert a supported VeriSight value into a JSON-safe representation."""

    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON floating-point values must be finite.")

        return value

    if isinstance(value, np.generic):
        return to_jsonable(value.item())

    if isinstance(value, Enum):
        return to_jsonable(value.value)

    if isinstance(value, Path):
        return str(value)

    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_jsonable(getattr(value, field.name))
            for field in fields(value)
        }

    if isinstance(value, Mapping):
        serialized: dict[str, JsonValue] = {}

        for key, nested_value in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON mapping keys must be strings.")

            serialized[key] = to_jsonable(nested_value)

        return serialized

    if isinstance(value, (bytes, bytearray)):
        raise TypeError("Binary values cannot be serialized to JSON.")

    if isinstance(value, Sequence):
        return [to_jsonable(item) for item in value]

    raise TypeError(f"Unsupported JSON serialization type: {type(value).__name__}.")
