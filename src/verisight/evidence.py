"""Shared immutable evidence models for VeriSight."""

from collections.abc import Mapping, Sequence
from types import MappingProxyType
from typing import TypeAlias

EvidenceScalar: TypeAlias = str | int | float | bool | None

EvidenceValue: TypeAlias = (
    EvidenceScalar | tuple["EvidenceValue", ...] | Mapping[str, "EvidenceValue"]
)

Evidence: TypeAlias = Mapping[str, EvidenceValue]

EvidenceInputValue: TypeAlias = (
    EvidenceScalar | Sequence["EvidenceInputValue"] | Mapping[str, "EvidenceInputValue"]
)

EvidenceInput: TypeAlias = Mapping[str, EvidenceInputValue]


def freeze_evidence(evidence: EvidenceInput) -> Evidence:
    """Create an immutable recursive snapshot of evidence."""

    return MappingProxyType(
        {key: _freeze_evidence_value(value) for key, value in evidence.items()}
    )


def _freeze_evidence_value(value: EvidenceInputValue) -> EvidenceValue:
    """Recursively freeze one evidence value."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, Mapping):
        return MappingProxyType(
            {
                key: _freeze_evidence_value(nested_value)
                for key, nested_value in value.items()
            }
        )

    if isinstance(value, Sequence):
        return tuple(_freeze_evidence_value(item) for item in value)

    raise TypeError(
        "Evidence values must contain only strings, numbers, booleans, "
        "None, mappings, or sequences."
    )
