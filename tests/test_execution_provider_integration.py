"""Integration tests for provider failures across execution boundaries."""

from pathlib import Path

import pandas as pd
import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder, DatasetAnalysisResult
from verisight.error_reporting import ErrorCode
from verisight.execution.decisions import (
    InvestigationAction,
    InvestigationDecision,
)
from verisight.execution.exceptions import QueryPlanningError
from verisight.execution.gemini import GeminiGenerationError, GeminiTransientError
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.generative_investigator import GenerativeInvestigator
from verisight.execution.generative_repair import GenerativeQueryRepairer
from verisight.execution.generative_synthesis import (
    GenerativeInvestigationSynthesizer,
)
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_result import InvestigationStatus
from verisight.execution.orchestration import InvestigationOrchestrator
from verisight.execution.service import AnalyticalExecutionService
from verisight.ingestion.models import (
    LoadedDataset,
    LoadedTable,
    SourceMetadata,
)
from verisight.ingestion.schema import SchemaInferer
from verisight.profiling.models import DatasetProfile
from verisight.public_api import run_public_operation


class FailingGenerationClient:
    """Simulate a provider failure at the text-generation boundary."""

    def __init__(self, error: GeminiGenerationError) -> None:
        self.error = error
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        raise self.error


class StaticGenerationClient:
    """Return deterministic SQL or a structured investigation response."""

    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


class SingleQuestionInvestigator:
    """Request one analytical query, then finish after an attempt."""

    def __init__(self, question: str) -> None:
        self.question = question
        self.states: list[InvestigationState] = []

    def decide(self, state: InvestigationState) -> InvestigationDecision:
        self.states.append(state)

        if state.observation_count or state.failed_attempt_count:
            return InvestigationDecision(
                action=InvestigationAction.FINISH,
                reasoning="Investigation attempt completed.",
            )

        return InvestigationDecision(
            action=InvestigationAction.INVESTIGATE,
            reasoning="Analytical evidence is required.",
            question=self.question,
        )


class RecordingSynthesizer:
    """Record whether investigation synthesis was attempted."""

    def __init__(self) -> None:
        self.states: list[InvestigationState] = []

    def synthesize(self, state: InvestigationState) -> str:
        self.states.append(state)
        return "Investigation completed."


def _dataset() -> LoadedDataset:
    source = SourceMetadata(
        path=Path("observations.csv"),
        file_name="observations.csv",
        file_extension=".csv",
        file_size_bytes=1,
    )

    table = LoadedTable(
        name="Observations",
        data=pd.DataFrame(
            {
                "category": ["A", "B", "A"],
                "value": [10.0, 20.0, 30.0],
            }
        ),
        source=source,
    )
    table.relation_name = "observations"

    return LoadedDataset(tables=[table])


def _analysis(dataset: LoadedDataset) -> DatasetAnalysisResult:
    return AnalysisResultBuilder().build(
        DatasetAnalysis(
            schema=SchemaInferer().infer_dataset(dataset),
            profile=DatasetProfile(tables=()),
            issues=(),
        )
    )


def test_provider_failure_during_planning_stops_investigation() -> None:
    """Permanent provider failures preserve the established planner wrapper."""

    dataset = _dataset()
    provider_error = GeminiGenerationError("Provider unavailable.")
    generation_client = FailingGenerationClient(provider_error)

    execution_service = AnalyticalExecutionService(
        dataset,
        planner=GenerativeQueryPlanner(generation_client),
    )

    investigator = SingleQuestionInvestigator("Count available records.")
    synthesizer = RecordingSynthesizer()

    orchestrator = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
        max_steps=3,
    )

    with pytest.raises(
        QueryPlanningError,
        match="Query planner text generation failed.",
    ) as exc_info:
        orchestrator.investigate(
            question="Investigate the available data.",
            analysis=_analysis(dataset),
        )

    assert exc_info.value.__cause__ is provider_error
    assert len(generation_client.prompts) == 1
    assert len(investigator.states) == 1
    assert investigator.states[0].failed_attempt_count == 0
    assert investigator.states[0].observation_count == 0
    assert synthesizer.states == []


