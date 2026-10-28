"""Public analysis and analytical execution facade for VeriSight."""

from collections.abc import Iterable, Mapping
from pathlib import Path

from verisight.analysis.result import (
    AnalysisResultBuilder,
    DatasetAnalysisResult,
)
from verisight.analysis.service import DatasetAnalyzer
from verisight.config import Settings
from verisight.execution.context import PopulationFilter
from verisight.execution.exceptions import (
    InvestigationError,
    QueryPlanningError,
)
from verisight.execution.gemini import GeminiTextGenerationClient
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.generative_investigator import (
    GenerativeInvestigator,
)
from verisight.execution.generative_repair import GenerativeQueryRepairer
from verisight.execution.investigation_parsing import (
    INVESTIGATION_DECISION_JSON_SCHEMA,
)
from verisight.execution.investigation_result import (
    ClaimOutputContract,
    InvestigationResult,
)
from verisight.execution.investigator import Investigator
from verisight.execution.models import QueryResult
from verisight.execution.orchestration import InvestigationOrchestrator
from verisight.execution.planning import QueryPlan, QueryPlanner
from verisight.execution.repair import QueryRepairer, QueryRepairRequest
from verisight.execution.service import AnalyticalExecutionService
from verisight.execution.structured_synthesis import (
    StructuredInvestigationSynthesizer,
)
from verisight.execution.synthesis import InvestigationSynthesizer
from verisight.ingestion.exceptions import FileValidationError
from verisight.ingestion.models import CsvReadOptions, LoadedDataset
from verisight.ingestion.service import DatasetLoader


