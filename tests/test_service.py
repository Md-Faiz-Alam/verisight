from collections.abc import Callable, Iterable
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from verisight.analysis.result import DatasetAnalysisResult
from verisight.config import Settings
from verisight.error_reporting import to_public_error
from verisight.execution.claim_verification import VerificationStatus
from verisight.execution.decisions import (
    InvestigationAction,
    InvestigationDecision,
)
from verisight.execution.exceptions import (
    InvestigationError,
    QueryExecutionError,
    QueryPlanningError,
    QueryRuntimeError,
    QueryValidationError,
)
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_parsing import (
    INVESTIGATION_DECISION_JSON_SCHEMA,
)
from verisight.execution.investigation_result import (
    InvestigationResult,
    InvestigationStatus,
)
from verisight.execution.planning import QueryPlan, QueryRequest
from verisight.execution.repair import QueryRepairRequest
from verisight.ingestion.exceptions import FileValidationError
from verisight.service import VeriSight, _LazyGeminiQueryRepairer


class StubQueryPlanner:
    """Query planner used by public service integration tests."""

    def plan(self, request: QueryRequest) -> QueryPlan:
        return QueryPlan(
            question=request.question,
            sql="""
            SELECT
                COUNT(*) AS order_count,
                SUM(amount) AS total_amount
            FROM orders
            """,
        )


class StubInvestigator:
    """Deterministic investigator used by public service tests."""

    def __init__(
        self,
        decisions: list[InvestigationDecision],
    ) -> None:
        self._decisions = decisions
        self.states: list[InvestigationState] = []

    def decide(
        self,
        state: InvestigationState,
    ) -> InvestigationDecision:
        self.states.append(state)

        return self._decisions[len(self.states) - 1]


class StubInvestigationSynthesizer:
    """Deterministic synthesizer used by public service tests."""

    def __init__(
        self,
        conclusion: str = "Synthesized analytical conclusion.",
    ) -> None:
        self.conclusion = conclusion
        self.states: list[InvestigationState] = []

    def synthesize(
        self,
        state: InvestigationState,
    ) -> str:
        self.states.append(state)

        return self.conclusion


@pytest.mark.parametrize(
    "path_factory",
    [str, Path, lambda path: [path], lambda path: (path,), lambda path: iter([path])],
    ids=["string", "path", "list", "tuple", "iterator"],
)
def test_analyzes_single_csv_file(
    tmp_path: Path,
    path_factory: Callable[[Path], str | Path | Iterable[str | Path]],
) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [10.0, 20.0, 30.0],
        }
    ).to_csv(path, index=False)

    result = VeriSight().analyze(path_factory(path))

    assert isinstance(result, DatasetAnalysisResult)
    assert result.analysis.schema.table_count == 1
    assert result.analysis.profile.table_count == 1

    table_schema = result.analysis.schema.tables[0]
    table_profile = result.analysis.profile.tables[0]

    assert table_schema.name == "orders"
    assert table_profile.name == "orders"
    assert table_schema.relation_name == "orders"
    assert table_profile.relation_name == "orders"


def test_analyzes_multiple_files(tmp_path: Path) -> None:
    customers_path = tmp_path / "customers.csv"
    orders_path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "customer_id": [1, 2],
            "name": ["Alice", "Bob"],
        }
    ).to_csv(customers_path, index=False)

    pd.DataFrame(
        {
            "order_id": [10, 20],
            "customer_id": [1, 2],
        }
    ).to_csv(orders_path, index=False)

    result = VeriSight().analyze(
        [
            customers_path,
            orders_path,
        ]
    )

    assert result.analysis.schema.table_count == 2
    assert result.analysis.profile.table_count == 2

    assert tuple(table.relation_name for table in result.analysis.schema.tables) == (
        "customers",
        "orders",
    )

    assert tuple(table.relation_name for table in result.analysis.profile.tables) == (
        "customers",
        "orders",
    )


def test_analyze_builds_summary_and_insights(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "status": ["open", "open", "closed"],
        }
    ).to_csv(path, index=False)

    result = VeriSight().analyze([path])

    assert result.summary.table_count == 1
    assert result.insight_count == len(result.insights)