def test_provider_failure_during_repair_stops_investigation() -> None:
    """Permanent repair failures preserve the established planner wrapper."""

    dataset = _dataset()
    provider_error = GeminiGenerationError("Provider unavailable.")

    planner_client = StaticGenerationClient("SELECT missing_metric FROM observations")
    repair_client = FailingGenerationClient(provider_error)

    execution_service = AnalyticalExecutionService(
        dataset,
        planner=GenerativeQueryPlanner(planner_client),
        repairer=GenerativeQueryRepairer(repair_client),
    )

    investigator = SingleQuestionInvestigator("Calculate the unavailable metric.")
    synthesizer = RecordingSynthesizer()

    orchestrator = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
        max_steps=3,
    )

    with pytest.raises(
        QueryPlanningError,
        match="Query repairer text generation failed.",
    ) as exc_info:
        orchestrator.investigate(
            question="Investigate the available data.",
            analysis=_analysis(dataset),
        )

    assert exc_info.value.__cause__ is provider_error
    assert len(planner_client.prompts) == 1
    assert len(repair_client.prompts) == 1
    assert len(investigator.states) == 1
    assert investigator.states[0].failed_attempt_count == 0
    assert investigator.states[0].observation_count == 0
    assert synthesizer.states == []


def test_successful_generation_executes_real_sql() -> None:
    """Successful generated SQL executes against a real synthetic dataset."""

    dataset = _dataset()
    generation_client = StaticGenerationClient(
        "SELECT COUNT(*) AS record_count FROM observations"
    )

    execution_service = AnalyticalExecutionService(
        dataset,
        planner=GenerativeQueryPlanner(generation_client),
    )

    investigator = SingleQuestionInvestigator("Count available records.")
    synthesizer = RecordingSynthesizer()

    result = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=investigator,
        synthesizer=synthesizer,
        max_steps=1,
    ).investigate(
        question="Investigate the available data.",
        analysis=_analysis(dataset),
    )

    assert len(generation_client.prompts) == 1
    assert result.observation_count == 1
    assert result.observations[0].sql == (
        "SELECT COUNT(*) AS record_count FROM observations"
    )
    assert result.observations[0].result.rows == ((3,),)
    assert result.conclusion == "Investigation completed."
    assert len(synthesizer.states) == 1
    assert synthesizer.states[0].failed_attempt_count == 0


def test_transient_planning_failure_reaches_public_boundary() -> None:
    """A temporary planning outage must not become an analytical failure."""

    dataset = _dataset()
    provider_error = GeminiTransientError("Sensitive provider details.")
    generation_client = FailingGenerationClient(provider_error)

    investigator = SingleQuestionInvestigator("Count available records.")
    synthesizer = RecordingSynthesizer()

    orchestrator = InvestigationOrchestrator(
        execution_service=AnalyticalExecutionService(
            dataset,
            planner=GenerativeQueryPlanner(generation_client),
        ),
        investigator=investigator,
        synthesizer=synthesizer,
        max_steps=3,
    )

    result = run_public_operation(
        lambda: orchestrator.investigate(
            question="Investigate the available data.",
            analysis=_analysis(dataset),
        )
    )

    assert result.succeeded is False
    assert result.value is None
    assert result.error is not None
    assert result.error.code is ErrorCode.PROVIDER_UNAVAILABLE
    assert result.error.message == "The AI provider is temporarily unavailable."
    assert "Sensitive provider details." not in repr(result)

    assert len(generation_client.prompts) == 1
    assert len(investigator.states) == 1
    assert investigator.states[0].failed_attempt_count == 0
    assert investigator.states[0].observation_count == 0
    assert synthesizer.states == []


def test_transient_repair_failure_reaches_public_boundary() -> None:
    """A temporary repair outage must not be recorded as a failed query."""

    dataset = _dataset()
    provider_error = GeminiTransientError("Sensitive repair provider details.")

    planner_client = StaticGenerationClient("SELECT missing_metric FROM observations")
    repair_client = FailingGenerationClient(provider_error)

    investigator = SingleQuestionInvestigator("Calculate the unavailable metric.")
    synthesizer = RecordingSynthesizer()

    orchestrator = InvestigationOrchestrator(
        execution_service=AnalyticalExecutionService(
            dataset,
            planner=GenerativeQueryPlanner(planner_client),
            repairer=GenerativeQueryRepairer(repair_client),
        ),
        investigator=investigator,
        synthesizer=synthesizer,
        max_steps=3,
    )

    result = run_public_operation(
        lambda: orchestrator.investigate(
            question="Investigate the available data.",
            analysis=_analysis(dataset),
        )
    )

    assert result.succeeded is False
    assert result.value is None
    assert result.error is not None
    assert result.error.code is ErrorCode.PROVIDER_UNAVAILABLE
    assert result.error.message == "The AI provider is temporarily unavailable."
    assert "Sensitive repair provider details." not in repr(result)

    assert len(planner_client.prompts) == 1
    assert len(repair_client.prompts) == 1
    assert len(investigator.states) == 1
    assert investigator.states[0].failed_attempt_count == 0
    assert investigator.states[0].observation_count == 0
    assert synthesizer.states == []


