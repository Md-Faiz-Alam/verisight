"""Deterministic data-quality rules for VeriSight."""

from verisight.evidence import EvidenceInput
from verisight.ingestion.schema import LogicalType
from verisight.profiling.models import TableProfile
from verisight.quality.models import (
    QualityIssue,
    QualityIssueType,
    QualityScope,
    QualitySeverity,
)

_HIGH_CARDINALITY_MIN_NON_MISSING_COUNT = 20
_HIGH_CARDINALITY_DISTINCT_RATIO = 0.90


class QualityRuleEngine:
    """Evaluate deterministic quality rules against a table profile."""

    def evaluate(self, profile: TableProfile) -> tuple[QualityIssue, ...]:
        """Return deterministic quality findings for a table profile."""

        issues: list[QualityIssue] = []

        issues.extend(self._evaluate_column_rules(profile))
        issues.extend(self._evaluate_table_rules(profile))

        return tuple(issues)

    @staticmethod
    def _column_issue(
        *,
        profile: TableProfile,
        column_name: str,
        issue_type: QualityIssueType,
        severity: QualitySeverity,
        message: str,
        affected_count: int | None = None,
        affected_ratio: float | None = None,
        evidence: EvidenceInput | None = None,
    ) -> QualityIssue:
        """Build a column-level quality issue."""

        return QualityIssue(
            issue_type=issue_type,
            severity=severity,
            scope=QualityScope.COLUMN,
            table_name=profile.name,
            relation_name=profile.relation_name,
            column_name=column_name,
            message=message,
            affected_count=affected_count,
            affected_ratio=affected_ratio,
            evidence={} if evidence is None else evidence,
        )

    @staticmethod
    def _table_issue(
        *,
        profile: TableProfile,
        issue_type: QualityIssueType,
        severity: QualitySeverity,
        message: str,
        affected_count: int | None = None,
        affected_ratio: float | None = None,
        evidence: EvidenceInput | None = None,
    ) -> QualityIssue:
        """Build a table-level quality issue."""

        return QualityIssue(
            issue_type=issue_type,
            severity=severity,
            scope=QualityScope.TABLE,
            table_name=profile.name,
            relation_name=profile.relation_name,
            message=message,
            affected_count=affected_count,
            affected_ratio=affected_ratio,
            evidence={} if evidence is None else evidence,
        )

    @classmethod
    def _evaluate_column_rules(
        cls,
        profile: TableProfile,
    ) -> list[QualityIssue]:
        """Evaluate deterministic column-level quality rules."""

        issues: list[QualityIssue] = []

        for column in profile.columns:
            if column.row_count > 0 and column.missing_count == column.row_count:
                issues.append(
                    cls._column_issue(
                        profile=profile,
                        column_name=column.name,
                        issue_type=QualityIssueType.ENTIRELY_MISSING_COLUMN,
                        severity=QualitySeverity.WARNING,
                        message="Column is entirely missing.",
                        affected_count=column.missing_count,
                        affected_ratio=column.missing_ratio,
                        evidence={
                            "missing_count": column.missing_count,
                            "non_missing_count": column.non_missing_count,
                            "row_count": column.row_count,
                        },
                    )
                )
            elif column.missing_count > 0:
                issues.append(
                    cls._column_issue(
                        profile=profile,
                        column_name=column.name,
                        issue_type=QualityIssueType.MISSING_VALUES,
                        severity=QualitySeverity.WARNING,
                        message="Column contains missing values.",
                        affected_count=column.missing_count,
                        affected_ratio=column.missing_ratio,
                        evidence={
                            "missing_count": column.missing_count,
                            "non_missing_count": column.non_missing_count,
                            "row_count": column.row_count,
                        },
                    )
                )

            numeric_statistics = column.numeric_statistics

            if (
                numeric_statistics is not None
                and numeric_statistics.non_finite_count > 0
            ):
                issues.append(
                    cls._column_issue(
                        profile=profile,
                        column_name=column.name,
                        issue_type=QualityIssueType.NON_FINITE_VALUES,
                        severity=QualitySeverity.WARNING,
                        message="Column contains non-finite numeric values.",
                        affected_count=numeric_statistics.non_finite_count,
                        affected_ratio=numeric_statistics.non_finite_ratio,
                        evidence={
                            "non_finite_count": (numeric_statistics.non_finite_count),
                            "non_missing_count": column.non_missing_count,
                            "non_finite_ratio": (numeric_statistics.non_finite_ratio),
                        },
                    )
                )

            text_statistics = column.text_statistics

            if text_statistics is not None and text_statistics.empty_count > 0:
                issues.append(
                    cls._column_issue(
                        profile=profile,
                        column_name=column.name,
                        issue_type=QualityIssueType.EMPTY_STRINGS,
                        severity=QualitySeverity.WARNING,
                        message="Column contains empty strings.",
                        affected_count=text_statistics.empty_count,
                        affected_ratio=text_statistics.empty_ratio,
                        evidence={
                            "empty_count": text_statistics.empty_count,
                            "non_missing_count": column.non_missing_count,
                        },
                    )
                )

            if column.non_missing_count > 1 and column.distinct_count == 1:
                issues.append(
                    cls._column_issue(
                        profile=profile,
                        column_name=column.name,
                        issue_type=QualityIssueType.CONSTANT_COLUMN,
                        severity=QualitySeverity.INFO,
                        message=(
                            "Column contains only one distinct non-missing value."
                        ),
                        affected_count=column.non_missing_count,
                        affected_ratio=1.0,
                        evidence={
                            "distinct_count": column.distinct_count,
                            "non_missing_count": column.non_missing_count,
                            "row_count": column.row_count,
                        },
                    )
                )

            if (
                column.logical_type is LogicalType.STRING
                and column.non_missing_count >= _HIGH_CARDINALITY_MIN_NON_MISSING_COUNT
                and column.distinct_ratio >= _HIGH_CARDINALITY_DISTINCT_RATIO
            ):
                issues.append(
                    cls._column_issue(
                        profile=profile,
                        column_name=column.name,
                        issue_type=QualityIssueType.HIGH_CARDINALITY,
                        severity=QualitySeverity.INFO,
                        message="Column has high cardinality.",
                        affected_count=column.distinct_count,
                        affected_ratio=column.distinct_ratio,
                        evidence={
                            "distinct_count": column.distinct_count,
                            "non_missing_count": column.non_missing_count,
                            "distinct_ratio": column.distinct_ratio,
                            "minimum_non_missing_count": (
                                _HIGH_CARDINALITY_MIN_NON_MISSING_COUNT
                            ),
                            "distinct_ratio_threshold": (
                                _HIGH_CARDINALITY_DISTINCT_RATIO
                            ),
                        },
                    )
                )

        return issues

    @classmethod
    def _evaluate_table_rules(
        cls,
        profile: TableProfile,
    ) -> list[QualityIssue]:
        """Evaluate deterministic table-level quality rules."""

        issues: list[QualityIssue] = []

        missing_statistics = profile.missing_value_statistics

        if (
            missing_statistics is not None
            and missing_statistics.fully_missing_row_count > 0
        ):
            issues.append(
                cls._table_issue(
                    profile=profile,
                    issue_type=QualityIssueType.FULLY_MISSING_ROWS,
                    severity=QualitySeverity.WARNING,
                    message="Table contains fully missing rows.",
                    affected_count=missing_statistics.fully_missing_row_count,
                    affected_ratio=missing_statistics.fully_missing_row_ratio,
                    evidence={
                        "fully_missing_row_count": (
                            missing_statistics.fully_missing_row_count
                        ),
                        "row_count": profile.row_count,
                    },
                )
            )

        duplicate_statistics = profile.duplicate_statistics

        if (
            duplicate_statistics is not None
            and duplicate_statistics.duplicate_row_count > 0
        ):
            issues.append(
                cls._table_issue(
                    profile=profile,
                    issue_type=QualityIssueType.DUPLICATE_ROWS,
                    severity=QualitySeverity.WARNING,
                    message="Table contains duplicate rows.",
                    affected_count=duplicate_statistics.duplicate_row_count,
                    affected_ratio=duplicate_statistics.duplicate_row_ratio,
                    evidence={
                        "duplicate_row_count": (
                            duplicate_statistics.duplicate_row_count
                        ),
                        "duplicate_group_row_count": (
                            duplicate_statistics.duplicate_group_row_count
                        ),
                        "row_count": profile.row_count,
                    },
                )
            )

        return issues