def test_analyze_preserves_quality_issues(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [10.0, None, 30.0],
        }
    ).to_csv(path, index=False)

    result = VeriSight().analyze([path])

    assert result.issue_count > 0
    assert result.issue_count == len(result.analysis.issues)


def test_analyzes_with_explicit_settings(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
        }
    ).to_csv(path, index=False)

    service = VeriSight(Settings())

    result = service.analyze([path])

    assert result.analysis.schema.table_count == 1
    assert result.analysis.profile.table_count == 1


@pytest.mark.parametrize("operation", ["analyze", "execute", "ask", "investigate"])
@pytest.mark.parametrize(
    "paths_factory",
    [list, tuple, lambda: iter(())],
    ids=["list", "tuple", "iterator"],
)
def test_public_operations_reject_empty_input(
    operation: str,
    paths_factory: Callable[[], Iterable[str | Path]],
) -> None:
    service = VeriSight(settings=Settings(allow_llm_data_disclosure=False))
    paths = paths_factory()
    operations: dict[str, Callable[[], object]] = {
        "analyze": lambda: service.analyze(paths),
        "execute": lambda: service.execute(paths, "SELECT 1"),
        "ask": lambda: service.ask(paths, "Count the rows."),
        "investigate": lambda: service.investigate(paths, "Inspect the data."),
    }

    with pytest.raises(
        FileValidationError,
        match="At least one dataset file path is required",
    ):
        operations[operation]()


@pytest.mark.parametrize("paths", ["", "   ", ["missing.csv", ""]])
def test_public_analyze_rejects_blank_paths_before_loading(
    paths: str | list[str],
) -> None:
    service = VeriSight(settings=Settings(allow_llm_data_disclosure=False))

    with pytest.raises(
        FileValidationError, match="Dataset file paths must not be blank"
    ):
        service.analyze(paths)


def test_verisight_is_available_from_package_root() -> None:
    from verisight import VeriSight as PublicVeriSight

    assert PublicVeriSight is VeriSight


@pytest.mark.parametrize(
    "path_factory",
    [str, Path, lambda path: [path], lambda path: (path,), lambda path: iter([path])],
    ids=["string", "path", "list", "tuple", "iterator"],
)
def test_executes_query_against_single_csv_file(
    tmp_path: Path,
    path_factory: Callable[[Path], str | Path | Iterable[str | Path]],
) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [10.0, 20.0, 30.0],
        }
    ).to_csv(path, index=False)

    result = VeriSight().execute(
        path_factory(path),
        """
        SELECT order_id, amount
        FROM orders
        WHERE amount >= 20
        ORDER BY order_id
        """,
    )

    assert result.columns == (
        "order_id",
        "amount",
    )
    assert result.rows == (
        (2, 20.0),
        (3, 30.0),
    )


def test_executes_query_across_multiple_files(tmp_path: Path) -> None:
    customers_path = tmp_path / "customers.csv"
    orders_path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "customer_id": [1, 2],
            "name": ["Alice", "Bob"],
        }
    ).to_csv(customers_path, index=False)

    pd.DataFrame(
        {
            "order_id": [10, 20, 30],
            "customer_id": [1, 1, 2],
            "amount": [10.0, 20.0, 50.0],
        }
    ).to_csv(orders_path, index=False)

    result = VeriSight().execute(
        [
            customers_path,
            orders_path,
        ],
        """
        SELECT
            customers.name,
            SUM(orders.amount) AS total_amount
        FROM customers
        JOIN orders
            ON customers.customer_id = orders.customer_id
        GROUP BY customers.name
        ORDER BY customers.name
        """,
    )

    assert result.columns == (
        "name",
        "total_amount",
    )
    assert result.rows == (
        ("Alice", 30.0),
        ("Bob", 50.0),
    )


@pytest.mark.parametrize(
    "path_factory",
    [str, Path, lambda path: [path], lambda path: (path,), lambda path: iter([path])],
    ids=["string", "path", "list", "tuple", "iterator"],
)
def test_asks_natural_language_question_against_csv_file(
    tmp_path: Path,
    path_factory: Callable[[Path], str | Path | Iterable[str | Path]],
) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [10.0, 20.0, 30.0],
        }
    ).to_csv(path, index=False)

    result = VeriSight(planner=StubQueryPlanner()).ask(
        path_factory(path),
        "How many orders are there and what is the total amount?",
    )

    assert result.columns == (
        "order_count",
        "total_amount",
    )
    assert result.rows == ((3, 60.0),)