def test_transient_investigator_failure_reaches_public_boundary() -> None:
    """A transient decision-generation outage must propagate unchanged."""

    dataset = _dataset()
    provider_error = GeminiTransientError("Sensitive investigator provider details.")
    investigator_client = FailingGenerationClient(provider_error)

    planner_client = StaticGenerationClient(
        "SELECT COUNT(*) AS record_count FROM observations"
    )
    synthesizer = RecordingSynthesizer()

    orchestrator = InvestigationOrchestrator(
        execution_service=AnalyticalExecutionService(
            dataset,
            planner=GenerativeQueryPlanner(planner_client),
        ),
        investigator=GenerativeInvestigator(investigator_client),
        synthesizer=synthesizer,
        max_steps=3,
    )

    result = run_public_operation(
        lambda: orchestrator.investigate(
            question="Investigate the available data.",
            analysis=_analysis(dataset),
        )
    )

    assert result.succeeded is False
    assert result.value is None
    assert result.error is not None
    assert result.error.code is ErrorCode.PROVIDER_UNAVAILABLE
    assert result.error.message == "The AI provider is temporarily unavailable."
    assert "Sensitive investigator provider details." not in repr(result)

    assert len(investigator_client.prompts) == 1
    assert planner_client.prompts == []
    assert synthesizer.states == []


def test_transient_synthesis_failure_returns_incomplete_public_value() -> None:
    """A synthesis outage preserves successful SQL evidence in an incomplete value."""

    dataset = _dataset()

    planner_client = StaticGenerationClient(
        "SELECT COUNT(*) AS record_count FROM observations"
    )
    synthesis_error = GeminiTransientError("Sensitive synthesis provider details.")
    synthesis_client = FailingGenerationClient(synthesis_error)

    investigator = SingleQuestionInvestigator("Count available records.")

    orchestrator = InvestigationOrchestrator(
        execution_service=AnalyticalExecutionService(
            dataset,
            planner=GenerativeQueryPlanner(planner_client),
        ),
        investigator=investigator,
        synthesizer=GenerativeInvestigationSynthesizer(synthesis_client),
        max_steps=3,
    )

    result = run_public_operation(
        lambda: orchestrator.investigate(
            question="Investigate the available data.",
            analysis=_analysis(dataset),
        )
    )

    assert result.succeeded is True
    assert result.error is None
    assert result.value is not None
    assert result.value.status is InvestigationStatus.INCOMPLETE
    assert result.value.observation_count == 1
    assert result.value.observations[0].result.rows == ((3,),)
    assert "final synthesis could not be completed" in result.value.conclusion
    assert "Sensitive synthesis provider details." not in repr(result)

    assert len(planner_client.prompts) == 1
    assert len(synthesis_client.prompts) == 1
    assert len(investigator.states) == 2
    assert investigator.states[1].observation_count == 1
    assert investigator.states[1].failed_attempt_count == 0


@pytest.mark.parametrize("seconds", [0.0, -1.0, float("nan"), float("inf")])
def test_rejects_invalid_investigation_time_budgets(seconds: float) -> None:
    from pydantic import ValidationError

    from verisight.config import Settings
    from verisight.execution.deadline import investigation_deadline

    with pytest.raises(ValidationError):
        Settings(max_investigation_seconds=seconds)
    with (
        pytest.raises(ValueError, match="finite and positive"),
        investigation_deadline(seconds),
    ):
        pytest.fail("Invalid deadline was accepted")
    with pytest.raises(ValueError, match="finite and positive"):
        InvestigationOrchestrator(
            execution_service=AnalyticalExecutionService(_dataset()),
            investigator=SingleQuestionInvestigator("Count"),
            synthesizer=RecordingSynthesizer(),
            timeout_seconds=seconds,
        )


