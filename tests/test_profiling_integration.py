from pathlib import Path

import pandas as pd

from verisight.ingestion.models import (
    LoadedDataset,
    LoadedTable,
    SourceMetadata,
)
from verisight.ingestion.schema import LogicalType, SchemaInferer
from verisight.profiling.dataset import DatasetProfiler
from verisight.quality.models import (
    QualityIssueType,
    QualityScope,
    QualitySeverity,
)
from verisight.quality.rules import QualityRuleEngine


def make_table(
    *,
    name: str,
    data: pd.DataFrame,
    file_name: str,
) -> LoadedTable:
    """Create a loaded table for Phase 3 integration tests."""

    source = SourceMetadata(
        path=Path(file_name),
        file_name=file_name,
        file_extension=Path(file_name).suffix,
        file_size_bytes=1,
    )

    return LoadedTable(
        name=name,
        data=data,
        source=source,
    )


def test_profiles_multi_table_dataset_end_to_end() -> None:
    orders = make_table(
        name="orders",
        file_name="orders.csv",
        data=pd.DataFrame(
            {
                "order_id": [1, 2, 2, 4],
                "amount": [10.0, 20.0, 20.0, None],
                "status": ["open", "", "", "closed"],
            }
        ),
    )

    customers = make_table(
        name="customers",
        file_name="customers.csv",
        data=pd.DataFrame(
            {
                "customer_id": [100, 200, 300],
                "name": ["Ada", "Grace", "Lin"],
                "active": [True, False, True],
            }
        ),
    )

    dataset = LoadedDataset(
        tables=[
            orders,
            customers,
        ]
    )

    schema = SchemaInferer().infer_dataset(dataset)

    profile = DatasetProfiler().profile(
        dataset=dataset,
        schema=schema,
    )

    assert schema.table_count == 2
    assert profile.table_count == 2

    assert tuple(table.name for table in profile.tables) == (
        "orders",
        "customers",
    )

    orders_schema = schema.tables[0]

    assert tuple(column.logical_type for column in orders_schema.columns) == (
        LogicalType.INTEGER,
        LogicalType.FLOAT,
        LogicalType.STRING,
    )

    orders_profile = profile.tables[0]

    assert orders_profile.row_count == 4
    assert orders_profile.column_count == 3

    assert orders_profile.missing_value_statistics is not None
    assert orders_profile.missing_value_statistics.missing_cell_count == 1

    assert orders_profile.duplicate_statistics is not None
    assert orders_profile.duplicate_statistics.duplicate_row_count == 1

    amount_profile = orders_profile.columns[1]

    assert amount_profile.numeric_statistics is not None
    assert amount_profile.numeric_statistics.minimum == 10.0
    assert amount_profile.numeric_statistics.maximum == 20.0

    status_profile = orders_profile.columns[2]

    assert status_profile.text_statistics is not None
    assert status_profile.text_statistics.empty_count == 2

    customers_profile = profile.tables[1]

    assert customers_profile.row_count == 3
    assert customers_profile.column_count == 3

    assert customers_profile.missing_value_statistics is not None
    assert customers_profile.missing_value_statistics.missing_cell_count == 0

    assert customers_profile.duplicate_statistics is not None
    assert customers_profile.duplicate_statistics.duplicate_row_count == 0


def test_quality_findings_are_derived_from_profiles() -> None:
    table = make_table(
        name="records",
        file_name="records.csv",
        data=pd.DataFrame(
            {
                "status": ["", "", None, ""],
                "value": [10.0, 10.0, None, 10.0],
            }
        ),
    )

    dataset = LoadedDataset(tables=[table])

    schema = SchemaInferer().infer_dataset(dataset)

    profile = DatasetProfiler().profile(
        dataset=dataset,
        schema=schema,
    )

    issues = QualityRuleEngine().evaluate(profile.tables[0])

    assert tuple(issue.issue_type for issue in issues) == (
        QualityIssueType.MISSING_VALUES,
        QualityIssueType.EMPTY_STRINGS,
        QualityIssueType.CONSTANT_COLUMN,
        QualityIssueType.MISSING_VALUES,
        QualityIssueType.CONSTANT_COLUMN,
        QualityIssueType.FULLY_MISSING_ROWS,
        QualityIssueType.DUPLICATE_ROWS,
    )

    assert issues[0].scope is QualityScope.COLUMN
    assert issues[0].severity is QualitySeverity.WARNING
    assert issues[0].column_name == "status"

    duplicate_issue = issues[-1]

    assert duplicate_issue.issue_type is QualityIssueType.DUPLICATE_ROWS
    assert duplicate_issue.scope is QualityScope.TABLE
    assert duplicate_issue.column_name is None
    assert duplicate_issue.affected_count == 2
    assert duplicate_issue.affected_ratio == 0.5


def test_clean_table_produces_no_quality_findings() -> None:
    table = make_table(
        name="clean",
        file_name="clean.csv",
        data=pd.DataFrame(
            {
                "id": [1, 2, 3],
                "score": [10.0, 20.0, 30.0],
                "label": ["a", "b", "c"],
            }
        ),
    )

    dataset = LoadedDataset(tables=[table])

    schema = SchemaInferer().infer_dataset(dataset)

    profile = DatasetProfiler().profile(
        dataset=dataset,
        schema=schema,
    )

    issues = QualityRuleEngine().evaluate(profile.tables[0])

    assert issues == ()


def test_profiling_pipeline_preserves_source_data() -> None:
    data = pd.DataFrame(
        {
            "id": pd.Series(
                [1, 2, pd.NA],
                dtype="Int64",
            ),
            "name": pd.Series(
                ["", "   ", None],
                dtype="string",
            ),
            "amount": pd.Series(
                [10.0, None, 30.0],
                dtype="Float64",
            ),
        }
    )

    original = data.copy(deep=True)

    table = make_table(
        name="records",
        file_name="records.csv",
        data=data,
    )

    dataset = LoadedDataset(tables=[table])

    schema = SchemaInferer().infer_dataset(dataset)

    profile = DatasetProfiler().profile(
        dataset=dataset,
        schema=schema,
    )

    QualityRuleEngine().evaluate(profile.tables[0])

    pd.testing.assert_frame_equal(
        data,
        original,
    )


def test_empty_dataset_is_supported() -> None:
    dataset = LoadedDataset(tables=[])

    schema = SchemaInferer().infer_dataset(dataset)

    profile = DatasetProfiler().profile(
        dataset=dataset,
        schema=schema,
    )

    assert schema.table_count == 0
    assert profile.table_count == 0
    assert profile.tables == ()