def test_ask_requires_configured_query_planner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
        }
    ).to_csv(path, index=False)

    settings = Settings(gemini_api_key=None)

    with pytest.raises(
        QueryPlanningError,
        match="No query planner is configured.",
    ):
        VeriSight(settings=settings).ask(
            [path],
            "How many orders are there?",
        )


def test_public_ask_preserves_safe_execution_validation(
    tmp_path: Path,
) -> None:
    class UnsafeQueryPlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql="DROP TABLE orders",
            )

    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
        }
    ).to_csv(path, index=False)

    with pytest.raises(
        QueryExecutionError,
        match="Only read-only analytical SELECT queries are allowed.",
    ):
        VeriSight(planner=UnsafeQueryPlanner()).ask(
            [path],
            "Delete the orders table.",
        )


def test_verisight_builds_gemini_planner_from_settings() -> None:
    settings = Settings(
        gemini_api_key="test-api-key",
        gemini_model="test-model",
        allow_llm_data_disclosure=True,
    )

    with patch("verisight.service.GeminiTextGenerationClient") as client_class:
        service = VeriSight(settings=settings)

    client_class.assert_called_once_with(
        api_key="test-api-key",
        model="test-model",
        request_timeout_seconds=30.0,
        max_retries=2,
        retry_base_delay_seconds=1.0,
        response_json_schema=None,
    )

    assert isinstance(service._planner, GenerativeQueryPlanner)


def test_explicit_planner_takes_precedence_over_gemini_settings() -> None:
    planner = StubQueryPlanner()

    settings = Settings(
        gemini_api_key="test-api-key",
        gemini_model="test-model",
    )

    with patch("verisight.service.GeminiTextGenerationClient") as client_class:
        service = VeriSight(
            settings=settings,
            planner=planner,
        )

    client_class.assert_not_called()
    assert service._planner is planner


def test_verisight_does_not_build_gemini_planner_without_api_key() -> None:
    settings = Settings(
        gemini_api_key=None,
    )

    with patch("verisight.service.GeminiTextGenerationClient") as client_class:
        service = VeriSight(settings=settings)

    client_class.assert_not_called()
    assert service._planner is None


def test_default_gemini_planner_can_answer_question(
    tmp_path: Path,
) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [10.0, 20.0, 30.0],
        }
    ).to_csv(path, index=False)

    generated_client = MagicMock()
    generated_client.generate.return_value = (
        "SELECT COUNT(*) AS order_count, SUM(amount) AS total_amount FROM orders"
    )

    settings = Settings(
        gemini_api_key="test-api-key",
        gemini_model="test-model",
        allow_llm_data_disclosure=True,
    )

    with patch(
        "verisight.service.GeminiTextGenerationClient",
        return_value=generated_client,
    ):
        result = VeriSight(settings=settings).ask(
            [path],
            "How many orders are there and what is the total amount?",
        )

    assert result.columns == (
        "order_count",
        "total_amount",
    )
    assert result.rows == ((3, 60.0),)

    generated_client.generate.assert_called_once()