def test_nested_deadlines_restore_the_enclosing_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from verisight.execution.deadline import (
        InvestigationDeadlineExceeded,
        investigation_deadline,
        remaining_seconds,
    )

    clock = [100.0]
    monkeypatch.setattr("verisight.execution.deadline.monotonic", lambda: clock[0])
    with investigation_deadline(10):
        assert remaining_seconds(30) == 10
        with investigation_deadline(100):
            assert remaining_seconds(30) == 10
        with investigation_deadline(2):
            clock[0] += 3
            with pytest.raises(InvestigationDeadlineExceeded):
                remaining_seconds(30)
        assert remaining_seconds(30) == 7
    assert remaining_seconds(30) == 30


@pytest.mark.parametrize(
    "stage", ["decision", "query", "finish", "synthesis", "repair"]
)
def test_shared_deadline_preserves_state_and_stops_later_stages(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    from unittest.mock import Mock

    from verisight.execution.deadline import check_deadline

    clock = [0.0]
    monkeypatch.setattr("verisight.execution.deadline.monotonic", lambda: clock[0])
    dataset = _dataset()
    investigator = SingleQuestionInvestigator("Count records")
    decide = investigator.decide
    decisions = Mock()

    def decide_with_expiry(state: InvestigationState) -> InvestigationDecision:
        decision = decide(state)
        if stage == "decision" or (stage == "finish" and state.observation_count):
            clock[0] = 11
        return decision

    decisions.decide.side_effect = decide_with_expiry
    planner = StaticGenerationClient(
        "SELECT absent FROM observations"
        if stage == "repair"
        else "SELECT COUNT(*) AS total FROM observations"
    )
    repair = Mock()

    def expire_repair(request: object) -> None:
        clock[0] = 11
        check_deadline()

    repair.repair.side_effect = expire_repair
    service = AnalyticalExecutionService(
        dataset, planner=GenerativeQueryPlanner(planner), repairer=repair
    )
    run = service.run

    def run_with_expiry(
        question: str, *, original_question: str | None = None
    ) -> object:
        execution = run(question, original_question=original_question)
        if stage == "query":
            clock[0] = 11
        return execution

    execution_service = Mock()
    execution_service.run.side_effect = run_with_expiry
    synthesizer = RecordingSynthesizer()
    synthesize = synthesizer.synthesize
    synthesis = Mock()

    def synthesize_with_expiry(state: InvestigationState) -> str:
        text = synthesize(state)
        if stage == "synthesis":
            clock[0] = 11
        return text

    synthesis.synthesize.side_effect = synthesize_with_expiry
    result = InvestigationOrchestrator(
        execution_service=execution_service,
        investigator=decisions,
        synthesizer=synthesis,
        max_steps=2 if stage == "finish" else 1,
        timeout_seconds=10,
    ).investigate(question="Count records", analysis=_analysis(dataset))

    assert result.status is InvestigationStatus.INCOMPLETE
    assert "investigation time budget was exhausted" in result.conclusion
    assert result.observation_count == (0 if stage in {"decision", "repair"} else 1)
    assert result.generated_claims == ()
    assert len(synthesizer.states) == (1 if stage == "synthesis" else 0)
    assert decisions.decide.call_count == (2 if stage == "finish" else 1)
    if stage == "repair":
        assert len(result.failed_attempts) == 1
        assert len(result.failed_attempts[0].repair_history) == 1
        assert result.failed_attempts[0].repair_history[0].outcome == "failed"


@pytest.mark.parametrize("expire_during", ["retry", "response"])
def test_generation_deadline_caps_retries_and_rejects_late_responses(
    monkeypatch: pytest.MonkeyPatch, expire_during: str
) -> None:
    from unittest.mock import Mock

    from verisight.execution.deadline import (
        InvestigationDeadlineExceeded,
        investigation_deadline,
    )
    from verisight.execution.gemini import GeminiTextGenerationClient
    from verisight.execution.generation_telemetry import capture_generation_calls

    clock = [0.0]
    monkeypatch.setattr("verisight.execution.deadline.monotonic", lambda: clock[0])
    sdk = Mock()

    def request(**kwargs: object) -> object:
        if expire_during == "response":
            clock[0] = 11
            return Mock(text="late answer")
        clock[0] = 9.5
        raise ConnectionError("synthetic provider detail")

    sdk.models.generate_content.side_effect = request
    delays: list[float] = []

    def sleep(seconds: float) -> None:
        delays.append(seconds)
        clock[0] += seconds

    client = GeminiTextGenerationClient(
        api_key="synthetic-key", model="test-model", client=sdk, sleep=sleep
    )
    with (
        capture_generation_calls() as calls,
        investigation_deadline(10),
        pytest.raises(InvestigationDeadlineExceeded) as caught,
    ):
        client.generate("Synthetic request")
    assert sdk.models.generate_content.call_count == 1
    assert delays == ([0.5] if expire_during == "retry" else [])
    assert calls[0].attempts == 1
    assert calls[0].returned_text is False
    assert caught.value.__context__ is None
    # Context restoration must allow another independent call.
    sdk.models.generate_content.side_effect = None
    sdk.models.generate_content.return_value.text = "fresh answer"
    assert client.generate("Independent request") == "fresh answer"


def test_investigation_deadline_cancels_sdk_worker_and_closes_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import asyncio
    from unittest.mock import AsyncMock, Mock, patch

    from verisight.execution.deadline import (
        InvestigationDeadlineExceeded,
        investigation_deadline,
    )
    from verisight.execution.gemini import GeminiTextGenerationClient

    # Force the outer clock to remain before expiry even when the event-loop
    # timer fires. This reproduces an early timer wakeup deterministically.
    monkeypatch.setattr("verisight.execution.deadline.monotonic", lambda: 0.0)
    cancelled = False

    async def slow_response(**kwargs: object) -> object:
        nonlocal cancelled
        try:
            await asyncio.sleep(5)
        finally:
            cancelled = True
        return Mock(text="late answer")

    with patch("verisight.execution.gemini.genai.Client") as factory:
        sdk = factory.return_value.__enter__.return_value
        async_sdk = sdk.aio.__aenter__.return_value
        async_sdk.models.generate_content = AsyncMock(side_effect=slow_response)
        client = GeminiTextGenerationClient(
            api_key="synthetic-key",
            model="test-model",
            request_timeout_seconds=30,
            max_retries=5,
            sleep=Mock(),
        )
        with (
            investigation_deadline(0.1),
            pytest.raises(InvestigationDeadlineExceeded) as caught,
        ):
            client.generate("Synthetic request")
        assert cancelled
        assert factory.call_count == 1
        assert caught.value.__context__ is None
        sdk.aio.__aexit__.assert_awaited_once()
        factory.return_value.__exit__.assert_called_once()


def test_sdk_timeout_before_shared_timer_expiry_can_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock, Mock, patch

    from verisight.execution.deadline import investigation_deadline
    from verisight.execution.gemini import GeminiTextGenerationClient

    monkeypatch.setattr("verisight.execution.deadline.monotonic", lambda: 0.0)
    with patch("verisight.execution.gemini.genai.Client") as factory:
        sdk = factory.return_value.__enter__.return_value
        async_sdk = sdk.aio.__aenter__.return_value
        async_sdk.models.generate_content = AsyncMock(
            side_effect=[TimeoutError("synthetic provider detail"), Mock(text="ready")]
        )
        sleep = Mock()
        client = GeminiTextGenerationClient(
            api_key="synthetic-key",
            model="test-model",
            request_timeout_seconds=30,
            max_retries=1,
            sleep=sleep,
        )
        with investigation_deadline(10):
            assert client.generate("Synthetic request") == "ready"
        assert factory.call_count == 2
        assert async_sdk.models.generate_content.await_count == 2
        assert sdk.aio.__aexit__.await_count == 2
        assert factory.return_value.__exit__.call_count == 2
        sleep.assert_called_once_with(1.0)


def test_sql_uses_shared_budget_and_does_not_start_after_registration_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import patch

    from verisight.execution.deadline import (
        InvestigationDeadlineExceeded,
        investigation_deadline,
    )
    from verisight.execution.engine import DuckDBExecutor

    clock = [0.0]
    monkeypatch.setattr("verisight.execution.deadline.monotonic", lambda: clock[0])
    executor = DuckDBExecutor(execution_timeout_seconds=30)
    with investigation_deadline(5):
        with patch("verisight.execution.engine.Timer") as timer:
            assert executor.execute(_dataset(), "SELECT 1").rows == ((1,),)
        assert timer.call_args.args[0] == 5

    register = DuckDBExecutor._register_table

    def register_then_expire(connection: object, table: LoadedTable) -> None:
        register(connection, table)  # type: ignore[arg-type]
        clock[0] = 10

    with (
        patch.object(
            DuckDBExecutor, "_register_table", side_effect=register_then_expire
        ),
        investigation_deadline(5),
        pytest.raises(InvestigationDeadlineExceeded),
    ):
        executor.execute(_dataset(), "SELECT 1")


def test_facade_applies_configured_orchestration_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import Mock

    from verisight import VeriSight
    from verisight.config import Settings

    path = tmp_path / "observations.csv"
    path.write_text("value\n1\n", encoding="utf-8")
    clock = [0.0]
    monkeypatch.setattr("verisight.execution.deadline.monotonic", lambda: clock[0])
    investigator = Mock()

    def late_decision(state: InvestigationState) -> InvestigationDecision:
        clock[0] = 3
        return InvestigationDecision(
            action=InvestigationAction.FINISH, reasoning="Too late"
        )

    investigator.decide.side_effect = late_decision
    result = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False, max_investigation_seconds=2),
        planner=GenerativeQueryPlanner(StaticGenerationClient("SELECT 1")),
        investigator=investigator,
        synthesizer=RecordingSynthesizer(),
    ).investigate(path, "Count records")
    assert result.status is InvestigationStatus.INCOMPLETE
    assert "investigation time budget was exhausted" in result.conclusion
    assert result.observation_count == 0


