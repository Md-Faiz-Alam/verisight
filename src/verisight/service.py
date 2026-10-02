"""Public analysis and analytical execution facade for VeriSight."""

from collections.abc import Iterable
from pathlib import Path

from verisight.analysis.result import AnalysisResultBuilder, DatasetAnalysisResult
from verisight.analysis.service import DatasetAnalyzer
from verisight.config import Settings
from verisight.execution.gemini import GeminiTextGenerationClient
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.models import QueryResult
from verisight.execution.planning import QueryPlanner
from verisight.execution.service import AnalyticalExecutionService
from verisight.ingestion.service import DatasetLoader


class VeriSight:
    """Provide the public VeriSight analysis and execution workflows."""

    def __init__(
        self,
        settings: Settings | None = None,
        planner: QueryPlanner | None = None,
    ) -> None:
        """Initialize the VeriSight facade."""

        resolved_settings = settings if settings is not None else Settings()

        self._dataset_loader = DatasetLoader(resolved_settings)
        self._dataset_analyzer = DatasetAnalyzer()
        self._result_builder = AnalysisResultBuilder()
        self._planner = self._resolve_planner(
            settings=resolved_settings,
            planner=planner,
        )

    @staticmethod
    def _resolve_planner(
        *,
        settings: Settings,
        planner: QueryPlanner | None,
    ) -> QueryPlanner | None:
        """Resolve an explicitly configured or Gemini-backed query planner."""

        if planner is not None:
            return planner

        if settings.gemini_api_key is None or not settings.gemini_api_key.strip():
            return None

        client = GeminiTextGenerationClient(
            api_key=settings.gemini_api_key,
            model=settings.gemini_model,
        )

        return GenerativeQueryPlanner(client)

    def analyze(
        self,
        paths: Iterable[str | Path],
    ) -> DatasetAnalysisResult:
        """Load and analyze one or more dataset files."""

        dataset = self._dataset_loader.load(paths)
        analysis = self._dataset_analyzer.analyze(dataset)

        return self._result_builder.build(analysis)

    def execute(
        self,
        paths: Iterable[str | Path],
        query: str,
    ) -> QueryResult:
        """Execute a read-only analytical query against dataset files."""

        dataset = self._dataset_loader.load(paths)
        execution_service = AnalyticalExecutionService(dataset)

        return execution_service.execute(query)

    def ask(
        self,
        paths: Iterable[str | Path],
        question: str,
    ) -> QueryResult:
        """Answer a natural-language analytical question against dataset files."""

        dataset = self._dataset_loader.load(paths)
        execution_service = AnalyticalExecutionService(
            dataset,
            planner=self._planner,
        )

        return execution_service.ask(question)
