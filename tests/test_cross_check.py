"""The second, blind query behind an answer that matched its evidence."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from verisight import VeriSight
from verisight.config import Settings
from verisight.execution.claim_verification import ClaimOperation
from verisight.execution.cross_check import (
    CROSS_CHECK_COLUMN,
    CrossCheck,
    CrossCheckStatus,
    IndependentCrossChecker,
)
from verisight.execution.deadline import InvestigationDeadlineExceeded
from verisight.execution.exceptions import (
    QueryPlanningError,
    QueryResultLimitError,
    QueryValidationError,
)
from verisight.execution.execution import QueryExecution
from verisight.execution.gemini import GeminiGenerationError, GeminiTransientError
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.generative_investigator import GenerativeInvestigator
from verisight.execution.investigation_result import (
    ClaimOutputContract,
    InvestigationResult,
    InvestigationStatus,
)
from verisight.execution.models import QueryResult, QueryScalar
from verisight.execution.planning import QueryPlan
from verisight.execution.prompt_budget import PromptBudgetExceededError
from verisight.execution.structured_synthesis import StructuredInvestigationSynthesizer

PRIMARY = "SELECT SUM(amount) AS total FROM sales"
SECOND = "SELECT SUM(amount) AS cross_check_answer FROM sales WHERE amount > 0"
ANSWER = Decimal("100")


class _Runner:
    def __init__(
        self,
        columns: tuple[str, ...] = (CROSS_CHECK_COLUMN,),
        rows: tuple[tuple[QueryScalar, ...], ...] = ((100,),),
        *,
        sql: str = SECOND,
        error: Exception | None = None,
    ) -> None:
        self.result = QueryResult(columns=columns, rows=rows)
        self.sql = sql
        self.error = error
        self.calls: list[tuple[str, str | None]] = []

    def run(
        self, question: str, *, original_question: str | None = None
    ) -> QueryExecution:
        self.calls.append((question, original_question))
        if self.error is not None:
            raise self.error
        return QueryExecution(QueryPlan(question, self.sql), self.result)


def _check(runner: _Runner, answer: Decimal = ANSWER) -> CrossCheck:
    return IndependentCrossChecker(runner).check("How much?", answer, PRIMARY)


def test_matching_numbers_agree_and_keep_both_values() -> None:
    runner = _Runner()

    check = _check(runner)

    assert check == CrossCheck(
        status=CrossCheckStatus.AGREED,
        reason="values_match",
        sql=SECOND,
        primary_value=ANSWER,
        independent_value=Decimal("100"),
        identical_sql=False,
    )
    question, original = runner.calls[0]
    assert question.startswith("How much?\n\nINDEPENDENT CROSS-CHECK")
    assert original == "How much?"
    assert PRIMARY not in question


def test_second_query_is_asked_for_another_route() -> None:
    runner = _Runner()

    _check(runner)

    question = runner.calls[0][0]
    assert "less direct route" in question
    assert "exactly the same rows and meaning" in question
    assert "Do not answer with a plain WHERE column = value filter" in question
    assert "SUM(CASE WHEN condition THEN 1 ELSE 0 END)" in " ".join(question.split())


def test_different_numbers_disagree() -> None:
    check = _check(_Runner(rows=((99.5,),)))

    assert check.status is CrossCheckStatus.DISAGREED
    assert check.reason == "values_differ"
    assert check.independent_value == Decimal("99.5")


@pytest.mark.parametrize(
    ("answer", "cell", "status"),
    [
        (Decimal("333819.64"), 333819.64000000036, CrossCheckStatus.AGREED),
        (Decimal("0"), 0, CrossCheckStatus.AGREED),
        (Decimal("0"), 0.001, CrossCheckStatus.DISAGREED),
        (Decimal("12.34"), 12.3, CrossCheckStatus.DISAGREED),
        (Decimal("12.5"), 0.125, CrossCheckStatus.DISAGREED),
        (Decimal("-5"), 5, CrossCheckStatus.DISAGREED),
    ],
)
def test_only_floating_point_noise_counts_as_the_same_number(
    answer: Decimal, cell: QueryScalar, status: CrossCheckStatus
) -> None:
    assert _check(_Runner(rows=((cell,),)), answer).status is status


def test_named_column_is_found_among_others() -> None:
    runner = _Runner(("left_total", "CROSS_CHECK_ANSWER"), ((7, 100),))

    assert _check(runner).status is CrossCheckStatus.AGREED


def test_single_unnamed_column_is_accepted() -> None:
    assert _check(_Runner(("sum",), ((100,),))).status is CrossCheckStatus.AGREED


@pytest.mark.parametrize(
    ("columns", "rows"),
    [
        ((CROSS_CHECK_COLUMN,), ()),
        ((CROSS_CHECK_COLUMN,), ((1,), (2,))),
        (("first", "second"), ((100, 100),)),
        ((CROSS_CHECK_COLUMN,), (("100",),)),
        ((CROSS_CHECK_COLUMN,), ((None,),)),
        ((CROSS_CHECK_COLUMN,), ((True,),)),
        ((CROSS_CHECK_COLUMN,), ((float("nan"),),)),
    ],
)
def test_result_without_one_number_is_not_assessed(
    columns: tuple[str, ...], rows: tuple[tuple[QueryScalar, ...], ...]
) -> None:
    check = _check(_Runner(columns, rows))

    assert check.status is CrossCheckStatus.NOT_ASSESSED
    assert check.reason == "not_a_single_number"
    assert check.sql == SECOND
    assert check.primary_value == ANSWER
    assert check.independent_value is None


@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (InvestigationDeadlineExceeded("late"), "time_budget_exhausted"),
        (GeminiGenerationError("no"), "provider_failed"),
        (GeminiTransientError("busy"), "provider_failed"),
        (QueryPlanningError("no"), "query_failed"),
        (QueryValidationError("no"), "query_failed"),
        (QueryResultLimitError("no"), "query_failed"),
        (
            PromptBudgetExceededError(max_prompt_chars=1, actual_prompt_chars=2),
            "query_failed",
        ),
    ],
)
def test_failed_second_query_is_not_assessed(error: Exception, reason: str) -> None:
    check = _check(_Runner(error=error))

    assert check == CrossCheck(CrossCheckStatus.NOT_ASSESSED, reason)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("sql", "identical"),
    [
        ('SELECT SUM("amount") AS "cross_check_answer" FROM "sales"', True),
        ("SELECT SUM(amount) FROM sales", True),
        ("SELECT SUM(amount) FROM sales WHERE amount > 0", False),
        ("SELECT AVG(amount) * COUNT(amount) FROM sales", False),
    ],
)
def test_repeated_formulation_is_recorded(sql: str, identical: bool) -> None:
    check = _check(_Runner(sql=sql))

    assert check.status is CrossCheckStatus.AGREED
    assert check.identical_sql is identical


WHERE_SQL = "SELECT SUM(amount) AS total FROM sales WHERE "


@pytest.mark.parametrize(
    ("first", "second", "identical"),
    [
        ("a = 1 AND b = 2", "b = 2 AND a = 1", True),
        ("a = 1 AND b = 2 AND c = 3", "c = 3 AND a = 1 AND b = 2", True),
        ("a = 1 AND (b = 2 AND c = 3)", "(c = 3 AND b = 2) AND a = 1", True),
        ("a = 1 AND (b = 2 OR c = 3)", "(b = 2 OR c = 3) AND a = 1", True),
        ("a = 1 AND b = 2", "a = 1 OR b = 2", False),
        ("a = 1 AND b = 2", "a = 1 AND b = 3", False),
        ("a = 1 AND (b = 2 OR c = 3)", "(a = 1 AND b = 2) OR c = 3", False),
    ],
)
def test_filters_in_another_order_are_the_same_query(
    first: str, second: str, identical: bool
) -> None:
    runner = _Runner(sql=WHERE_SQL + second)

    check = IndependentCrossChecker(runner).check(
        "How much?", ANSWER, WHERE_SQL + first
    )

    assert check.identical_sql is identical


FLIGHTS = (
    "SELECT SUM(f.n) FROM flights AS f JOIN ports AS a ON f.origin = a.code "
    "WHERE a.state = 'AK'"
)
ROUTES = (
    "SELECT SUM(f.n) FROM flights AS f JOIN ports AS o ON f.origin = o.code "
    "JOIN ports AS d ON f.dest = d.code WHERE o.state = 'TX' AND d.state = 'CA'"
)
INNER = "(SELECT amount AS total FROM sales)"


@pytest.mark.parametrize(
    ("first", "second", "identical"),
    [
        (
            FLIGHTS,
            "SELECT SUM(x.n) FROM flights x JOIN ports y ON x.origin = y.code "
            "WHERE y.state = 'AK'",
            True,
        ),
        (
            FLIGHTS,
            "SELECT SUM(flights.n) FROM flights JOIN ports "
            "ON flights.origin = ports.code WHERE ports.state = 'AK'",
            True,
        ),
        (
            FLIGHTS,
            "SELECT SUM(f.n) FROM flights AS f JOIN ports AS a ON f.dest = a.code "
            "WHERE a.state = 'AK'",
            False,
        ),
        (
            ROUTES,
            ROUTES.replace("o.", "p.").replace("AS o", "AS p"),
            True,
        ),
        (
            ROUTES,
            "SELECT SUM(f.n) FROM flights AS f JOIN ports AS o ON f.origin = o.code "
            "JOIN ports AS d ON f.dest = d.code "
            "WHERE o.state = 'CA' AND d.state = 'TX'",
            False,
        ),
        (PRIMARY, "SELECT SUM(s.amount) FROM sales AS s", True),
        (PRIMARY, "SELECT SUM(other.amount) FROM sales", False),
        (
            f"SELECT SUM(x.total) FROM {INNER} AS x",
            f"SELECT SUM(y.total) FROM {INNER} AS y",
            True,
        ),
    ],
)
def test_table_aliases_do_not_make_a_query_independent(
    first: str, second: str, identical: bool
) -> None:
    check = IndependentCrossChecker(_Runner(sql=second)).check(
        "How much?", ANSWER, first
    )

    assert check.identical_sql is identical


class _Script:
    def __init__(self, items: list[str | Exception]) -> None:
        self.items = list(items)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _claim(expected: str, column: str = "total") -> dict[str, object]:
    return {
        "operation": "value",
        "expected": expected,
        "left": {"observation_index": 0, "row_index": 0, "column": column},
        "right": None,
    }


def _synthesis(conclusion: str, *claims: dict[str, object]) -> str:
    return json.dumps({"conclusion": conclusion, "claims": list(claims)})


def _decisions() -> list[str | Exception]:
    return [
        json.dumps({"action": "investigate", "reasoning": "r", "question": "Sum it"}),
        json.dumps({"action": "finish", "reasoning": "r", "question": None}),
    ]


FIRST_SQL = "SELECT SUM(amount) AS total, COUNT(*) AS rows_seen FROM sales"
AGREEING_SQL = "SELECT SUM(amount) AS cross_check_answer FROM sales"


def _investigate(
    tmp_path: Path,
    plan: list[str | Exception],
    synth: list[str | Exception],
    *,
    cross_check: bool = True,
    contract: tuple[ClaimOperation, ...] | None = None,
) -> tuple[InvestigationResult, _Script]:
    source = tmp_path / "sales.csv"
    source.write_text("amount\n10\n20\n", encoding="utf-8")
    planner = _Script(plan)
    result = VeriSight(
        settings=Settings(_env_file=None, allow_llm_data_disclosure=False),  # type: ignore[call-arg]
        planner=GenerativeQueryPlanner(planner),
        investigator=GenerativeInvestigator(_Script(_decisions())),
        synthesizer=StructuredInvestigationSynthesizer(_Script(synth)),
    ).investigate(
        source,
        "What is the total amount?",
        max_steps=2,
        claim_output_contract=(
            None if contract is None else ClaimOutputContract(contract)
        ),
        cross_check=cross_check,
    )
    return result, planner


def test_investigation_plans_the_second_query_without_the_first(
    tmp_path: Path,
) -> None:
    result, planner = _investigate(
        tmp_path,
        [FIRST_SQL, AGREEING_SQL],
        [_synthesis("The total is 30.", _claim("30"))],
        contract=(ClaimOperation.VALUE,),
    )

    assert result.status is InvestigationStatus.COMPLETE
    assert result.cross_check is not None
    assert result.cross_check.status is CrossCheckStatus.AGREED
    assert result.cross_check.primary_value == Decimal("30")
    assert result.cross_check.identical_sql is False
    assert len(planner.prompts) == 2
    blind = planner.prompts[1]
    assert "INDEPENDENT CROSS-CHECK" in blind
    assert FIRST_SQL not in blind
    assert "rows_seen" not in blind
    assert "The total is 30" not in blind


def test_mistaken_first_query_is_caught(tmp_path: Path) -> None:
    result, _ = _investigate(
        tmp_path,
        ["SELECT COUNT(*) AS total FROM sales", AGREEING_SQL],
        [_synthesis("The total is 2.", _claim("2"))],
        contract=(ClaimOperation.VALUE,),
    )

    assert result.cross_check is not None
    assert result.cross_check.status is CrossCheckStatus.DISAGREED
    assert result.cross_check.independent_value == Decimal("30")


def test_cross_check_is_off_by_default(tmp_path: Path) -> None:
    result, planner = _investigate(
        tmp_path,
        [FIRST_SQL],
        [_synthesis("The total is 30.", _claim("30"))],
        cross_check=False,
    )

    assert result.cross_check is None
    assert len(planner.prompts) == 1


@pytest.mark.parametrize(
    ("synth", "contract"),
    [
        ([_synthesis("No number could be established.")], None),
        ([_synthesis("The total is 31.", _claim("31"))], None),
        (
            [_synthesis("The total is 30.", _claim("30"))],
            (ClaimOperation.VALUE, ClaimOperation.VALUE),
        ),
    ],
)
def test_rejected_answers_spend_no_second_query(
    tmp_path: Path,
    synth: list[str | Exception],
    contract: tuple[ClaimOperation, ...] | None,
) -> None:
    # A contract mismatch is repaired once, so that case needs a second response.
    responses = synth + synth
    result, planner = _investigate(tmp_path, [FIRST_SQL], responses, contract=contract)

    assert result.cross_check is None
    assert len(planner.prompts) == 1


def test_incomplete_investigation_spends_no_second_query(tmp_path: Path) -> None:
    result, planner = _investigate(tmp_path, [FIRST_SQL], [GeminiGenerationError("no")])

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.cross_check is None
    assert len(planner.prompts) == 1


def test_several_claims_are_not_assessed(tmp_path: Path) -> None:
    result, planner = _investigate(
        tmp_path,
        [FIRST_SQL],
        [
            _synthesis(
                "The total is 30 over 2 rows.",
                _claim("30"),
                _claim("2", "rows_seen"),
            )
        ],
    )

    assert result.cross_check == CrossCheck(
        CrossCheckStatus.NOT_ASSESSED, "multiple_claims"
    )
    assert len(planner.prompts) == 1


def test_configured_model_plans_the_cross_check() -> None:
    settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        gemini_api_key="key",
        allow_llm_data_disclosure=True,
        gemini_cross_check_model="other-model",
    )
    primary = GenerativeQueryPlanner(_Script([]))
    engine = VeriSight(settings=settings)

    chosen = engine._cross_check_planner(primary)

    assert isinstance(chosen, GenerativeQueryPlanner)
    assert chosen is not primary
    assert chosen._client._model == "other-model"  # type: ignore[attr-defined]


def test_main_planner_is_used_without_a_cross_check_model() -> None:
    settings = Settings(_env_file=None, allow_llm_data_disclosure=False)  # type: ignore[call-arg]
    primary = GenerativeQueryPlanner(_Script([]))

    assert VeriSight(settings=settings)._cross_check_planner(primary) is primary