def test_shared_deadline_interrupts_real_sql_without_repair() -> None:
    from unittest.mock import Mock

    from verisight.execution.deadline import (
        InvestigationDeadlineExceeded,
        investigation_deadline,
    )

    repair = Mock()
    service = AnalyticalExecutionService(
        _dataset(),
        planner=GenerativeQueryPlanner(
            StaticGenerationClient("SELECT SUM(SIN(i)) FROM range(10000000000) AS t(i)")
        ),
        repairer=repair,
        execution_timeout_seconds=30,
    )
    with (
        investigation_deadline(0.1),
        pytest.raises(InvestigationDeadlineExceeded),
    ):
        service.run("Synthetic bounded SQL test")
    repair.repair.assert_not_called()


@pytest.mark.parametrize(
    "investigation_seconds", [0.1, 40.0], ids=["shared-deadline", "query-timeout"]
)
def test_sql_interrupt_retains_the_timer_budget_source(
    monkeypatch: pytest.MonkeyPatch, investigation_seconds: float
) -> None:
    """Classify fired timers even before a clock recheck observes expiry."""
    from unittest.mock import MagicMock, patch

    import duckdb

    from verisight.execution.deadline import (
        InvestigationDeadlineExceeded,
        investigation_deadline,
    )
    from verisight.execution.engine import DuckDBExecutor
    from verisight.execution.exceptions import QueryTimeoutError

    monkeypatch.setattr("verisight.execution.deadline.monotonic", lambda: 0.0)
    executor = DuckDBExecutor(execution_timeout_seconds=30)
    connection = MagicMock()
    connection.execute.side_effect = duckdb.InterruptException("Synthetic interrupt")
    context = MagicMock()
    context.__enter__.return_value = connection
    expected_error = (
        InvestigationDeadlineExceeded
        if investigation_seconds < 30
        else QueryTimeoutError
    )

    from threading import Event

    finished = MagicMock()
    finished.wait.return_value = True
    with (
        patch.object(executor, "_connection", return_value=context),
        patch("verisight.execution.engine.Timer") as timer,
        patch("verisight.execution.engine.Event", side_effect=[Event(), finished]),
        investigation_deadline(investigation_seconds),
    ):

        def fire_timer() -> None:
            timer.call_args.args[1]()

        timer.return_value.start.side_effect = fire_timer
        with pytest.raises(expected_error) as caught:
            executor.execute(_dataset(), "SELECT 1")

    assert timer.call_args.args[0] == min(investigation_seconds, 30)
    connection.interrupt.assert_called_once_with()
    timer.return_value.cancel.assert_called_once_with()
    timer.return_value.join.assert_called_once_with()
    context.__exit__.assert_called_once()
    if investigation_seconds < 30:
        assert caught.value.__cause__ is None
        assert caught.value.__suppress_context__
    else:
        assert "30 seconds" in str(caught.value)


