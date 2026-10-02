from verisight.execution.models import QueryResult


def test_query_result_exposes_dimensions() -> None:
    result = QueryResult(
        columns=("customer_id", "total"),
        rows=(
            (1, 25.0),
            (2, 40.0),
        ),
    )

    assert result.row_count == 2
    assert result.column_count == 2
    assert result.is_empty is False


def test_empty_query_result_is_empty() -> None:
    result = QueryResult(
        columns=("customer_id",),
        rows=(),
    )

    assert result.row_count == 0
    assert result.column_count == 1
    assert result.is_empty is True


def test_zero_column_query_result_reports_zero_columns() -> None:
    result = QueryResult(
        columns=(),
        rows=(),
    )

    assert result.row_count == 0
    assert result.column_count == 0
    assert result.is_empty is True
