from pathlib import Path

import pandas as pd

from verisight.analysis.service import DatasetAnalyzer
from verisight.ingestion.models import (
    LoadedDataset,
    LoadedTable,
    SourceMetadata,
)
from verisight.quality.models import QualityIssueType


def make_table(
    *,
    name: str,
    data: pd.DataFrame,
    relation_name: str | None = None,
) -> LoadedTable:
    """Create a loaded table for analysis service tests."""

    source = SourceMetadata(
        path=Path(f"{name}.csv"),
        file_name=f"{name}.csv",
        file_extension=".csv",
        file_size_bytes=1,
    )

    table = LoadedTable(
        name=name,
        data=data,
        source=source,
    )

    if relation_name is not None:
        table.relation_name = relation_name

    return table


def test_analyzes_single_table_dataset() -> None:
    table = make_table(
        name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2, 2],
                "amount": [10.0, 20.0, 20.0],
            }
        ),
    )

    analysis = DatasetAnalyzer().analyze(LoadedDataset(tables=[table]))

    assert analysis.schema.table_count == 1
    assert analysis.profile.table_count == 1

    assert analysis.schema.tables[0].name == "orders"
    assert analysis.schema.tables[0].relation_name == "orders"

    assert analysis.profile.tables[0].name == "orders"
    assert analysis.profile.tables[0].relation_name == "orders"

    assert analysis.issue_count == 1

    issue = analysis.issues[0]

    assert issue.issue_type is QualityIssueType.DUPLICATE_ROWS
    assert issue.table_name == "orders"
    assert issue.relation_name == "orders"


def test_analyzes_multiple_tables() -> None:
    orders = make_table(
        name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2, 2],
            }
        ),
    )

    customers = make_table(
        name="customers",
        data=pd.DataFrame(
            {
                "customer_id": [10, 20],
                "name": ["Ada", ""],
            }
        ),
    )

    analysis = DatasetAnalyzer().analyze(
        LoadedDataset(
            tables=[
                orders,
                customers,
            ]
        )
    )

    assert analysis.schema.table_count == 2
    assert analysis.profile.table_count == 2

    assert tuple(table.relation_name for table in analysis.schema.tables) == (
        "orders",
        "customers",
    )

    assert tuple(table.relation_name for table in analysis.profile.tables) == (
        "orders",
        "customers",
    )

    assert tuple(issue.issue_type for issue in analysis.issues) == (
        QualityIssueType.DUPLICATE_ROWS,
        QualityIssueType.EMPTY_STRINGS,
    )

    assert tuple(issue.relation_name for issue in analysis.issues) == (
        "orders",
        "customers",
    )


def test_preserves_duplicate_display_names_using_relation_identity() -> None:
    first = make_table(
        name="sales",
        relation_name="sales",
        data=pd.DataFrame(
            {
                "value": [1, 1],
            }
        ),
    )

    second = make_table(
        name="sales",
        relation_name="sales_2",
        data=pd.DataFrame(
            {
                "value": ["", "active"],
            }
        ),
    )

    analysis = DatasetAnalyzer().analyze(
        LoadedDataset(
            tables=[
                first,
                second,
            ]
        )
    )

    assert tuple(table.name for table in analysis.profile.tables) == (
        "sales",
        "sales",
    )

    assert tuple(table.relation_name for table in analysis.profile.tables) == (
        "sales",
        "sales_2",
    )

    assert tuple(issue.relation_name for issue in analysis.issues) == (
        "sales",
        "sales",
        "sales_2",
    )

    assert tuple(issue.issue_type for issue in analysis.issues) == (
        QualityIssueType.CONSTANT_COLUMN,
        QualityIssueType.DUPLICATE_ROWS,
        QualityIssueType.EMPTY_STRINGS,
    )

    assert tuple(issue.table_name for issue in analysis.issues) == (
        "sales",
        "sales",
        "sales",
    )


def test_clean_dataset_produces_no_quality_issues() -> None:
    table = make_table(
        name="customers",
        data=pd.DataFrame(
            {
                "customer_id": [1, 2, 3],
                "name": ["Ada", "Grace", "Linus"],
            }
        ),
    )

    analysis = DatasetAnalyzer().analyze(LoadedDataset(tables=[table]))

    assert analysis.issue_count == 0
    assert analysis.issues == ()


def test_empty_dataset_produces_empty_analysis() -> None:
    analysis = DatasetAnalyzer().analyze(LoadedDataset(tables=[]))

    assert analysis.schema.table_count == 0
    assert analysis.schema.tables == ()

    assert analysis.profile.table_count == 0
    assert analysis.profile.tables == ()

    assert analysis.issue_count == 0
    assert analysis.issues == ()


def test_quality_issues_preserve_table_and_rule_order() -> None:
    first = make_table(
        name="first",
        data=pd.DataFrame(
            {
                "value": [None, None],
            }
        ),
    )

    second = make_table(
        name="second",
        data=pd.DataFrame(
            {
                "status": ["", ""],
            }
        ),
    )

    analysis = DatasetAnalyzer().analyze(
        LoadedDataset(
            tables=[
                first,
                second,
            ]
        )
    )

    assert tuple(
        (
            issue.relation_name,
            issue.issue_type,
        )
        for issue in analysis.issues
    ) == (
        (
            "first",
            QualityIssueType.MISSING_VALUES,
        ),
        (
            "first",
            QualityIssueType.FULLY_MISSING_ROWS,
        ),
        (
            "first",
            QualityIssueType.DUPLICATE_ROWS,
        ),
        (
            "second",
            QualityIssueType.EMPTY_STRINGS,
        ),
        (
            "second",
            QualityIssueType.CONSTANT_COLUMN,
        ),
        (
            "second",
            QualityIssueType.DUPLICATE_ROWS,
        ),
    )


def test_analysis_does_not_mutate_source_tables() -> None:
    orders_data = pd.DataFrame(
        {
            "order_id": [1, 2, 2],
            "amount": [10.0, None, None],
        }
    )

    customers_data = pd.DataFrame(
        {
            "customer_id": [10, 20],
            "name": ["Ada", ""],
        }
    )

    original_orders = orders_data.copy(deep=True)
    original_customers = customers_data.copy(deep=True)

    orders = make_table(
        name="orders",
        data=orders_data,
    )

    customers = make_table(
        name="customers",
        data=customers_data,
    )

    dataset = LoadedDataset(
        tables=[
            orders,
            customers,
        ]
    )

    DatasetAnalyzer().analyze(dataset)

    pd.testing.assert_frame_equal(
        orders_data,
        original_orders,
    )

    pd.testing.assert_frame_equal(
        customers_data,
        original_customers,
    )
