"""Regression tests for JSON-safe analytical observation formatting."""

from datetime import date, datetime
from decimal import Decimal

import pytest

from verisight.execution.investigation_formatting import (
    InvestigationStateFormatter,
)
from verisight.execution.models import QueryResult, QueryScalar


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (
            date(2026, 1, 15),
            '["2026-01-15"]',
        ),
        (
            datetime(2026, 1, 15, 10, 30),
            '["2026-01-15T10:30:00"]',
        ),
        (
            Decimal("1234.567890"),
            '["1234.567890"]',
        ),
        (
            Decimal("0.00000001"),
            '["1E-8"]',
        ),
        (
            None,
            "[null]",
        ),
        (
            float("nan"),
            "[null]",
        ),
    ],
)
def test_formats_sql_scalar_as_json(
    value: QueryScalar,
    expected: str,
) -> None:
    """Supported SQL scalar values must be JSON-safe."""

    formatter = InvestigationStateFormatter()

    result = QueryResult(
        columns=("value",),
        rows=((value,),),
    )

    formatted = formatter._format_result(result)

    assert expected in formatted


def test_formats_mixed_temporal_and_decimal_values() -> None:
    """A result row may contain multiple non-JSON-native SQL values."""

    formatter = InvestigationStateFormatter()

    result = QueryResult(
        columns=("month", "total", "created_at"),
        rows=(
            (
                date(2026, 1, 1),
                Decimal("1500.25"),
                datetime(2026, 1, 31, 23, 59),
            ),
        ),
    )

    formatted = formatter._format_result(result)

    assert '["2026-01-01","1500.25","2026-01-31T23:59:00"]' in formatted
    assert "Row count: 1" in formatted


def test_serialization_preserves_row_omission_limits() -> None:
    """Serialization must not change the existing row-budget contract."""

    formatter = InvestigationStateFormatter(max_result_rows=1)

    result = QueryResult(
        columns=("month", "amount"),
        rows=(
            (date(2026, 1, 1), Decimal("100.50")),
            (date(2026, 2, 1), Decimal("200.75")),
        ),
    )

    formatted = formatter._format_result(result)

    assert '["2026-01-01","100.50"]' in formatted
    assert "200.75" not in formatted
    assert "Rows omitted: 1 of 2" in formatted
