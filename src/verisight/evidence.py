"""Shared immutable evidence models for VeriSight."""

import math
from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import TypeAlias

import numpy as np

EvidenceScalar: TypeAlias = str | int | float | bool | None
EvidenceInputScalar: TypeAlias = EvidenceScalar | np.generic

EvidenceValue: TypeAlias = (
    EvidenceScalar | tuple["EvidenceValue", ...] | Mapping[str, "EvidenceValue"]
)

Evidence: TypeAlias = Mapping[str, EvidenceValue]

EvidenceInputValue: TypeAlias = (
    EvidenceInputScalar
    | Sequence["EvidenceInputValue"]
    | Mapping[str, "EvidenceInputValue"]
)

EvidenceInput: TypeAlias = Mapping[str, EvidenceInputValue]

JsonEvidenceValue: TypeAlias = (
    EvidenceScalar | list["JsonEvidenceValue"] | dict[str, "JsonEvidenceValue"]
)

JsonEvidence: TypeAlias = dict[str, JsonEvidenceValue]


def freeze_evidence(evidence: EvidenceInput) -> Evidence:
    """Create a validated immutable recursive snapshot of evidence."""

    return MappingProxyType(_freeze_evidence_mapping(evidence))


def evidence_to_jsonable(evidence: Evidence) -> JsonEvidence:
    """Convert immutable evidence into a JSON-safe mutable representation."""

    return {key: _evidence_value_to_jsonable(value) for key, value in evidence.items()}


def _freeze_evidence_mapping(
    mapping: Mapping[str, EvidenceInputValue],
) -> dict[str, EvidenceValue]:
    """Validate and recursively freeze one evidence mapping."""

    frozen: dict[str, EvidenceValue] = {}

    for key, value in mapping.items():
        if not isinstance(key, str):
            raise TypeError("Evidence mapping keys must be strings.")

        frozen[key] = _freeze_evidence_value(value)

    return frozen


def _freeze_evidence_value(value: EvidenceInputValue) -> EvidenceValue:
    """Normalize and recursively freeze one evidence value."""

    if isinstance(value, np.generic):
        normalized = value.item()
        return _freeze_evidence_value(normalized)

    if value is None or isinstance(value, (str, bool, int)):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Evidence floating-point values must be finite.")

        return value

    if isinstance(value, Mapping):
        return MappingProxyType(_freeze_evidence_mapping(value))

    if isinstance(value, (bytes, bytearray)):
        raise TypeError("Evidence values cannot contain bytes.")

    if isinstance(value, Sequence):
        return tuple(_freeze_evidence_value(item) for item in value)

    raise TypeError(
        "Evidence values must contain only strings, numbers, booleans, "
        "None, mappings, or sequences."
    )


def _evidence_value_to_jsonable(
    value: EvidenceValue,
) -> JsonEvidenceValue:
    """Convert one frozen evidence value into a JSON-safe value."""

    if isinstance(value, Mapping):
        return {
            key: _evidence_value_to_jsonable(nested_value)
            for key, nested_value in value.items()
        }

    if isinstance(value, tuple):
        return [_evidence_value_to_jsonable(item) for item in value]

    return value
