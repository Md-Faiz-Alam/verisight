"""Domain models for VeriSight data-quality findings."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class QualityIssueType(StrEnum):
    """Supported deterministic data-quality issue types."""

    MISSING_VALUES = "missing_values"
    FULLY_MISSING_ROWS = "fully_missing_rows"
    DUPLICATE_ROWS = "duplicate_rows"
    EMPTY_STRINGS = "empty_strings"
    CONSTANT_COLUMN = "constant_column"
    HIGH_CARDINALITY = "high_cardinality"


class QualitySeverity(StrEnum):
    """Severity assigned to a data-quality finding."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class QualityScope(StrEnum):
    """Dataset location affected by a data-quality finding."""

    TABLE = "table"
    COLUMN = "column"


@dataclass(frozen=True, slots=True)
class QualityIssue:
    """A deterministic data-quality finding."""

    issue_type: QualityIssueType
    severity: QualitySeverity
    scope: QualityScope
    table_name: str
    relation_name: str
    message: str
    column_name: str | None = None
    affected_count: int | None = None
    affected_ratio: float | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
