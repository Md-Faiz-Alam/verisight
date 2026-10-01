import json
from unittest.mock import patch

import numpy as np
import pytest

from verisight.evidence import (
    EvidenceInput,
    evidence_to_jsonable,
    freeze_evidence,
)


def test_freezes_scalar_evidence_values() -> None:
    evidence = freeze_evidence(
        {
            "name": "orders",
            "count": 3,
            "ratio": 0.25,
            "valid": True,
            "optional": None,
        }
    )

    assert evidence == {
        "name": "orders",
        "count": 3,
        "ratio": 0.25,
        "valid": True,
        "optional": None,
    }


def test_top_level_evidence_is_immutable() -> None:
    evidence = freeze_evidence(
        {
            "count": 3,
        }
    )

    with pytest.raises(TypeError):
        evidence["count"] = 999  # type: ignore[index]


def test_nested_mapping_is_immutable() -> None:
    evidence = freeze_evidence(
        {
            "statistics": {
                "missing_count": 3,
                "row_count": 10,
            }
        }
    )

    statistics = evidence["statistics"]

    assert isinstance(statistics, dict) is False

    with pytest.raises(TypeError):
        statistics["missing_count"] = 999  # type: ignore[index]


def test_nested_sequence_becomes_tuple() -> None:
    evidence = freeze_evidence(
        {
            "columns": [
                "customer_id",
                "email",
                "country",
            ]
        }
    )

    assert evidence["columns"] == (
        "customer_id",
        "email",
        "country",
    )


def test_nested_evidence_is_recursively_frozen() -> None:
    evidence = freeze_evidence(
        {
            "details": {
                "columns": [
                    {
                        "name": "amount",
                        "missing_count": 3,
                    },
                    {
                        "name": "status",
                        "missing_count": 1,
                    },
                ]
            }
        }
    )

    assert evidence["details"] == {
        "columns": (
            {
                "name": "amount",
                "missing_count": 3,
            },
            {
                "name": "status",
                "missing_count": 1,
            },
        )
    }


def test_freezing_copies_nested_source_values() -> None:
    nested: dict[str, int] = {
        "missing_count": 3,
    }
    columns: list[str] = [
        "amount",
        "status",
    ]
    source: EvidenceInput = {
        "statistics": nested,
        "columns": columns,
    }

    evidence = freeze_evidence(source)

    nested["missing_count"] = 999
    columns.append("country")

    assert evidence["statistics"] == {
        "missing_count": 3,
    }
    assert evidence["columns"] == (
        "amount",
        "status",
    )


def test_freezing_normalizes_numpy_scalars() -> None:
    evidence = freeze_evidence(
        {
            "count": np.int64(3),
            "ratio": np.float64(0.25),
            "valid": np.bool_(True),
        }
    )

    assert evidence == {
        "count": 3,
        "ratio": 0.25,
        "valid": True,
    }
    assert type(evidence["count"]) is int
    assert type(evidence["ratio"]) is float
    assert type(evidence["valid"]) is bool


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        np.float64("nan"),
        np.float64("inf"),
        np.float64("-inf"),
    ],
)
def test_rejects_non_finite_floating_point_values(
    value: float | np.float64,
) -> None:
    with pytest.raises(
        ValueError,
        match="Evidence floating-point values must be finite.",
    ):
        freeze_evidence({"value": value})


@pytest.mark.parametrize(
    "value",
    [
        b"binary",
        bytearray(b"binary"),
    ],
)
def test_rejects_binary_evidence_values(
    value: bytes | bytearray,
) -> None:
    with pytest.raises(
        TypeError,
        match="Evidence values cannot contain bytes.",
    ):
        freeze_evidence({"value": value})


def test_rejects_non_string_mapping_keys() -> None:
    invalid_evidence = {
        "statistics": {
            1: "invalid",
        }
    }

    with pytest.raises(
        TypeError,
        match="Evidence mapping keys must be strings.",
    ):
        freeze_evidence(invalid_evidence)  # type: ignore[arg-type]


def test_rejects_unsupported_evidence_value_at_runtime() -> None:
    invalid_evidence = {
        "unsupported": object(),
    }

    with pytest.raises(
        TypeError,
        match=(
            "Evidence values must contain only strings, numbers, booleans, "
            "None, mappings, or sequences."
        ),
    ):
        freeze_evidence(invalid_evidence)  # type: ignore[arg-type]


def test_each_freeze_produces_independent_mapping() -> None:
    first = freeze_evidence({})
    second = freeze_evidence({})

    assert first == {}
    assert second == {}
    assert first is not second


def test_evidence_to_jsonable_converts_recursive_containers() -> None:
    evidence = freeze_evidence(
        {
            "statistics": {
                "missing_count": 3,
            },
            "columns": [
                "amount",
                "status",
            ],
        }
    )

    jsonable = evidence_to_jsonable(evidence)

    assert jsonable == {
        "statistics": {
            "missing_count": 3,
        },
        "columns": [
            "amount",
            "status",
        ],
    }
    assert isinstance(jsonable["statistics"], dict)
    assert isinstance(jsonable["columns"], list)


def test_jsonable_evidence_is_independent_from_frozen_evidence() -> None:
    evidence = freeze_evidence(
        {
            "columns": [
                "amount",
                "status",
            ],
        }
    )

    jsonable = evidence_to_jsonable(evidence)
    columns = jsonable["columns"]

    assert isinstance(columns, list)

    columns.append("country")

    assert evidence["columns"] == (
        "amount",
        "status",
    )


def test_jsonable_evidence_can_be_serialized_by_json() -> None:
    evidence = freeze_evidence(
        {
            "name": "orders",
            "count": np.int64(3),
            "statistics": {
                "missing_ratio": np.float64(0.25),
            },
            "columns": [
                "amount",
                "status",
            ],
        }
    )

    serialized = json.dumps(evidence_to_jsonable(evidence))

    assert json.loads(serialized) == {
        "name": "orders",
        "count": 3,
        "statistics": {
            "missing_ratio": 0.25,
        },
        "columns": [
            "amount",
            "status",
        ],
    }


def test_evidence_to_jsonable_rejects_non_mapping_serialization() -> None:
    evidence = freeze_evidence({"count": 1})

    with (
        patch(
            "verisight.evidence.to_jsonable",
            return_value=["unexpected"],
        ),
        pytest.raises(
            TypeError,
            match="Serialized evidence must be a mapping.",
        ),
    ):
        evidence_to_jsonable(evidence)
