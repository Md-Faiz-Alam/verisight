"""High-level dataset analysis orchestration for VeriSight."""

from verisight.analysis.models import DatasetAnalysis
from verisight.ingestion.models import LoadedDataset
from verisight.ingestion.schema import SchemaInferer
from verisight.profiling.dataset import DatasetProfiler
from verisight.quality.models import QualityIssue
from verisight.quality.rules import QualityRuleEngine


class DatasetAnalyzer:
    """Coordinate schema inference, profiling, and quality analysis."""

    def __init__(self) -> None:
        self._schema_inferer = SchemaInferer()
        self._dataset_profiler = DatasetProfiler()
        self._quality_rule_engine = QualityRuleEngine()

    def analyze(self, dataset: LoadedDataset) -> DatasetAnalysis:
        """Build a complete deterministic analysis of a loaded dataset."""

        schema = self._schema_inferer.infer_dataset(dataset)

        profile = self._dataset_profiler.profile(
            dataset=dataset,
            schema=schema,
        )

        issues: list[QualityIssue] = []

        for table_profile in profile.tables:
            issues.extend(self._quality_rule_engine.evaluate(table_profile))

        return DatasetAnalysis(
            schema=schema,
            profile=profile,
            issues=tuple(issues),
        )
