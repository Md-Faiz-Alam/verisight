"""Public analysis and analytical execution facade for VeriSight."""

from collections.abc import Iterable
from pathlib import Path

from verisight.analysis.result import (
    AnalysisResultBuilder,
    DatasetAnalysisResult,
)
from verisight.analysis.service import DatasetAnalyzer
from verisight.config import Settings
from verisight.execution.exceptions import InvestigationError
from verisight.execution.gemini import GeminiTextGenerationClient
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.generative_investigator import (
    GenerativeInvestigator,
)
from verisight.execution.generative_synthesis import (
    GenerativeInvestigationSynthesizer,
)
from verisight.execution.investigation_result import InvestigationResult
from verisight.execution.investigator import Investigator
from verisight.execution.models import QueryResult
from verisight.execution.orchestration import InvestigationOrchestrator
from verisight.execution.planning import QueryPlanner
from verisight.execution.service import AnalyticalExecutionService
from verisight.execution.synthesis import InvestigationSynthesizer
from verisight.ingestion.service import DatasetLoader


class VeriSight:
    """Provide the public VeriSight analysis and execution workflows."""

    def __init__(
        self,
        settings: Settings | None = None,
        planner: QueryPlanner | None = None,
        investigator: Investigator | None = None,
        synthesizer: InvestigationSynthesizer | None = None,
    ) -> None:
        """Initialize the VeriSight facade."""

        resolved_settings = settings if settings is not None else Settings()

        self._settings = resolved_settings
        self._dataset_loader = DatasetLoader(resolved_settings)
        self._dataset_analyzer = DatasetAnalyzer()
        self._result_builder = AnalysisResultBuilder()

        self._planner = planner
        self._investigator = investigator
        self._synthesizer = synthesizer

        if self._planner is None:
            self._planner = self._build_gemini_planner(resolved_settings)

    @staticmethod
    def _build_generation_client(
        settings: Settings,
    ) -> GeminiTextGenerationClient | None:
        """Build a Gemini generation client when credentials are configured."""

        api_key = settings.gemini_api_key

        if api_key is None or not api_key.strip():
            return None

        return GeminiTextGenerationClient(
            api_key=api_key,
            model=settings.gemini_model,
        )

    @classmethod
    def _build_gemini_planner(
        cls,
        settings: Settings,
    ) -> QueryPlanner | None:
        """Build the default Gemini-backed query planner."""

        client = cls._build_generation_client(settings)

        if client is None:
            return None

        return GenerativeQueryPlanner(client)

    @classmethod
    def _build_gemini_investigator(
        cls,
        settings: Settings,
    ) -> Investigator | None:
        """Build the default Gemini-backed analytical investigator."""

        client = cls._build_generation_client(settings)

        if client is None:
            return None

        return GenerativeInvestigator(client)

    @classmethod
    def _build_gemini_synthesizer(
        cls,
        settings: Settings,
    ) -> InvestigationSynthesizer | None:
        """Build the default Gemini-backed investigation synthesizer."""

        client = cls._build_generation_client(settings)

        if client is None:
            return None

        return GenerativeInvestigationSynthesizer(client)

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

        execution_service = AnalyticalExecutionService(
            dataset,
            max_result_rows=self._settings.max_query_result_rows,
            memory_limit_mb=self._settings.max_query_memory_mb,
            execution_timeout_seconds=self._settings.max_query_execution_seconds,
            temp_storage_limit_mb=self._settings.max_query_temp_storage_mb,
        )

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
            max_result_rows=self._settings.max_query_result_rows,
            memory_limit_mb=self._settings.max_query_memory_mb,
            execution_timeout_seconds=self._settings.max_query_execution_seconds,
            temp_storage_limit_mb=self._settings.max_query_temp_storage_mb,
        )

        return execution_service.ask(question)

    def investigate(
        self,
        paths: Iterable[str | Path],
        question: str,
        *,
        max_steps: int = 5,
    ) -> InvestigationResult:
        """Run a bounded autonomous investigation against dataset files."""

        dataset = self._dataset_loader.load(paths)

        analysis = self._dataset_analyzer.analyze(dataset)
        analysis_result = self._result_builder.build(analysis)

        planner = self._planner

        if planner is None:
            planner = self._build_gemini_planner(self._settings)

        investigator = self._investigator

        if investigator is None:
            investigator = self._build_gemini_investigator(self._settings)

        if investigator is None:
            raise InvestigationError("No analytical investigator is configured.")

        synthesizer = self._synthesizer

        if synthesizer is None:
            synthesizer = self._build_gemini_synthesizer(self._settings)

        if synthesizer is None:
            raise InvestigationError("No investigation synthesizer is configured.")

        execution_service = AnalyticalExecutionService(
            dataset,
            planner=planner,
            max_result_rows=self._settings.max_query_result_rows,
            memory_limit_mb=self._settings.max_query_memory_mb,
            execution_timeout_seconds=self._settings.max_query_execution_seconds,
            temp_storage_limit_mb=self._settings.max_query_temp_storage_mb,
        )

        orchestrator = InvestigationOrchestrator(
            execution_service=execution_service,
            investigator=investigator,
            synthesizer=synthesizer,
            max_steps=max_steps,
        )

        return orchestrator.investigate(
            question=question,
            analysis=analysis_result,
        )
