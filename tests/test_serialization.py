import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum, StrEnum
from pathlib import Path
from types import MappingProxyType

import numpy as np
import pandas as pd
import pytest

from verisight.analysis.result import AnalysisResultBuilder, DatasetAnalysisResult
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


def _build_result(data: pd.DataFrame) -> DatasetAnalysisResult:
    source = SourceMetadata(
        path=Path("orders.xlsx"),
        file_name="orders.xlsx",
        file_extension=".xlsx",
        file_size_bytes=1,
    )

    table = LoadedTable(
        name="orders",
        data=data,
        source=source,
    )

    analysis = DatasetAnalyzer().analyze(
        LoadedDataset(
            tables=[table],
        )
    )

    return AnalysisResultBuilder().build(analysis)


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

    serialized = to_jsonable(value)
    encoded = json.dumps(serialized, allow_nan=False)

    assert json.loads(encoded) == {
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
        np.float64("nan"),
        np.float64("inf"),
        np.float64("-inf"),
    ],
)
def test_to_jsonable_maps_non_finite_floats_to_none(value: object) -> None:
    assert to_jsonable(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            datetime(2026, 1, 2, 3, 4, 5),
            "2026-01-02T03:04:05",
        ),
        (
            datetime(
                2026,
                1,
                2,
                3,
                4,
                5,
                tzinfo=UTC,
            ),
            "2026-01-02T03:04:05+00:00",
        ),
        (
            date(2026, 1, 2),
            "2026-01-02",
        ),
        (
            pd.Timestamp("2026-01-02 03:04:05"),
            "2026-01-02T03:04:05",
        ),
        (
            pd.Timestamp("2026-01-02 03:04:05", tz="UTC"),
            "2026-01-02T03:04:05+00:00",
        ),
        (
            pd.Timedelta(days=2, hours=3, minutes=4),
            "P2DT3H4M0S",
        ),
    ],
)
def test_to_jsonable_serializes_temporal_values(
    value: object,
    expected: str,
) -> None:
    assert to_jsonable(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        pd.NA,
        pd.NaT,
    ],
)
def test_to_jsonable_maps_pandas_missing_values_to_none(
    value: object,
) -> None:
    assert to_jsonable(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            Decimal("12.3400"),
            "12.3400",
        ),
        (
            Decimal("0.00000000000000000001"),
            "1E-20",
        ),
        (
            Decimal("12345678901234567890.123456789"),
            "12345678901234567890.123456789",
        ),
    ],
)
def test_to_jsonable_serializes_decimal_exactly(
    value: Decimal,
    expected: str,
) -> None:
    assert to_jsonable(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
    ],
)
def test_to_jsonable_maps_non_finite_decimal_to_none(
    value: Decimal,
) -> None:
    assert to_jsonable(value) is None


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
    result = _build_result(
        pd.DataFrame(
            {
                "order_id": [1, 2, 2],
                "amount": [10.0, 20.0, 20.0],
            }
        )
    )

    serialized = to_jsonable(result)

    assert isinstance(serialized, dict)

    encoded = json.dumps(serialized, allow_nan=False)
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


def test_to_jsonable_serializes_datetime_analysis_result() -> None:
    result = _build_result(
        pd.DataFrame(
            {
                "order_id": [1, 2, 3],
                "ordered_at": pd.to_datetime(
                    [
                        "2026-01-01 10:00:00",
                        "2026-01-02 11:30:00",
                        "2026-01-04 14:00:00",
                    ]
                ),
            }
        )
    )

    serialized = to_jsonable(result)

    encoded = json.dumps(serialized, allow_nan=False)
    decoded = json.loads(encoded)

    assert decoded == serialized

    table_profile = decoded["analysis"]["profile"]["tables"][0]
    ordered_at = next(
        column for column in table_profile["columns"] if column["name"] == "ordered_at"
    )

    statistics = ordered_at["datetime_statistics"]

    assert statistics["earliest"] == "2026-01-01T10:00:00"
    assert statistics["latest"] == "2026-01-04T14:00:00"
    assert statistics["span"] == "P3DT4H0M0S"
    assert statistics["timezone"] is None


def test_to_jsonable_serializes_timezone_aware_datetime_analysis_result() -> None:
    result = _build_result(
        pd.DataFrame(
            {
                "event_id": [1, 2],
                "occurred_at": pd.Series(
                    [
                        pd.Timestamp("2026-01-01 10:00:00", tz="UTC"),
                        pd.Timestamp("2026-01-02 12:30:00", tz="UTC"),
                    ]
                ),
            }
        )
    )

    serialized = to_jsonable(result)

    encoded = json.dumps(serialized, allow_nan=False)
    decoded = json.loads(encoded)

    assert decoded == serialized

    table_profile = decoded["analysis"]["profile"]["tables"][0]
    occurred_at = next(
        column for column in table_profile["columns"] if column["name"] == "occurred_at"
    )

    statistics = occurred_at["datetime_statistics"]

    assert statistics["earliest"] == "2026-01-01T10:00:00+00:00"
    assert statistics["latest"] == "2026-01-02T12:30:00+00:00"
    assert statistics["timezone"] == "UTC"


def test_to_jsonable_serializes_analysis_result_with_infinity() -> None:
    result = _build_result(
        pd.DataFrame(
            {
                "measurement": [
                    1.0,
                    float("inf"),
                    float("-inf"),
                ],
            }
        )
    )

    serialized = to_jsonable(result)

    encoded = json.dumps(serialized, allow_nan=False)
    decoded = json.loads(encoded)

    assert decoded == serialized

    table_profile = decoded["analysis"]["profile"]["tables"][0]
    measurement = next(
        column for column in table_profile["columns"] if column["name"] == "measurement"
    )

    statistics = measurement["numeric_statistics"]

    assert statistics["minimum"] == 1.0
    assert statistics["maximum"] == 1.0
    assert statistics["mean"] == 1.0
    assert statistics["median"] == 1.0
    assert statistics["standard_deviation"] is None
    assert statistics["non_finite_count"] == 2
    assert statistics["non_finite_ratio"] == pytest.approx(2 / 3)

    issues = decoded["analysis"]["issues"]

    non_finite_issue = next(
        issue for issue in issues if issue["issue_type"] == "non_finite_values"
    )

    assert non_finite_issue["severity"] == "warning"
    assert non_finite_issue["scope"] == "column"
    assert non_finite_issue["column_name"] == "measurement"
    assert non_finite_issue["affected_count"] == 2
    assert non_finite_issue["affected_ratio"] == pytest.approx(2 / 3)
    assert non_finite_issue["evidence"] == {
        "non_finite_count": 2,
        "non_missing_count": 3,
        "non_finite_ratio": pytest.approx(2 / 3),
    }


def test_to_jsonable_maps_nat_timestamp_to_none() -> None:
    value = pd.Timestamp("NaT")

    assert to_jsonable(value) is None


def test_to_jsonable_maps_nat_timedelta_to_none() -> None:
    value = pd.Timedelta("NaT")

    assert to_jsonable(value) is None
