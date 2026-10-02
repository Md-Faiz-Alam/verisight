"""Public analysis facade for VeriSight."""

from collections.abc import Iterable
from pathlib import Path

from verisight.analysis.result import AnalysisResultBuilder, DatasetAnalysisResult
from verisight.analysis.service import DatasetAnalyzer
from verisight.config import Settings
from verisight.ingestion.service import DatasetLoader


class VeriSight:
    """Provide the public deterministic analysis workflow."""

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize the analysis facade."""

        resolved_settings = settings if settings is not None else Settings()

        self._dataset_loader = DatasetLoader(resolved_settings)
        self._dataset_analyzer = DatasetAnalyzer()
        self._result_builder = AnalysisResultBuilder()

    def analyze(
        self,
        paths: Iterable[str | Path],
    ) -> DatasetAnalysisResult:
        """Load and analyze one or more dataset files."""

        dataset = self._dataset_loader.load(paths)
        analysis = self._dataset_analyzer.analyze(dataset)

        return self._result_builder.build(analysis)