@pytest.mark.parametrize(
    "path_factory",
    [str, Path, lambda path: [path], lambda path: (path,), lambda path: iter([path])],
    ids=["string", "path", "list", "tuple", "iterator"],
)
def test_public_investigate_runs_autonomous_analysis(
    tmp_path: Path,
    path_factory: Callable[[Path], str | Path | Iterable[str | Path]],
) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [10.0, 20.0, 30.0],
        }
    ).to_csv(path, index=False)

    investigator = StubInvestigator(
        [
            InvestigationDecision(
                action=InvestigationAction.INVESTIGATE,
                reasoning="The total order amount should be measured.",
                question="What is the total order amount?",
            ),
            InvestigationDecision(
                action=InvestigationAction.FINISH,
                reasoning="The executed observation is sufficient.",
            ),
        ]
    )

    synthesizer = StubInvestigationSynthesizer(
        conclusion=("There are three orders with a total observed amount of 60.")
    )

    service = VeriSight(
        planner=StubQueryPlanner(),
        investigator=investigator,
        synthesizer=synthesizer,
    )

    result = service.investigate(
        path_factory(path),
        "What can we learn about these orders?",
    )

    assert isinstance(result, InvestigationResult)
    assert result.question == "What can we learn about these orders?"
    assert result.conclusion == (
        "There are three orders with a total observed amount of 60."
    )
    assert result.observation_count == 1

    observation = result.observations[0]

    assert observation.question == "What is the total order amount?"
    assert observation.result.columns == (
        "order_count",
        "total_amount",
    )
    assert observation.result.rows == ((3, 60.0),)

    assert len(investigator.states) == 2
    assert investigator.states[0].observation_count == 0
    assert investigator.states[1].observation_count == 1

    assert len(synthesizer.states) == 1
    assert synthesizer.states[0].observation_count == 1


def test_public_investigate_can_finish_without_querying(
    tmp_path: Path,
) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [10.0, 20.0, 30.0],
        }
    ).to_csv(path, index=False)

    investigator = StubInvestigator(
        [
            InvestigationDecision(
                action=InvestigationAction.FINISH,
                reasoning="The deterministic analysis is sufficient.",
            )
        ]
    )

    synthesizer = StubInvestigationSynthesizer(
        conclusion="The deterministic analysis supports the conclusion."
    )

    result = VeriSight(
        planner=StubQueryPlanner(),
        investigator=investigator,
        synthesizer=synthesizer,
    ).investigate(
        [path],
        "Inspect the orders dataset.",
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.conclusion == (
        "Investigation incomplete: no analytical observations were collected. "
        "No analytical conclusion has been established."
    )
    assert result.observation_count == 0
    assert len(investigator.states) == 1
    assert synthesizer.states == []


def test_public_investigate_requires_configured_investigator(
    tmp_path: Path,
) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
        }
    ).to_csv(path, index=False)

    settings = Settings(gemini_api_key=None)

    with pytest.raises(
        InvestigationError,
        match="No analytical investigator is configured.",
    ):
        VeriSight(
            settings=settings,
            planner=StubQueryPlanner(),
            synthesizer=StubInvestigationSynthesizer(),
        ).investigate(
            [path],
            "Investigate the orders.",
        )


def test_public_investigate_requires_configured_synthesizer(
    tmp_path: Path,
) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
        }
    ).to_csv(path, index=False)

    investigator = StubInvestigator(
        [
            InvestigationDecision(
                action=InvestigationAction.FINISH,
                reasoning="The evidence is sufficient.",
            )
        ]
    )

    settings = Settings(gemini_api_key=None)

    with pytest.raises(
        InvestigationError,
        match="No investigation synthesizer is configured.",
    ):
        VeriSight(
            settings=settings,
            planner=StubQueryPlanner(),
            investigator=investigator,
        ).investigate(
            [path],
            "Investigate the orders.",
        )


