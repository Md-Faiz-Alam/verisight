"""Domain models for complete VeriSight dataset analysis."""

from dataclasses import dataclass

from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile
from verisight.quality.models import QualityIssue


@dataclass(frozen=True, slots=True)
class DatasetAnalysis:
    """Complete deterministic analysis of an ingested dataset."""

    schema: DatasetSchema
    profile: DatasetProfile
    issues: tuple[QualityIssue, ...]

    @property
    def issue_count(self) -> int:
        """Return the total number of quality issues."""

        return len(self.issues)
