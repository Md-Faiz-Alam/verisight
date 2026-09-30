from dataclasses import FrozenInstanceError
from pathlib import Path

import pandas as pd
import pytest

from verisight.analysis.insights import InsightType
from verisight.analysis.result import AnalysisResultBuilder, DatasetAnalysisResult
from verisight.analysis.service import DatasetAnalyzer
from verisight.analysis.summary import AnalysisSummary
from verisight.ingestion.models import LoadedDataset, LoadedTable, SourceMetadata


def make_table(
    *,
    name: str,
    data: pd.DataFrame,
    relation_name: str | None = None,
) -> LoadedTable:
    """Create a loaded table for unified analysis result tests."""

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


def test_builds_unified_analysis_result() -> None:
    table = make_table(
        name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2, 2],
                "amount": [10.0, 20.0, 20.0],
            }
        ),
    )

    analysis = DatasetAnalyzer().analyze(
        LoadedDataset(
            tables=[table],
        )
    )

    result = AnalysisResultBuilder().build(analysis)

    assert result.analysis is analysis

    assert result.summary.table_count == 1
    assert result.summary.total_row_count == 3
    assert result.summary.total_column_count == 2

    assert result.issue_count == analysis.issue_count
    assert result.insight_count == len(result.insights)


def test_result_contains_generated_insights() -> None:
    table = make_table(
        name="orders",
        data=pd.DataFrame(
            {
                "order_id": [1, 2, 2],
            }
        ),
    )

    analysis = DatasetAnalyzer().analyze(
        LoadedDataset(
            tables=[table],
        )
    )

    result = AnalysisResultBuilder().build(analysis)

    assert tuple(insight.insight_type for insight in result.insights) == (
        InsightType.DATASET_STRUCTURE,
        InsightType.TABLE_STRUCTURE,
        InsightType.DATA_QUALITY,
    )

    assert result.insight_count == 3


def test_result_preserves_duplicate_display_names_by_relation_identity() -> None:
    first = make_table(
        name="sales",
        relation_name="sales",
        data=pd.DataFrame(
            {
                "value": [1, 2],
            }
        ),
    )

    second = make_table(
        name="sales",
        relation_name="sales_2",
        data=pd.DataFrame(
            {
                "value": [10, 20],
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

    result = AnalysisResultBuilder().build(analysis)

    table_insights = tuple(
        insight
        for insight in result.insights
        if insight.insight_type is InsightType.TABLE_STRUCTURE
    )

    assert tuple(insight.table_name for insight in table_insights) == (
        "sales",
        "sales",
    )

    assert tuple(insight.relation_name for insight in table_insights) == (
        "sales",
        "sales_2",
    )


def test_empty_analysis_builds_valid_result() -> None:
    analysis = DatasetAnalyzer().analyze(
        LoadedDataset(
            tables=[],
        )
    )

    result = AnalysisResultBuilder().build(analysis)

    assert result.analysis is analysis

    assert result.summary.table_count == 0
    assert result.summary.issue_count == 0

    assert result.issue_count == 0

    assert result.insight_count == 1
    assert result.insights[0].insight_type is InsightType.DATASET_STRUCTURE
    assert result.insights[0].evidence["table_count"] == 0


def test_builder_does_not_replace_analysis_object() -> None:
    table = make_table(
        name="customers",
        data=pd.DataFrame(
            {
                "customer_id": [1, 2, 3],
                "name": ["Ada", "Grace", "Linus"],
            }
        ),
    )

    analysis = DatasetAnalyzer().analyze(
        LoadedDataset(
            tables=[table],
        )
    )

    result = AnalysisResultBuilder().build(analysis)

    assert result.analysis is analysis
    assert result.analysis.schema is analysis.schema
    assert result.analysis.profile is analysis.profile
    assert result.analysis.issues is analysis.issues


def test_dataset_analysis_result_is_immutable() -> None:
    analysis = DatasetAnalyzer().analyze(
        LoadedDataset(
            tables=[],
        )
    )

    result = DatasetAnalysisResult(
        analysis=analysis,
        summary=AnalysisSummary(
            table_count=0,
            total_row_count=0,
            total_column_count=0,
            issue_count=0,
            info_issue_count=0,
            warning_issue_count=0,
            error_issue_count=0,
            table_issue_count=0,
            column_issue_count=0,
            affected_relation_names=(),
        ),
        insights=(),
    )

    with pytest.raises(FrozenInstanceError):
        result.insights = ()  # type: ignore[misc]
