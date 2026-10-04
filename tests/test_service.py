from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from verisight.analysis.result import DatasetAnalysisResult
from verisight.config import Settings
from verisight.execution.decisions import (
    InvestigationAction,
    InvestigationDecision,
)
from verisight.execution.exceptions import (
    InvestigationError,
    QueryExecutionError,
    QueryPlanningError,
)
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_result import InvestigationResult
from verisight.execution.planning import QueryPlan, QueryRequest
from verisight.service import VeriSight


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


def test_analyzes_single_csv_file(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [10.0, 20.0, 30.0],
        }
    ).to_csv(path, index=False)

    result = VeriSight().analyze([path])

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


def test_empty_input_produces_empty_analysis_result() -> None:
    result = VeriSight().analyze([])

    assert result.analysis.schema.table_count == 0
    assert result.analysis.profile.table_count == 0
    assert result.issue_count == 0
    assert result.insight_count == len(result.insights)


def test_verisight_is_available_from_package_root() -> None:
    from verisight import VeriSight as PublicVeriSight

    assert PublicVeriSight is VeriSight


def test_executes_query_against_single_csv_file(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [10.0, 20.0, 30.0],
        }
    ).to_csv(path, index=False)

    result = VeriSight().execute(
        [path],
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


def test_asks_natural_language_question_against_csv_file(
    tmp_path: Path,
) -> None:
    path = tmp_path / "orders.csv"

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
            "amount": [10.0, 20.0, 30.0],
        }
    ).to_csv(path, index=False)

    result = VeriSight(planner=StubQueryPlanner()).ask(
        [path],
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
    )

    with patch("verisight.service.GeminiTextGenerationClient") as client_class:
        service = VeriSight(settings=settings)

    client_class.assert_called_once_with(
        api_key="test-api-key",
        model="test-model",
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


def test_public_investigate_runs_autonomous_analysis(
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
        [path],
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

    assert result.conclusion == ("The deterministic analysis supports the conclusion.")
    assert result.observation_count == 0
    assert len(investigator.states) == 1

    assert len(synthesizer.states) == 1
    assert synthesizer.states[0].observation_count == 0


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

    assert result.conclusion == ("No additional analytical evidence is required.")
    assert result.observation_count == 0


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

    pd.DataFrame(
        {
            "order_id": [1, 2, 3],
        }
    ).to_csv(path, index=False)

    investigator = StubInvestigator(
        [
            InvestigationDecision(
                action=InvestigationAction.INVESTIGATE,
                reasoning="The orders table should be inspected.",
                question="Inspect the orders table.",
            )
        ]
    )

    synthesizer = StubInvestigationSynthesizer()

    with pytest.raises(
        QueryExecutionError,
        match="Only read-only analytical SELECT queries are allowed.",
    ):
        VeriSight(
            planner=UnsafeQueryPlanner(),
            investigator=investigator,
            synthesizer=synthesizer,
        ).investigate(
            [path],
            "Investigate the orders.",
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
    synthesizer_client.generate.return_value = (
        "The available deterministic evidence supports the final conclusion."
    )

    settings = Settings(
        gemini_api_key="test-api-key",
        gemini_model="test-model",
    )

    with patch(
        "verisight.service.GeminiTextGenerationClient",
        side_effect=[
            investigator_client,
            synthesizer_client,
        ],
    ) as client_class:
        result = VeriSight(
            settings=settings,
            planner=planner,
        ).investigate(
            [path],
            "What can we learn about these orders?",
        )

    assert result.question == "What can we learn about these orders?"
    assert result.conclusion == (
        "The available deterministic evidence supports the final conclusion."
    )
    assert result.observation_count == 0

    assert client_class.call_count == 2

    assert client_class.call_args_list[0].kwargs == {
        "api_key": "test-api-key",
        "model": "test-model",
    }
    assert client_class.call_args_list[1].kwargs == {
        "api_key": "test-api-key",
        "model": "test-model",
    }

    investigator_client.generate.assert_called_once()
    synthesizer_client.generate.assert_called_once()

    investigator_prompt = investigator_client.generate.call_args.args[0]
    synthesis_prompt = synthesizer_client.generate.call_args.args[0]

    assert (
        "You are the autonomous analytical investigator for VeriSight."
        in investigator_prompt
    )
    assert "What can we learn about these orders?" in investigator_prompt

    assert (
        "You are the analytical conclusion synthesizer for VeriSight."
        in synthesis_prompt
    )
    assert "What can we learn about these orders?" in synthesis_prompt


def test_default_gemini_investigator_can_request_observe_and_synthesize(
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
        "The dataset contains three orders totaling 60."
    )

    settings = Settings(
        gemini_api_key="test-api-key",
        gemini_model="test-model",
    )

    with patch(
        "verisight.service.GeminiTextGenerationClient",
        side_effect=[
            investigator_client,
            synthesizer_client,
        ],
    ):
        result = VeriSight(
            settings=settings,
            planner=planner,
        ).investigate(
            [path],
            "What can we learn about these orders?",
        )

    assert result.conclusion == ("The dataset contains three orders totaling 60.")
    assert result.observation_count == 1

    observation = result.observations[0]

    assert observation.question == "What is the total order amount?"
    assert observation.sql.strip() == (
        "SELECT\n"
        "                COUNT(*) AS order_count,\n"
        "                SUM(amount) AS total_amount\n"
        "            FROM orders"
    )
    assert observation.result.columns == (
        "order_count",
        "total_amount",
    )
    assert observation.result.rows == ((3, 60.0),)

    assert investigator_client.generate.call_count == 2
    synthesizer_client.generate.assert_called_once()

    first_prompt = investigator_client.generate.call_args_list[0].args[0]
    second_prompt = investigator_client.generate.call_args_list[1].args[0]
    synthesis_prompt = synthesizer_client.generate.call_args.args[0]

    assert "EXECUTED OBSERVATIONS\nNone" in first_prompt

    assert "EXECUTED OBSERVATIONS" in second_prompt
    assert "What is the total order amount?" in second_prompt
    assert "order_count" in second_prompt
    assert "total_amount" in second_prompt

    assert (
        "You are the analytical conclusion synthesizer for VeriSight."
        in synthesis_prompt
    )
    assert "EXECUTED OBSERVATIONS" in synthesis_prompt
    assert "What is the total order amount?" in synthesis_prompt
    assert "order_count" in synthesis_prompt
    assert "total_amount" in synthesis_prompt


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

    assert result.conclusion == ("The deterministic analysis supports the conclusion.")
    assert result.observation_count == 0

    build_planner.assert_called_once_with(settings)