def test_explicit_investigator_and_synthesizer_do_not_require_gemini(
    tmp_path: Path,
) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
        }
    ).to_csv(path, index=False)

    investigator = StubInvestigator(
        [
            InvestigationDecision(
                action=InvestigationAction.FINISH,
                reasoning="No further investigation is required.",
            )
        ]
    )

    synthesizer = StubInvestigationSynthesizer(
        conclusion="No additional analytical evidence is required."
    )

    settings = Settings(gemini_api_key=None)

    result = VeriSight(
        settings=settings,
        planner=StubQueryPlanner(),
        investigator=investigator,
        synthesizer=synthesizer,
    ).investigate(
        [path],
        "Inspect the orders.",
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.conclusion == (
        "Investigation incomplete: no analytical observations were collected. "
        "No analytical conclusion has been established."
    )
    assert result.observation_count == 0
    assert len(investigator.states) == 1
    assert synthesizer.states == []


def test_public_investigate_preserves_safe_execution_validation(
    tmp_path: Path,
) -> None:
    class UnsafeQueryPlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql="DROP TABLE orders",
            )

    path = tmp_path / "orders.csv"
    pd.DataFrame({"order_id": [1, 2, 3]}).to_csv(path, index=False)

    question = "Inspect the orders table."

    investigator = StubInvestigator(
        [
            InvestigationDecision(
                action=InvestigationAction.INVESTIGATE,
                reasoning="The orders table should be inspected.",
                question=question,
            ),
            InvestigationDecision(
                action=InvestigationAction.INVESTIGATE,
                reasoning="Retry the same analytical request.",
                question=question,
            ),
        ]
    )

    synthesizer = StubInvestigationSynthesizer()

    result = VeriSight(
        planner=UnsafeQueryPlanner(),
        investigator=investigator,
        synthesizer=synthesizer,
    ).investigate(
        [path],
        "Investigate the orders.",
    )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == 0
    assert "repeated an analytical question" in result.conclusion

    assert len(investigator.states) == 2

    failed_state = investigator.states[1]

    assert failed_state.failed_attempt_count == 1
    assert failed_state.failed_attempts[0].question == question
    assert failed_state.failed_attempts[0].error_type == "QueryValidationError"

    assert (
        failed_state.failed_attempts[0].message
        == to_public_error(
            QueryValidationError(
                "Only read-only analytical SELECT queries are allowed."
            )
        ).message
    )

    assert synthesizer.states == []


def test_public_investigate_builds_default_gemini_components(
    tmp_path: Path,
) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [10.0, 20.0, 30.0],
        }
    ).to_csv(path, index=False)

    planner = StubQueryPlanner()

    investigator_client = MagicMock()
    investigator_client.generate.return_value = (
        '{"action":"finish",'
        '"reasoning":"The deterministic evidence is sufficient.",'
        '"question":null}'
    )
    synthesizer_client = MagicMock()

    settings = Settings(
        gemini_api_key="test-api-key",
        gemini_model="test-model",
        allow_llm_data_disclosure=True,
    )

    with (
        patch(
            "verisight.service.GeminiTextGenerationClient",
            return_value=investigator_client,
        ) as investigator_class,
        patch(
            "verisight.execution.structured_synthesis.GeminiTextGenerationClient",
            return_value=synthesizer_client,
        ) as synthesizer_class,
    ):
        result = VeriSight(
            settings=settings,
            planner=planner,
        ).investigate(
            [path],
            "What can we learn about these orders?",
        )

    assert result.question == "What can we learn about these orders?"
    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.conclusion == (
        "Investigation incomplete: no analytical observations were collected. "
        "No analytical conclusion has been established."
    )
    assert result.observation_count == 0
    assert result.generated_claims == ()
    assert result.verified_claims == ()
    assert result.narrative_verified is False

    investigator_class.assert_called_once_with(
        api_key="test-api-key",
        model="test-model",
        request_timeout_seconds=30.0,
        max_retries=2,
        retry_base_delay_seconds=1.0,
        response_json_schema=INVESTIGATION_DECISION_JSON_SCHEMA,
    )
    synthesizer_class.assert_called_once()
    synthesis_config = synthesizer_class.call_args.kwargs
    assert synthesis_config["api_key"] == "test-api-key"
    assert synthesis_config["model"] == "test-model"
    assert synthesis_config["request_timeout_seconds"] == 30.0
    assert synthesis_config["max_retries"] == 2
    assert synthesis_config["retry_base_delay_seconds"] == 1.0
    schema = synthesis_config["response_json_schema"]
    assert isinstance(schema, dict)
    assert set(schema["required"]) == {"conclusion", "claims"}
    assert schema["additionalProperties"] is False

    investigator_client.generate.assert_called_once()
    synthesizer_client.generate.assert_not_called()

    investigator_prompt = investigator_client.generate.call_args.args[0]
    assert (
        "You are the autonomous analytical investigator for VeriSight."
        in investigator_prompt
    )
    assert "What can we learn about these orders?" in investigator_prompt


