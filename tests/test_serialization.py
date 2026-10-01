import json
from dataclasses import dataclass
from enum import Enum, StrEnum
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pandas as pd
import pytest

from verisight.analysis.result import AnalysisResultBuilder
from verisight.analysis.service import DatasetAnalyzer
from verisight.ingestion.models import LoadedDataset, LoadedTable, SourceMetadata
from verisight.serialization import to_jsonable


class ExampleType(StrEnum):
    SAMPLE = "sample"


class ExampleNumber(Enum):
    ONE = 1


@dataclass(frozen=True, slots=True)
class ExampleChild:
    count: int


@dataclass(frozen=True, slots=True)
class ExampleModel:
    name: str
    kind: ExampleType
    path: Path
    children: tuple[ExampleChild, ...]
    evidence: object


def test_to_jsonable_serializes_nested_domain_values() -> None:
    value = ExampleModel(
        name="customers",
        kind=ExampleType.SAMPLE,
        path=Path("data/customers.csv"),
        children=(
            ExampleChild(count=3),
            ExampleChild(count=5),
        ),
        evidence=MappingProxyType(
            {
                "count": np.int64(8),
                "columns": ("id", "name"),
            }
        ),
    )

    serialized = to_jsonable(value)

    assert serialized == {
        "name": "customers",
        "kind": "sample",
        "path": str(Path("data/customers.csv")),
        "children": [
            {"count": 3},
            {"count": 5},
        ],
        "evidence": {
            "count": 8,
            "columns": ["id", "name"],
        },
    }


def test_to_jsonable_serializes_enum_values() -> None:
    assert to_jsonable(ExampleNumber.ONE) == 1


def test_to_jsonable_output_can_be_serialized_by_json() -> None:
    value = ExampleModel(
        name="customers",
        kind=ExampleType.SAMPLE,
        path=Path("data/customers.csv"),
        children=(ExampleChild(count=3),),
        evidence=MappingProxyType({"valid": True}),
    )

    serialized = json.dumps(to_jsonable(value))

    assert json.loads(serialized) == {
        "name": "customers",
        "kind": "sample",
        "path": str(Path("data/customers.csv")),
        "children": [{"count": 3}],
        "evidence": {"valid": True},
    }


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
    ],
)
def test_to_jsonable_rejects_non_finite_floats(value: float) -> None:
    with pytest.raises(
        ValueError,
        match="JSON floating-point values must be finite.",
    ):
        to_jsonable(value)


def test_to_jsonable_rejects_non_string_mapping_keys() -> None:
    with pytest.raises(
        TypeError,
        match="JSON mapping keys must be strings.",
    ):
        to_jsonable({1: "invalid"})


@pytest.mark.parametrize(
    "value",
    [
        b"binary",
        bytearray(b"binary"),
    ],
)
def test_to_jsonable_rejects_binary_values(
    value: bytes | bytearray,
) -> None:
    with pytest.raises(
        TypeError,
        match="Binary values cannot be serialized to JSON.",
    ):
        to_jsonable(value)


def test_to_jsonable_rejects_unsupported_objects() -> None:
    with pytest.raises(
        TypeError,
        match="Unsupported JSON serialization type: object.",
    ):
        to_jsonable(object())


def test_to_jsonable_serializes_complete_dataset_analysis_result() -> None:
    source = SourceMetadata(
        path=Path("orders.csv"),
        file_name="orders.csv",
        file_extension=".csv",
        file_size_bytes=1,
    )

    table = LoadedTable(
        name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2, 2],
                "amount": [10.0, 20.0, 20.0],
            }
        ),
        source=source,
    )

    analysis = DatasetAnalyzer().analyze(
        LoadedDataset(
            tables=[table],
        )
    )

    result = AnalysisResultBuilder().build(analysis)

    serialized = to_jsonable(result)

    assert isinstance(serialized, dict)

    encoded = json.dumps(serialized)
    decoded = json.loads(encoded)

    assert decoded == serialized

    analysis_data = decoded["analysis"]
    summary_data = decoded["summary"]
    insights_data = decoded["insights"]

    assert isinstance(analysis_data["schema"], dict)
    assert isinstance(analysis_data["profile"], dict)
    assert isinstance(analysis_data["issues"], list)

    issues = analysis_data["issues"]

    assert len(issues) >= 1

    duplicate_issue = next(
        issue for issue in issues if issue["issue_type"] == "duplicate_rows"
    )

    assert duplicate_issue["table_name"] == "orders"
    assert duplicate_issue["relation_name"] == "orders"

    assert summary_data["table_count"] == 1
    assert summary_data["total_row_count"] == 3
    assert summary_data["total_column_count"] == 2

    assert isinstance(insights_data, list)