@pytest.mark.parametrize("repair", [False, True])
def test_scoped_investigation_enforces_population_and_preserves_provenance(
    tmp_path: Path, repair: bool
) -> None:
    import json
    from unittest.mock import patch

    from scripts.live_evaluation import CHALLENGE_CASES

    from verisight import VeriSight
    from verisight.config import Settings
    from verisight.execution.context import PopulationFilter
    from verisight.execution.investigation import FailedQueryAttempt
    from verisight.execution.investigation_compaction import InvestigationCompaction
    from verisight.serialization import to_jsonable

    case = CHALLENGE_CASES["education_entities"]
    paths = []
    for filename, content in case.files:
        path = tmp_path / filename
        path.write_text(content, encoding="utf-8")
        paths.append(path)
    population = (
        PopulationFilter("enrolments", "enrolment state", ("active",)),
        PopulationFilter("enrolments", "cohort", (2026,)),
        PopulationFilter("enrolments", "outcome", ("complete", "incomplete")),
    )
    # Omit every requested filter. The relation boundary must still enforce them.
    sql = (
        "SELECT 100.0 * COUNT(DISTINCT CASE WHEN outcome = 'complete' "
        'THEN "learner id" END) / COUNT(DISTINCT "learner id") '
        "AS metric FROM enrolments"
    )
    responses = [
        json.dumps(
            {
                "action": "investigate",
                "reasoning": "Measure",
                "question": "Count everyone",
            }
        ),
        "SELECT missing_metric FROM enrolments" if repair else sql,
    ]
    if repair:
        responses.append(sql)
    responses.extend(
        [
            json.dumps(
                {
                    "conclusion": "The completion percentage is 37.5.",
                    "claims": [
                        {
                            "operation": "value",
                            "expected": "37.5",
                            "left": {
                                "observation_index": 0,
                                "row_index": 0,
                                "column": "metric",
                            },
                            "right": None,
                        }
                    ],
                }
            ),
        ]
    )
    app = VeriSight(
        settings=Settings(gemini_api_key="offline-key", allow_llm_data_disclosure=True)
    )
    with patch(
        "verisight.execution.gemini.GeminiTextGenerationClient.generate",
        side_effect=responses,
    ) as generate:
        result = app.investigate(
            paths, case.question, max_steps=1, population=population
        )
    assert generate.call_count == 3 + int(repair)
    assert result.status is InvestigationStatus.COMPLETE
    assert result.population == population
    assert result.observations[0].result.rows == ((37.5,),)
    assert result.observations[0].sql == sql
    assert result.verified_claims[0].verification.status.value == "supported"
    assert len(result.observations[0].repair_history) == int(repair)
    serialized = to_jsonable(result)
    assert isinstance(serialized, dict)
    assert serialized["population"] == to_jsonable(population)
    for call in generate.call_args_list:
        assert "enrolment state" in call.args[0]
        assert "active" in call.args[0]
    state = InvestigationState(
        question=case.question, analysis=result.analysis, population=population
    )
    assert (
        "CALLER-ENFORCED RELATION POPULATION"
        in InvestigationCompaction().investigator_prompt(state)
    )
    failure = state.add_failed_attempt(
        FailedQueryAttempt("Fail", "QueryRuntimeError", "Failed")
    )
    assert failure.population == population
    incomplete = InvestigationOrchestrator._incomplete(failure)
    assert incomplete.population == population


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) FROM observations",
        "SELECT COUNT(*) FROM observations WHERE category = 'A' OR TRUE",
        "WITH people AS (SELECT * FROM observations) SELECT COUNT(*) FROM people",
        "SELECT COUNT(*) FROM observations a JOIN observations b ON a.value = b.value",
        "SELECT COUNT(*) FROM observations UNION ALL SELECT COUNT(*) FROM observations",
    ],
)
def test_relation_scope_survives_sql_shapes_without_source_mutation(sql: str) -> None:
    from verisight.execution.context import PopulationFilter
    from verisight.execution.engine import DuckDBExecutor

    dataset = _dataset()
    original = dataset.tables[0].data.copy(deep=True)
    executor = DuckDBExecutor(
        population=(PopulationFilter("observations", "category", ("A",)),)
    )
    result = executor.execute(dataset, sql)
    assert all(row == (2,) for row in result.rows)
    pd.testing.assert_frame_equal(dataset.tables[0].data, original)