@pytest.mark.parametrize(
    ("expected", "reference_index", "status"),
    [
        ("60", 0, VerificationStatus.SUPPORTED),
        ("70", 0, VerificationStatus.CONTRADICTED),
        ("60", 9, VerificationStatus.UNVERIFIABLE),
    ],
)
def test_default_gemini_investigator_can_request_observe_and_synthesize(
    tmp_path: Path,
    expected: str,
    reference_index: int,
    status: VerificationStatus,
) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [10.0, 20.0, 30.0],
        }
    ).to_csv(path, index=False)

    planner = StubQueryPlanner()

    investigator_client = MagicMock()
    investigator_client.generate.side_effect = [
        (
            '{"action":"investigate",'
            '"reasoning":"The total amount should be measured.",'
            '"question":"What is the total order amount?"}'
        ),
        (
            '{"action":"finish",'
            '"reasoning":"The executed observation provides sufficient evidence.",'
            '"question":null}'
        ),
    ]

    synthesizer_client = MagicMock()
    synthesizer_client.generate.return_value = (
        '{"conclusion":"The dataset contains three orders totaling 60.",'
        '"claims":[{"operation":"value","expected":"'
        + expected
        + '","left":{"observation_index":'
        + str(reference_index)
        + ',"row_index":0,"column":"total_amount"},"right":null}]}'
    )

    settings = Settings(
        gemini_api_key="test-api-key",
        gemini_model="test-model",
        allow_llm_data_disclosure=True,
    )

    with (
        patch(
            "verisight.service.GeminiTextGenerationClient",
            return_value=investigator_client,
        ),
        patch(
            "verisight.execution.structured_synthesis.GeminiTextGenerationClient",
            return_value=synthesizer_client,
        ) as synthesizer_class,
    ):
        result = VeriSight(
            settings=settings,
            planner=planner,
        ).investigate(
            [path],
            "What can we learn about these orders?",
        )

    assert result.status is InvestigationStatus.COMPLETE
    assert result.conclusion == "The dataset contains three orders totaling 60."
    assert result.observation_count == 1
    assert len(result.generated_claims) == 1
    assert len(result.verified_claims) == 1
    assert result.verified_claims[0].verification.status is status
    assert result.narrative_verified is False
    assert result.verification_scope == "referenced_numeric_values_only"

    observation = result.observations[0]
    assert observation.question == "What is the total order amount?"
    assert observation.sql.strip() == (
        "SELECT\n"
        "                COUNT(*) AS order_count,\n"
        "                SUM(amount) AS total_amount\n"
        "            FROM orders"
    )
    assert observation.result.columns == ("order_count", "total_amount")
    assert observation.result.rows == ((3, 60.0),)

    assert investigator_client.generate.call_count == 2
    synthesizer_client.generate.assert_called_once()
    synthesizer_class.assert_called_once()
    assert synthesizer_class.call_args.kwargs["response_json_schema"] is not None

    first_prompt = investigator_client.generate.call_args_list[0].args[0]
    second_prompt = investigator_client.generate.call_args_list[1].args[0]
    synthesis_prompt = synthesizer_client.generate.call_args.args[0]
    assert "EXECUTED OBSERVATIONS\nNone" in first_prompt
    assert "EXECUTED OBSERVATIONS" in second_prompt
    assert "What is the total order amount?" in second_prompt
    assert "order_count" in second_prompt
    assert "total_amount" in second_prompt
    assert "VeriSight's structured investigation synthesizer" in synthesis_prompt
    assert "INVESTIGATION STATE:" in synthesis_prompt
    assert "What is the total order amount?" in synthesis_prompt
    assert "order_count" in synthesis_prompt
    assert "total_amount" in synthesis_prompt


def test_default_gemini_synthesis_rejects_plain_text(
    tmp_path: Path,
) -> None:
    path = tmp_path / "orders.csv"
    pd.DataFrame({"order_id": [1], "amount": [10.0]}).to_csv(path, index=False)
    investigator_client = MagicMock()
    investigator_client.generate.side_effect = [
        '{"action":"investigate","reasoning":"Measure data.",'
        '"question":"What is the total order amount?"}',
        '{"action":"finish","reasoning":"Evidence collected.","question":null}',
    ]
    synthesizer_client = MagicMock()
    synthesizer_client.generate.return_value = "Unstructured conclusion."

    with (
        patch(
            "verisight.service.GeminiTextGenerationClient",
            return_value=investigator_client,
        ),
        patch(
            "verisight.execution.structured_synthesis.GeminiTextGenerationClient",
            return_value=synthesizer_client,
        ),
        pytest.raises(
            InvestigationError, match="Structured synthesis response is invalid."
        ),
    ):
        VeriSight(
            settings=Settings(
                gemini_api_key="test-api-key",
                allow_llm_data_disclosure=True,
            ),
            planner=StubQueryPlanner(),
        ).investigate(path, "Investigate orders.")
    synthesizer_client.generate.assert_called_once()