class _LazyGeminiQueryRepairer:
    """Create a Gemini repairer only after a repair is requested."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._repairer: QueryRepairer | None = None

    def repair(self, request: QueryRepairRequest) -> QueryPlan:
        """Generate a repaired query using a lazily created client."""

        if self._repairer is None:
            client = VeriSight._build_generation_client(self._settings)

            if client is None:
                raise QueryPlanningError(
                    "Gemini SQL repair requires configured credentials "
                    "and explicit LLM data-disclosure permission."
                )

            self._repairer = GenerativeQueryRepairer(client)

        return self._repairer.repair(request)


class VeriSight:
    """Provide the public VeriSight analysis and execution workflows."""

    def __init__(
        self,
        settings: Settings | None = None,
        planner: QueryPlanner | None = None,
        investigator: Investigator | None = None,
        synthesizer: InvestigationSynthesizer | None = None,
        repairer: QueryRepairer | None = None,
        *,
        csv_options: Mapping[str | Path, CsvReadOptions] | None = None,
    ) -> None:
        """Initialize the VeriSight facade."""

        resolved_settings = settings if settings is not None else Settings()

        self._settings = resolved_settings
        self._dataset_loader = DatasetLoader(resolved_settings, csv_options=csv_options)
        self._dataset_analyzer = DatasetAnalyzer()
        self._result_builder = AnalysisResultBuilder()

        self._planner = planner
        self._investigator = investigator
        self._synthesizer = synthesizer
        self._repairer = repairer

        if self._planner is None:
            self._planner = self._build_gemini_planner(resolved_settings)

        if self._repairer is None and self._build_generation_available(
            resolved_settings
        ):
            self._repairer = _LazyGeminiQueryRepairer(resolved_settings)

    @staticmethod
    def _build_generation_available(settings: Settings) -> bool:
        """Check whether Gemini credentials and disclosure permission exist."""

        api_key = settings.gemini_api_key

        return (
            settings.allow_llm_data_disclosure
            and api_key is not None
            and bool(api_key.strip())
        )

    @staticmethod
    def _build_generation_client(
        settings: Settings,
        *,
        response_json_schema: dict[str, object] | None = None,
    ) -> GeminiTextGenerationClient | None:
        """Build a Gemini generation client when credentials are configured."""

        if not VeriSight._build_generation_available(settings):
            return None

        api_key = settings.gemini_api_key
        assert api_key is not None

        return GeminiTextGenerationClient(
            api_key=api_key,
            model=settings.gemini_model,
            request_timeout_seconds=settings.gemini_request_timeout_seconds,
            max_retries=settings.gemini_max_retries,
            retry_base_delay_seconds=settings.gemini_retry_base_delay_seconds,
            response_json_schema=response_json_schema,
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

        client = cls._build_generation_client(
            settings,
            response_json_schema=INVESTIGATION_DECISION_JSON_SCHEMA,
        )

        if client is None:
            return None

        return GenerativeInvestigator(client)

    @classmethod
    def _build_gemini_synthesizer(
        cls,
        settings: Settings,
    ) -> InvestigationSynthesizer | None:
        """Build the default Gemini-backed structured synthesizer."""

        if not cls._build_generation_available(settings):
            return None

        return StructuredInvestigationSynthesizer.from_settings(settings)

    def _load_dataset(
        self,
        paths: str | Path | Iterable[str | Path],
    ) -> LoadedDataset:
        """Normalize public path inputs and require at least one file path."""

        normalized: tuple[str | Path, ...]

        if isinstance(paths, (str, Path)):
            normalized = (paths,)
        else:
            try:
                path_iterator = iter(paths)
            except TypeError as exc:
                raise FileValidationError(
                    "Dataset input must be a file path or an iterable of file paths."
                ) from exc

            normalized = tuple(path_iterator)

        if not normalized:
            raise FileValidationError("At least one dataset file path is required.")

        if any(isinstance(path, str) and not path.strip() for path in normalized):
            raise FileValidationError("Dataset file paths must not be blank.")

        return self._dataset_loader.load(normalized)

    def analyze(
        self,
        paths: str | Path | Iterable[str | Path],
    ) -> DatasetAnalysisResult:
        """Load and analyze one or more dataset files."""

        dataset = self._load_dataset(paths)
        analysis = self._dataset_analyzer.analyze(dataset)

        return self._result_builder.build(analysis)

    def execute(
        self,
        paths: str | Path | Iterable[str | Path],
        query: str,
        *,
        population: tuple[PopulationFilter, ...] = (),
    ) -> QueryResult:
        """Execute a read-only analytical query against dataset files."""

        dataset = self._load_dataset(paths)

        execution_service = AnalyticalExecutionService(
            dataset,
            max_result_rows=self._settings.max_query_result_rows,
            max_result_bytes=self._settings.max_query_result_bytes,
            memory_limit_mb=self._settings.max_query_memory_mb,
            execution_timeout_seconds=self._settings.max_query_execution_seconds,
            temp_storage_limit_mb=self._settings.max_query_temp_storage_mb,
            population=population,
        )

        return execution_service.execute(query)

    def ask(
        self,
        paths: str | Path | Iterable[str | Path],
        question: str,
        *,
        population: tuple[PopulationFilter, ...] = (),
    ) -> QueryResult:
        """Answer a natural-language analytical question against dataset files."""

        dataset = self._load_dataset(paths)

        execution_service = AnalyticalExecutionService(
            dataset,
            planner=self._planner,
            repairer=self._repairer,
            max_result_rows=self._settings.max_query_result_rows,
            max_result_bytes=self._settings.max_query_result_bytes,
            memory_limit_mb=self._settings.max_query_memory_mb,
            execution_timeout_seconds=self._settings.max_query_execution_seconds,
            temp_storage_limit_mb=self._settings.max_query_temp_storage_mb,
            population=population,
        )

        return execution_service.ask(question)

    def investigate(
        self,
        paths: str | Path | Iterable[str | Path],
        question: str,
        *,
        max_steps: int = 5,
        population: tuple[PopulationFilter, ...] = (),
        claim_output_contract: ClaimOutputContract | None = None,
    ) -> InvestigationResult:
        """Run a bounded autonomous investigation against dataset files."""

        dataset = self._load_dataset(paths)

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
            repairer=self._repairer,
            max_result_rows=self._settings.max_query_result_rows,
            max_result_bytes=self._settings.max_query_result_bytes,
            memory_limit_mb=self._settings.max_query_memory_mb,
            execution_timeout_seconds=self._settings.max_query_execution_seconds,
            temp_storage_limit_mb=self._settings.max_query_temp_storage_mb,
            population=population,
        )

        orchestrator = InvestigationOrchestrator(
            execution_service=execution_service,
            investigator=investigator,
            synthesizer=synthesizer,
            max_steps=max_steps,
            timeout_seconds=self._settings.max_investigation_seconds,
            population=population,
            claim_output_contract=claim_output_contract,
        )

        return orchestrator.investigate(
            question=question,
            analysis=analysis_result,
        )