@pytest.mark.parametrize(
    "relation,column,values",
    [
        ("missing", "category", ("A",)),
        ("observations", "missing", ("A",)),
        ("Observations", "category", ("A",)),
        ("observations", "value", ("10",)),
        ("observations", "value", (10,)),
        ("observations", "category", (True,)),
    ],
)
def test_invalid_population_is_rejected_before_planning(
    relation: str, column: str, values: tuple[str | int | bool, ...]
) -> None:
    from verisight.execution.context import PopulationFilter
    from verisight.execution.exceptions import QueryValidationError

    client = StaticGenerationClient("SELECT 1")
    with pytest.raises(QueryValidationError):
        AnalyticalExecutionService(
            _dataset(),
            planner=GenerativeQueryPlanner(client),
            population=(PopulationFilter(relation, column, values),),
        )
    assert client.prompts == []


def test_scope_handles_literal_identifiers_nulls_booleans_and_decimal_binding() -> None:
    from decimal import Decimal

    from verisight.execution.context import PopulationFilter
    from verisight.execution.engine import DuckDBExecutor
    from verisight.execution.exceptions import QueryValidationError

    dataset = _dataset()
    table = dataset.tables[0]
    table.data = pd.DataFrame(
        {
            'state."x': ["a' OR TRUE --", "other", None],
            "enabled": pd.Series([True, False, pd.NA], dtype="boolean"),
            "number": [1, 2, 3],
            "amount": [Decimal("0.123456789012345678"), Decimal("0.2"), Decimal("0.3")],
        }
    )
    population = (
        PopulationFilter("observations", 'state."x', ("a' OR TRUE --",)),
        PopulationFilter("observations", "enabled", (True,)),
        PopulationFilter("observations", "number", (1, 2)),
    )
    executor = DuckDBExecutor(population=population)
    assert executor.execute(dataset, "SELECT amount FROM observations").rows == (
        (Decimal("0.123456789012345678"),),
    )
    assert executor.execute(
        dataset, "SELECT COUNT(*) FROM observations WHERE enabled = false"
    ).rows == ((0,),)
    with pytest.raises(QueryValidationError):
        executor.execute(dataset, "SELECT * FROM duckdb_views()")
    # Revalidate mutable dataset identities and types on every execution.
    table.data = table.data.drop(columns=['state."x'])
    with pytest.raises(QueryValidationError):
        executor.execute(dataset, "SELECT COUNT(*) FROM observations")