def test_public_investigate_rebuilds_missing_planner(
    tmp_path: Path,
) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [10.0, 20.0, 30.0],
        }
    ).to_csv(path, index=False)

    investigator = StubInvestigator(
        [
            InvestigationDecision(
                action=InvestigationAction.FINISH,
                reasoning="The deterministic analysis is sufficient.",
            )
        ]
    )

    synthesizer = StubInvestigationSynthesizer(
        conclusion="The deterministic analysis supports the conclusion."
    )

    settings = Settings(gemini_api_key=None)

    service = VeriSight(
        settings=settings,
        investigator=investigator,
        synthesizer=synthesizer,
    )

    planner = StubQueryPlanner()

    with patch.object(
        VeriSight,
        "_build_gemini_planner",
        return_value=planner,
    ) as build_planner:
        result = service.investigate(
            [path],
            "Inspect the orders dataset.",
        )

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.conclusion == (
        "Investigation incomplete: no analytical observations were collected. "
        "No analytical conclusion has been established."
    )
    assert result.observation_count == 0

    build_planner.assert_called_once_with(settings)
    assert synthesizer.states == []


def test_public_ask_repairs_failed_generated_sql(tmp_path: Path) -> None:
    """The public ask API executes a repaired query after runtime failure."""

    class FailingPlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql="SELECT SUM(missing_amount) FROM orders",
            )

    class StubRepairer:
        def __init__(self) -> None:
            self.requests: list[QueryRepairRequest] = []

        def repair(self, request: QueryRepairRequest) -> QueryPlan:
            self.requests.append(request)
            return QueryPlan(
                question=request.question,
                sql="SELECT SUM(amount) AS total_amount FROM orders",
            )

    path = tmp_path / "orders.csv"
    pd.DataFrame({"amount": [10.0, 20.0, 30.0]}).to_csv(path, index=False)

    repairer = StubRepairer()

    result = VeriSight(
        planner=FailingPlanner(),
        repairer=repairer,
    ).ask(
        [path],
        "What is the total order amount?",
    )

    assert result.columns == ("total_amount",)
    assert result.rows == ((60.0,),)

    assert len(repairer.requests) == 1
    assert repairer.requests[0].failed_sql == ("SELECT SUM(missing_amount) FROM orders")


def test_public_ask_does_not_repair_successful_sql(tmp_path: Path) -> None:
    """Successful queries must not invoke the repairer."""

    repairer = MagicMock()

    path = tmp_path / "orders.csv"
    pd.DataFrame({"amount": [10.0, 20.0, 30.0]}).to_csv(path, index=False)

    result = VeriSight(
        planner=StubQueryPlanner(),
        repairer=repairer,
    ).ask(
        [path],
        "What is the total order amount?",
    )

    assert result.rows == ((3, 60.0),)
    repairer.repair.assert_not_called()


def test_public_ask_repairs_with_default_gemini_client(
    tmp_path: Path,
) -> None:
    """The default Gemini repairer is initialized only after failure."""

    path = tmp_path / "orders.csv"
    pd.DataFrame({"amount": [10.0, 20.0, 30.0]}).to_csv(path, index=False)

    generated_client = MagicMock()
    generated_client.generate.return_value = (
        "SELECT SUM(amount) AS total_amount FROM orders"
    )

    settings = Settings(
        gemini_api_key="test-api-key",
        gemini_model="test-model",
        allow_llm_data_disclosure=True,
    )

    class FailingPlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql="SELECT SUM(missing_amount) FROM orders",
            )

    with patch(
        "verisight.service.GeminiTextGenerationClient",
        return_value=generated_client,
    ) as client_class:
        result = VeriSight(
            settings=settings,
            planner=FailingPlanner(),
        ).ask(
            [path],
            "What is the total order amount?",
        )

    assert result.rows == ((60.0,),)
    client_class.assert_called_once()
    generated_client.generate.assert_called_once()


