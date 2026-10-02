from verisight.execution.context import (
    QueryColumn,
    QueryContext,
    QueryRelation,
)
from verisight.execution.formatting import QueryContextFormatter
from verisight.ingestion.schema import LogicalType


def test_formats_query_context() -> None:
    context = QueryContext(
        relations=(
            QueryRelation(
                name="Orders",
                relation_name="orders",
                row_count=3,
                columns=(
                    QueryColumn(
                        name="order_id",
                        physical_dtype="int64",
                        logical_type=LogicalType.INTEGER,
                        nullable=False,
                    ),
                    QueryColumn(
                        name="amount",
                        physical_dtype="float64",
                        logical_type=LogicalType.FLOAT,
                        nullable=True,
                    ),
                ),
            ),
        )
    )

    formatted = QueryContextFormatter().format(context)

    assert formatted == (
        "RELATION orders\n"
        "DISPLAY NAME: Orders\n"
        "ROWS: 3\n"
        "COLUMNS:\n"
        "- order_id | integer | int64 | nullable=false\n"
        "- amount | float | float64 | nullable=true"
    )


def test_formats_multiple_relations_with_stable_separation() -> None:
    context = QueryContext(
        relations=(
            QueryRelation(
                name="Customers",
                relation_name="customers",
                row_count=2,
                columns=(
                    QueryColumn(
                        name="customer_id",
                        physical_dtype="int64",
                        logical_type=LogicalType.INTEGER,
                        nullable=False,
                    ),
                ),
            ),
            QueryRelation(
                name="Orders",
                relation_name="orders",
                row_count=3,
                columns=(
                    QueryColumn(
                        name="order_id",
                        physical_dtype="int64",
                        logical_type=LogicalType.INTEGER,
                        nullable=False,
                    ),
                ),
            ),
        )
    )

    formatted = QueryContextFormatter().format(context)

    assert formatted == (
        "RELATION customers\n"
        "DISPLAY NAME: Customers\n"
        "ROWS: 2\n"
        "COLUMNS:\n"
        "- customer_id | integer | int64 | nullable=false\n"
        "\n"
        "RELATION orders\n"
        "DISPLAY NAME: Orders\n"
        "ROWS: 3\n"
        "COLUMNS:\n"
        "- order_id | integer | int64 | nullable=false"
    )


def test_formats_empty_query_context() -> None:
    formatted = QueryContextFormatter().format(QueryContext(relations=()))

    assert formatted == ""