def test_public_execute_and_ask_use_the_same_optional_scope(tmp_path: Path) -> None:
    from verisight import VeriSight
    from verisight.config import Settings
    from verisight.execution.context import PopulationFilter

    path = tmp_path / "observations.csv"
    path.write_text("category,value\nA,10\nB,20\nA,30\n", encoding="utf-8")
    client = StaticGenerationClient("SELECT COUNT(*) AS total FROM observations")
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False),
        planner=GenerativeQueryPlanner(client),
    )
    population = (PopulationFilter("observations", "category", ("A",)),)
    assert app.execute(
        path, "SELECT COUNT(*) FROM observations", population=population
    ).rows == ((2,),)
    assert app.ask(path, "Count rows", population=population).rows == ((2,),)
    assert "CALLER-ENFORCED RELATION POPULATION" in client.prompts[0]
    assert app.execute(path, "SELECT COUNT(*) FROM observations").rows == ((3,),)


def test_population_is_relation_specific_and_can_return_an_empty_population() -> None:
    from verisight.execution.context import PopulationFilter
    from verisight.execution.engine import DuckDBExecutor

    dataset = _dataset()
    table = dataset.tables[0]
    comparison = LoadedTable(
        name="comparison", data=table.data.copy(deep=True), source=table.source
    )
    dataset.tables.append(comparison)
    scoped = DuckDBExecutor(
        population=(PopulationFilter("observations", "category", ("A",)),)
    )
    assert scoped.execute(
        dataset,
        "SELECT (SELECT COUNT(*) FROM observations), (SELECT COUNT(*) FROM comparison)",
    ).rows == ((2, 3),)
    empty = DuckDBExecutor(
        population=(PopulationFilter("observations", "category", ("absent",)),)
    )
    assert empty.execute(dataset, "SELECT COUNT(*) FROM observations").rows == ((0,),)