def test_public_ask_does_not_retry_failed_repaired_sql(
    tmp_path: Path,
) -> None:
    """A repaired query receives no second repair attempt."""

    class FailingPlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                question=request.question,
                sql="SELECT missing_amount FROM orders",
            )

    class FailingRepairer:
        def __init__(self) -> None:
            self.calls = 0

        def repair(self, request: QueryRepairRequest) -> QueryPlan:
            self.calls += 1
            return QueryPlan(
                question=request.question,
                sql="SELECT another_missing_column FROM orders",
            )

    path = tmp_path / "orders.csv"
    pd.DataFrame({"amount": [10.0, 20.0]}).to_csv(path, index=False)

    repairer = FailingRepairer()

    with pytest.raises(QueryRuntimeError):
        VeriSight(
            planner=FailingPlanner(),
            repairer=repairer,
        ).ask(
            [path],
            "Calculate the total.",
        )

    assert repairer.calls == 1


def test_lazy_gemini_repairer_rejects_missing_credentials() -> None:
    """A lazy repairer cannot generate SQL without credentials."""

    settings = Settings(gemini_api_key=None)
    repairer = _LazyGeminiQueryRepairer(settings)

    request = MagicMock()

    with pytest.raises(
        QueryPlanningError,
        match=r"Gemini SQL repair requires configured credentials "
        r"and explicit LLM data-disclosure permission\.",
    ):
        repairer.repair(request)


def test_lazy_gemini_repairer_reuses_initialized_client() -> None:
    """Repeated repairs reuse the existing generative repairer."""

    settings = Settings(
        gemini_api_key="test-api-key",
        gemini_model="test-model",
        allow_llm_data_disclosure=True,
    )

    repairer = _LazyGeminiQueryRepairer(settings)

    request = MagicMock()
    expected_plan = MagicMock(spec=QueryPlan)

    generated_client = MagicMock()
    generated_client.generate.return_value = (
        "SELECT COUNT(*) AS order_count FROM orders"
    )

    with (
        patch(
            "verisight.service.GeminiTextGenerationClient",
            return_value=generated_client,
        ) as client_class,
        patch("verisight.service.GenerativeQueryRepairer") as repairer_class,
    ):
        repairer_instance = repairer_class.return_value
        repairer_instance.repair.return_value = expected_plan

        first_result = repairer.repair(request)
        second_result = repairer.repair(request)

    assert first_result is expected_plan
    assert second_result is expected_plan

    client_class.assert_called_once()
    repairer_class.assert_called_once_with(generated_client)

    assert repairer_instance.repair.call_count == 2
    repairer_instance.repair.assert_any_call(request)


def test_gemini_client_requires_explicit_data_disclosure_permission() -> None:
    """Configured credentials alone must not enable external generation."""

    settings = Settings(
        gemini_api_key="test-api-key",
        allow_llm_data_disclosure=False,
    )

    with patch("verisight.service.GeminiTextGenerationClient") as client_class:
        service = VeriSight(settings=settings)

        assert service._planner is None
        assert service._repairer is None

        assert VeriSight._build_gemini_planner(settings) is None
        assert VeriSight._build_gemini_investigator(settings) is None
        assert VeriSight._build_gemini_synthesizer(settings) is None

        client_class.assert_not_called()


def test_lazy_gemini_repairer_requires_disclosure_permission() -> None:
    """Lazy SQL repair must not bypass the disclosure policy."""

    settings = Settings(
        gemini_api_key="test-api-key",
        allow_llm_data_disclosure=False,
    )

    repairer = _LazyGeminiQueryRepairer(settings)

    with patch("verisight.service.GeminiTextGenerationClient") as client_class:
        with pytest.raises(
            QueryPlanningError,
            match="Gemini SQL repair requires configured credentials.",
        ):
            repairer.repair(MagicMock())

        client_class.assert_not_called()
