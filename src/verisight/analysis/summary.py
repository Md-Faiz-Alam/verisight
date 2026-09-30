"""Deterministic summary generation for VeriSight dataset analysis."""

from collections import Counter
from dataclasses import dataclass

from verisight.analysis.models import DatasetAnalysis
from verisight.quality.models import QualityScope, QualitySeverity


@dataclass(frozen=True, slots=True)
class AnalysisSummary:
    """Compact deterministic summary of a dataset analysis."""

    table_count: int
    total_row_count: int
    total_column_count: int
    issue_count: int
    info_issue_count: int
    warning_issue_count: int
    error_issue_count: int
    table_issue_count: int
    column_issue_count: int
    affected_relation_names: tuple[str, ...]

    @property
    def affected_table_count(self) -> int:
        """Return the number of distinct tables with quality issues."""

        return len(self.affected_relation_names)


class AnalysisSummarizer:
    """Build compact deterministic summaries from complete analyses."""

    def summarize(self, analysis: DatasetAnalysis) -> AnalysisSummary:
        """Summarize structural and quality information from an analysis."""

        severity_counts = Counter(issue.severity for issue in analysis.issues)
        scope_counts = Counter(issue.scope for issue in analysis.issues)

        affected_relation_names = tuple(
            dict.fromkeys(issue.relation_name for issue in analysis.issues)
        )

        return AnalysisSummary(
            table_count=analysis.profile.table_count,
            total_row_count=sum(table.row_count for table in analysis.profile.tables),
            total_column_count=sum(
                table.column_count for table in analysis.profile.tables
            ),
            issue_count=analysis.issue_count,
            info_issue_count=severity_counts[QualitySeverity.INFO],
            warning_issue_count=severity_counts[QualitySeverity.WARNING],
            error_issue_count=severity_counts[QualitySeverity.ERROR],
            table_issue_count=scope_counts[QualityScope.TABLE],
            column_issue_count=scope_counts[QualityScope.COLUMN],
            affected_relation_names=affected_relation_names,
        )
