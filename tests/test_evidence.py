import pytest

from verisight.evidence import EvidenceInput, freeze_evidence


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
