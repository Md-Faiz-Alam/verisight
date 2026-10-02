from verisight.execution.context import QueryContextBuilder
from verisight.ingestion.schema import (
    ColumnSchema,
    DatasetSchema,
    LogicalType,
    TableSchema,
)


def test_builds_query_context_from_dataset_schema() -> None:
    schema = DatasetSchema(
        tables=(
            TableSchema(
                name="Orders",
                relation_name="orders",
                row_count=3,
                column_count=2,
                columns=(
                    ColumnSchema(
                        name="order_id",
                        physical_dtype="int64",
                        logical_type=LogicalType.INTEGER,
                        nullable=False,
                        missing_count=0,
                    ),
                    ColumnSchema(
                        name="amount",
                        physical_dtype="float64",
                        logical_type=LogicalType.FLOAT,
                        nullable=True,
                        missing_count=1,
                    ),
                ),
            ),
        )
    )

    context = QueryContextBuilder().build(schema)

    assert context.relation_count == 1

    relation = context.relations[0]

    assert relation.name == "Orders"
    assert relation.relation_name == "orders"
    assert relation.row_count == 3

    assert relation.columns[0].name == "order_id"
    assert relation.columns[0].physical_dtype == "int64"
    assert relation.columns[0].logical_type is LogicalType.INTEGER
    assert relation.columns[0].nullable is False

    assert relation.columns[1].name == "amount"
    assert relation.columns[1].logical_type is LogicalType.FLOAT
    assert relation.columns[1].nullable is True


def test_builds_context_for_multiple_relations() -> None:
    schema = DatasetSchema(
        tables=(
            TableSchema(
                name="Customers",
                relation_name="customers",
                row_count=2,
                column_count=1,
                columns=(
                    ColumnSchema(
                        name="customer_id",
                        physical_dtype="int64",
                        logical_type=LogicalType.INTEGER,
                        nullable=False,
                        missing_count=0,
                    ),
                ),
            ),
            TableSchema(
                name="Orders",
                relation_name="orders",
                row_count=3,
                column_count=1,
                columns=(
                    ColumnSchema(
                        name="order_id",
                        physical_dtype="int64",
                        logical_type=LogicalType.INTEGER,
                        nullable=False,
                        missing_count=0,
                    ),
                ),
            ),
        )
    )

    context = QueryContextBuilder().build(schema)

    assert context.relation_count == 2
    assert tuple(relation.relation_name for relation in context.relations) == (
        "customers",
        "orders",
    )


def test_builds_empty_query_context() -> None:
    context = QueryContextBuilder().build(DatasetSchema(tables=()))

    assert context.relations == ()
    assert context.relation_count == 0
