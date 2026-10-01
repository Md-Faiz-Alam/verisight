"""Deterministic analytical insight models for VeriSight."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType

from verisight.analysis.models import DatasetAnalysis
from verisight.quality.models import QualityScope


class InsightType(StrEnum):
    """Supported deterministic analytical insight types."""

    DATASET_STRUCTURE = "dataset_structure"
    TABLE_STRUCTURE = "table_structure"
    DATA_QUALITY = "data_quality"


class InsightScope(StrEnum):
    """Dataset location described by an analytical insight."""

    DATASET = "dataset"
    TABLE = "table"
    COLUMN = "column"


@dataclass(frozen=True, slots=True)
class AnalysisInsight:
    """A deterministic analytical observation about a dataset."""

    insight_type: InsightType
    scope: InsightScope
    message: str
    table_name: str | None = None
    relation_name: str | None = None
    column_name: str | None = None
    evidence: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Store evidence as an immutable snapshot."""

        object.__setattr__(
            self,
            "evidence",
            MappingProxyType(dict(self.evidence)),
        )


class InsightGenerator:
    """Generate deterministic analytical insights from a dataset analysis."""

    def generate(
        self,
        analysis: DatasetAnalysis,
    ) -> tuple[AnalysisInsight, ...]:
        """Generate ordered analytical insights from an analysis."""

        insights: list[AnalysisInsight] = []

        insights.append(
            AnalysisInsight(
                insight_type=InsightType.DATASET_STRUCTURE,
                scope=InsightScope.DATASET,
                message=f"Dataset contains {analysis.profile.table_count} table(s).",
                evidence={
                    "table_count": analysis.profile.table_count,
                    "total_row_count": sum(
                        table.row_count for table in analysis.profile.tables
                    ),
                    "total_column_count": sum(
                        table.column_count for table in analysis.profile.tables
                    ),
                },
            )
        )

        for table in analysis.profile.tables:
            insights.append(
                AnalysisInsight(
                    insight_type=InsightType.TABLE_STRUCTURE,
                    scope=InsightScope.TABLE,
                    message=(
                        f"Table '{table.name}' contains "
                        f"{table.row_count} row(s) and "
                        f"{table.column_count} column(s)."
                    ),
                    table_name=table.name,
                    relation_name=table.relation_name,
                    evidence={
                        "row_count": table.row_count,
                        "column_count": table.column_count,
                    },
                )
            )

        for issue in analysis.issues:
            insights.append(
                AnalysisInsight(
                    insight_type=InsightType.DATA_QUALITY,
                    scope=(
                        InsightScope.TABLE
                        if issue.scope is QualityScope.TABLE
                        else InsightScope.COLUMN
                    ),
                    message=issue.message,
                    table_name=issue.table_name,
                    relation_name=issue.relation_name,
                    column_name=issue.column_name,
                    evidence=dict(issue.evidence),
                )
            )

        return tuple(insights)
