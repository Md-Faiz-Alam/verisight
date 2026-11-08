"""The SQL audit, answers without AI, and the trust level they lead to."""

import json
from pathlib import Path

import pytest

from verisight import VeriSight
from verisight.config import Settings
from verisight.execution.claim_verification import ClaimOperation
from verisight.execution.context import QueryContextBuilder
from verisight.execution.direct import Clarification, DirectAnswer, DirectAnswerer
from verisight.execution.engine import DuckDBExecutor
from verisight.execution.exceptions import QueryRuntimeError
from verisight.execution.gemini import GeminiTransientError
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.generative_investigator import GenerativeInvestigator
from verisight.execution.investigation_result import (
    ClaimOutputContract,
    InvestigationResult,
)
from verisight.execution.models import QueryResult
from verisight.execution.sql_audit import SqlAudit, audit_sql
from verisight.execution.structured_synthesis import StructuredInvestigationSynthesizer
from verisight.execution.trust import TrustLevel
from verisight.ingestion.models import LoadedDataset
from verisight.ingestion.service import DatasetLoader

SETTINGS = Settings(
    _env_file=None,  # type: ignore[call-arg]
    gemini_api_key=None,
    allow_llm_data_disclosure=False,
)
ORDERS = (
    "order_id,customer,region,status,amount,bonus,day\n"
    "1,c1,East,Shipped,100,,2025-01-05\n"
    "2,c2,West,shipped,200,5,2025-02-05\n"
    "3,c3,East,Pending,300,7,2024-03-05\n"
)
ITEMS = "order_id,sku\n1,a\n1,b\n2,c\n3,d\n"
CUSTOMERS = "customer,segment,region\nc1,Business,East\nc2,Home,West\nc3,Home,East\n"
SALES = (
    "region,month,amount\n"
    "East,Jan,10\nWest,Jan,20\nNorth,Jan,30\nTotal,Jan,60\n"
    "East,Feb,1\nWest,Feb,2\nNorth,Feb,3\nTotal,Feb,6\n"
    "East,Mar,4\nWest,Mar,5\nNorth,Mar,6\nTotal,Mar,15\n"
)


def _dataset(tmp_path: Path, **files: str) -> LoadedDataset:
    paths = []
    for name, text in files.items():
        path = tmp_path / f"{name}.csv"
        path.write_text(text, encoding="utf-8")
        paths.append(path)
    return DatasetLoader(SETTINGS).load(paths)


def _audit(dataset: LoadedDataset, question: str, sql: str) -> SqlAudit:
    context = QueryContextBuilder().build_from_dataset(dataset)
    return audit_sql(
        question=question,
        sql=sql,
        result=DuckDBExecutor().execute(dataset, sql),
        dataset=dataset,
        total_rows=context.total_rows,
        categories=context.review_categories,
    )


def _codes(dataset: LoadedDataset, question: str, sql: str) -> set[str]:
    return {finding.code for finding in _audit(dataset, question, sql).findings}


@pytest.fixture
def shop(tmp_path: Path) -> LoadedDataset:
    return _dataset(tmp_path, orders=ORDERS, items=ITEMS, customers=CUSTOMERS)


JOINED = "FROM orders o JOIN items i ON o.order_id = i.order_id"


@pytest.mark.parametrize(
    ("sql", "code"),
    [
        (f"SELECT SUM(o.amount) AS t {JOINED}", "join_fan_out"),
        (f"SELECT SUM(amount) AS t {JOINED}", "join_fan_out"),
        (
            f"WITH j AS (SELECT o.amount AS amount {JOINED}) SELECT SUM(amount) FROM j",
            "join_fan_out",
        ),
        (f"SELECT COUNT(o.amount) AS t {JOINED}", "join_fan_out"),
    ],
)
def test_measures_copied_by_a_join_are_found(
    shop: LoadedDataset, sql: str, code: str
) -> None:
    assert code in _codes(shop, "How much came in?", sql)


@pytest.mark.parametrize(
    "sql",
    [
        f"SELECT COUNT(DISTINCT o.amount) AS t {JOINED}",
        f"SELECT COUNT(*) AS t {JOINED}",
        # The other side of the join is not copied.
        f"SELECT COUNT(i.sku) AS t {JOINED}",
        "SELECT SUM(o.amount) AS t FROM orders o JOIN customers c "
        "ON o.customer = c.customer",
        # A grouped subquery has one row per key.
        "SELECT SUM(o.amount) AS t FROM orders o JOIN "
        "(SELECT order_id FROM items GROUP BY order_id) i ON o.order_id = i.order_id",
        # Conditions that are not column equalities between two tables.
        "SELECT SUM(o.amount) AS t FROM orders o JOIN items i ON o.order_id > 0",
        "SELECT SUM(o.amount) AS t FROM orders o JOIN items i "
        "ON o.order_id = o.order_id",
        "SELECT SUM(o.amount) AS t FROM orders o CROSS JOIN customers c",
        # An unqualified name that both sides of the join could own.
        "SELECT SUM(o.amount) AS t FROM orders o JOIN items i ON order_id = sku",
        "SELECT SUM(o.amount) AS t FROM orders o JOIN items i ON amount = sku",
        "SELECT SUM(o.amount) AS t FROM orders o JOIN items i "
        "ON o.order_id = i.missing_alias",
    ],
)
def test_harmless_joins_are_not_flagged(shop: LoadedDataset, sql: str) -> None:
    try:
        codes = _codes(shop, "How much came in?", sql)
    except QueryRuntimeError:
        audit = audit_sql(
            question="How much came in?",
            sql=sql,
            result=None,
            dataset=shop,
        )
        codes = {finding.code for finding in audit.findings}
    assert "join_fan_out" not in codes


def test_repeats_with_mismatched_key_types_are_skipped(tmp_path: Path) -> None:
    data = _dataset(tmp_path, a="k,v\n1,1\n2,2\n", b="k,w\nx,1\nx,2\n")

    audit = audit_sql(
        question="q",
        sql="SELECT SUM(a.v) FROM a JOIN b ON a.k = b.k",
        result=None,
        dataset=data,
    )

    assert audit.assessed
    assert audit.findings == ()


def test_join_without_matching_repeats_is_fine(tmp_path: Path) -> None:
    data = _dataset(tmp_path, a="k,v\n1,1\n2,2\n", b="k,w\n9,1\n9,2\n")

    assert _codes(data, "q", "SELECT SUM(a.v) AS t FROM a JOIN b ON a.k = b.k") == {
        "empty_result"
    }


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(amount) AS t FROM sales",
        "WITH s AS (SELECT amount FROM sales) SELECT SUM(amount) AS t FROM s",
        "SELECT SUM(a) AS t FROM (SELECT amount a FROM sales)",
    ],
)
def test_total_rows_are_found_through_subqueries(tmp_path: Path, sql: str) -> None:
    data = _dataset(tmp_path, sales=SALES)

    assert "total_rows_included" in _codes(data, "How much came in?", sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT SUM(amount) AS t FROM sales WHERE region <> 'Total'",
        "SELECT amount FROM sales LIMIT 1",
    ],
)
def test_handled_total_rows_are_fine(tmp_path: Path, sql: str) -> None:
    data = _dataset(tmp_path, sales=SALES)

    assert "total_rows_included" not in _codes(data, "How much came in?", sql)


@pytest.mark.parametrize(
    ("sql", "code", "hint"),
    [
        (
            "SELECT COUNT(*) AS n FROM orders WHERE status = 'Shipped'",
            "filter_misses_spellings",
            "other spellings",
        ),
        (
            "SELECT COUNT(*) AS n FROM orders WHERE region = 'east'",
            "filter_misses_spellings",
            "written",
        ),
        (
            "SELECT COUNT(*) AS n FROM orders WHERE region = 'Texas'",
            "filter_value_missing",
            "never contains",
        ),
        (
            "SELECT COUNT(*) AS n FROM orders WHERE status = 'East'",
            "filter_value_missing",
            "appears in region",
        ),
        (
            "SELECT COUNT(*) AS n FROM orders WHERE status IN ('Nope')",
            "filter_value_missing",
            "never",
        ),
    ],
)
def test_filters_are_checked_against_the_data(
    shop: LoadedDataset, sql: str, code: str, hint: str
) -> None:
    findings = _audit(shop, "How many are there?", sql).findings

    assert code in {finding.code for finding in findings}
    assert any(hint in finding.detail for finding in findings)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) AS n FROM orders WHERE LOWER(TRIM(status)) = 'shipped'",
        "SELECT COUNT(*) AS n FROM orders WHERE region = 'East'",
        # A number column is not text.
        "SELECT COUNT(*) AS n FROM orders WHERE amount = '100'",
        # The same column name in two tables, with no way to tell which.
        "SELECT COUNT(*) AS n FROM orders JOIN customers USING (customer) WHERE true",
        "SELECT COUNT(*) AS n FROM orders o, customers c WHERE c.region = 'East'",
        # An alias that is not a loaded table.
        "WITH x AS (SELECT status FROM orders) SELECT COUNT(*) AS n FROM x "
        "WHERE x.status = 'nothing' OR 1 = 1",
    ],
)
def test_sound_filters_pass(shop: LoadedDataset, sql: str) -> None:
    codes = _codes(shop, "How many are there?", sql)

    assert not codes & {"filter_value_missing", "filter_misses_spellings"}


def test_ambiguous_unqualified_column_is_skipped(shop: LoadedDataset) -> None:
    audit = audit_sql(
        question="q",
        sql="SELECT COUNT(*) FROM orders o JOIN customers c "
        "ON o.customer = c.customer WHERE region = 'Nowhere'",
        result=None,
        dataset=shop,
    )

    assert audit.findings == ()


@pytest.mark.parametrize(
    ("question", "sql", "flagged"),
    [
        ("How much was Pending?", "SELECT SUM(amount) AS t FROM orders", True),
        (
            "How much was Pending?",
            "SELECT SUM(amount) AS t FROM orders WHERE status = 'shipped'",
            True,
        ),
        (
            "How much was Pending?",
            "SELECT SUM(amount) AS t FROM orders WHERE status = 'Pending'",
            False,
        ),
        (
            "How much was Pending?",
            "SELECT SUM(amount) AS t FROM orders WHERE status LIKE 'Pen%'"
            " OR status LIKE '%pending%'",
            False,
        ),
        # A grouped column shows every value, including the one asked about.
        (
            "How much was Pending?",
            "SELECT status, SUM(amount) AS t FROM orders GROUP BY status",
            False,
        ),
        (
            "Average for Business customers?",
            "SELECT AVG(amount) AS t FROM orders",
            True,
        ),
    ],
)
def test_values_the_question_names_must_be_selected(
    shop: LoadedDataset, question: str, sql: str, flagged: bool
) -> None:
    assert ("named_value_not_selected" in _codes(shop, question, sql)) is flagged


def test_a_value_in_several_columns_needs_tying_down(tmp_path: Path) -> None:
    text = "housing,loan,n\nyes,no,1\nno,yes,2\nyes,yes,3\n"
    data = _dataset(tmp_path, bank=text)
    sql = "SELECT COUNT(*) AS c FROM bank WHERE loan = 'yes'"

    assert "named_value_not_selected" in _codes(
        data, "How many where housing is yes?", sql
    )
    assert "named_value_not_selected" not in _codes(data, "How many said yes?", sql)


def test_short_labels_count_only_in_capitals(tmp_path: Path) -> None:
    data = _dataset(tmp_path, t="zone,v\nNA,1\nEU,2\n", u="flag,w\nno,1\nok,2\n")

    na = "SELECT SUM(v) AS s FROM t WHERE zone = 'EU'"
    assert "named_value_not_selected" in _codes(data, "Total in NA?", na)
    plain = "SELECT SUM(w) AS s FROM u WHERE flag = 'ok'"
    assert "named_value_not_selected" not in _codes(data, "Is there no total?", plain)


@pytest.mark.parametrize(
    ("question", "sql", "code"),
    [
        (
            "What is the average bonus?",
            "SELECT AVG(amount) AS a FROM orders",
            "question_column_unused",
        ),
        (
            "What is the average amount?",
            "SELECT COUNT(*) AS a FROM orders WHERE amount > 0",
            "wrong_calculation",
        ),
        (
            "What is the highest amount?",
            "SELECT AVG(amount) AS a FROM orders",
            "wrong_calculation",
        ),
        (
            "What is the median amount?",
            "SELECT AVG(amount) AS a FROM orders",
            "wrong_calculation",
        ),
    ],
)
def test_calculation_must_match_the_question(
    shop: LoadedDataset, question: str, sql: str, code: str
) -> None:
    assert code in _codes(shop, question, sql)


@pytest.mark.parametrize(
    ("question", "sql"),
    [
        ("What is the average amount?", "SELECT AVG(amount) AS a FROM orders"),
        (
            "What is the average of the amount?",
            "SELECT SUM(amount)/COUNT(*) AS a FROM orders",
        ),
        (
            "What is the highest amount?",
            "SELECT amount FROM orders ORDER BY amount DESC LIMIT 1",
        ),
        ("What is the median amount?", "SELECT MEDIAN(amount) AS a FROM orders"),
        ("What is the average spend?", "SELECT COUNT(*) AS a FROM orders"),
    ],
)
def test_matching_calculations_pass(
    shop: LoadedDataset, question: str, sql: str
) -> None:
    assert not _codes(shop, question, sql) & {
        "wrong_calculation",
        "question_column_unused",
    }


def test_missing_values_counted_as_zero(shop: LoadedDataset) -> None:
    sql = "SELECT AVG(COALESCE(bonus, 0)) AS a FROM orders"

    assert "missing_counted_as_zero" in _codes(shop, "What was paid?", sql)
    assert "missing_counted_as_zero" not in _codes(
        shop, "What was paid, counting missing as zero?", sql
    )
    filled = "SELECT AVG(COALESCE(amount, 0)) AS a FROM orders"
    assert "missing_counted_as_zero" not in _codes(shop, "What was paid?", filled)
    other = "SELECT AVG(COALESCE(bonus, 1)) AS a FROM orders"
    assert "missing_counted_as_zero" not in _codes(shop, "What was paid?", other)


@pytest.mark.parametrize(
    ("question", "sql", "code", "flagged"),
    [
        (
            "How many have no recorded bonus?",
            "SELECT COUNT(*) AS n FROM orders WHERE bonus = 0",
            "missing_values_ignored",
            True,
        ),
        (
            "How many have no recorded bonus?",
            "SELECT COUNT(*) AS n FROM orders WHERE bonus IS NULL",
            "missing_values_ignored",
            False,
        ),
        (
            "How many have a recorded bonus?",
            "SELECT COUNT(*) AS n FROM orders",
            "unknown_values_counted",
            True,
        ),
        (
            "How many have a recorded bonus?",
            "SELECT COUNT(*) AS n FROM orders WHERE bonus IS NOT NULL",
            "unknown_values_counted",
            False,
        ),
        (
            "Among orders with a recorded bonus, the mean?",
            "SELECT AVG(bonus) AS n FROM orders",
            "unknown_values_counted",
            False,
        ),
        (
            "How many were recorded as paid?",
            "SELECT COUNT(*) AS n FROM orders",
            "unknown_values_counted",
            False,
        ),
        (
            "How many orders?",
            "SELECT COUNT(*) AS n FROM orders",
            "unknown_values_counted",
            False,
        ),
    ],
)
def test_questions_about_missing_values(
    shop: LoadedDataset, question: str, sql: str, code: str, flagged: bool
) -> None:
    assert (code in _codes(shop, question, sql)) is flagged


def test_named_years_must_be_selected(shop: LoadedDataset, tmp_path: Path) -> None:
    question = "What was the amount in 2025?"

    assert "period_not_selected" in _codes(
        shop, question, "SELECT SUM(amount) AS t FROM orders WHERE MONTH(day) = 3"
    )
    assert "period_not_selected" not in _codes(
        shop, question, "SELECT SUM(amount) AS t FROM orders WHERE YEAR(day) = 2025"
    )
    column = _dataset(tmp_path, t='"2025",k\n1,a\n')
    assert "period_not_selected" not in _codes(
        column, question, 'SELECT "2025" AS t FROM t'
    )


@pytest.mark.parametrize(
    ("question", "sql", "code", "flagged"),
    [
        (
            "Orders of at least 200?",
            "SELECT COUNT(*) AS n FROM orders WHERE amount > 200",
            "threshold_boundary",
            True,
        ),
        (
            "Orders of at least 200?",
            "SELECT COUNT(*) AS n FROM orders WHERE amount >= 200",
            "threshold_boundary",
            False,
        ),
        (
            "Orders above 200?",
            "SELECT COUNT(*) AS n FROM orders WHERE amount >= 200",
            "threshold_boundary",
            True,
        ),
        (
            "Orders over 1,000?",
            "SELECT COUNT(*) AS n FROM orders",
            "threshold_not_applied",
            True,
        ),
        (
            "Orders over 200?",
            "SELECT COUNT(*) AS n FROM orders WHERE amount > 200",
            "threshold_not_applied",
            False,
        ),
    ],
)
def test_thresholds(
    shop: LoadedDataset, question: str, sql: str, code: str, flagged: bool
) -> None:
    assert (code in _codes(shop, question, sql)) is flagged


def test_percentages_are_not_divided_down(shop: LoadedDataset) -> None:
    question = "What percentage is the bonus?"

    assert "wrong_scale" in _codes(
        shop, question, "SELECT AVG(bonus) / 100 AS p FROM orders"
    )
    for sql in (
        "SELECT AVG(bonus) AS p FROM orders",
        "SELECT AVG(bonus) / 100 * 100 AS p FROM orders",
        "SELECT AVG(bonus) / 2 AS p FROM orders",
    ):
        assert "wrong_scale" not in _codes(shop, question, sql)
    assert "wrong_scale" not in _codes(
        shop, "The bonus?", "SELECT AVG(bonus) / 100 AS p FROM orders"
    )


def test_subtraction_direction(shop: LoadedDataset) -> None:
    question = "What is East minus West in total amount?"
    east = "(SELECT SUM(amount) FROM orders WHERE region = 'East')"
    west = "(SELECT SUM(amount) FROM orders WHERE region = 'West')"

    backwards = _audit(shop, question, f"SELECT {west} - {east} AS d").findings
    assert "reversed_subtraction" in {f.code for f in backwards}
    assert "east minus west" in " ".join(f.detail for f in backwards)
    assert "reversed_subtraction" not in _codes(
        shop, question, f"SELECT {east} - {west} AS d"
    )
    assert "reversed_subtraction" not in _codes(
        shop, "East and West?", f"SELECT {west} - {east} AS d"
    )


def test_empty_results_are_findings(shop: LoadedDataset) -> None:
    assert "empty_result" in _codes(
        shop, "q", "SELECT amount FROM orders WHERE amount > 9999"
    )
    assert "empty_result" in _codes(
        shop, "q", "SELECT SUM(amount) AS s FROM orders WHERE amount > 9999"
    )


@pytest.mark.parametrize("sql", ["SELECT (", "SELECT 1 AS one"])
def test_unreadable_sql_is_not_assessed(shop: LoadedDataset, sql: str) -> None:
    audit = audit_sql(question="q", sql=sql, result=None, dataset=shop)

    assert audit == SqlAudit(False)


def _answerer(tmp_path: Path, **files: str) -> DirectAnswerer:
    return DirectAnswerer(_dataset(tmp_path, **files), DuckDBExecutor())


def _value(answer: object) -> object:
    assert isinstance(answer, DirectAnswer)
    return answer.observation.result.rows[0][0]


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("How many rows does orders have?", 3),
        ("how many records are in orders", 3),
        ("How many rows have status equal to shipped?", 2),
        ("How many orders were shipped?", 2),
        ("What is the total amount?", 600),
        ("What is the sum of bonus?", 12),
        ("What was the average amount?", 200.0),
        ("What is the highest amount where status is Pending?", 300),
        ("What is the lowest amount for East?", 100),
        ("What is the total amount in 2025?", 300),
        ("What is the total amount in 2025-02?", 200),
        ("What is the total amount in 2025-02-05?", 200),
    ],
)
def test_plain_questions_need_no_model(
    tmp_path: Path, question: str, expected: object
) -> None:
    answer = _answerer(tmp_path, orders=ORDERS).answer(question)

    assert _value(answer) == expected
    assert isinstance(answer, DirectAnswer)
    assert answer.trust.level is TrustLevel.COMPUTED
    assert answer.claim.verification.actual is not None
    assert "AI" in answer.conclusion


@pytest.mark.parametrize(
    "question",
    [
        "Why did sales fall?",
        "How many rows does nothing have?",
        "How many rows have nothing equal to x?",
        "How many rows have status equal to nothing?",
        "How many things were shipped?",
        "How many orders were nothing?",
        "What is the total nothing?",
        "What is the total status?",
        "What is the total amount where status is nothing?",
        "What is the total amount where nothing is x?",
        "What is the total amount for Atlantis?",
    ],
)
def test_anything_unclear_goes_to_the_model(tmp_path: Path, question: str) -> None:
    assert _answerer(tmp_path, orders=ORDERS).answer(question) is None


def test_column_in_two_tables_is_not_guessed(tmp_path: Path) -> None:
    answerer = _answerer(tmp_path, a="v,k\n1,x\n", b="v,j\n2,y\n")

    assert answerer.answer("What is the total v?") is None


def test_filter_on_another_table_goes_to_the_model(tmp_path: Path) -> None:
    answerer = _answerer(tmp_path, a="v,k\n1,x\n", b="w,j\n2,y\n")

    assert answerer.answer("What is the total v where j is y?") is None


def test_a_value_in_two_columns_gets_a_question(tmp_path: Path) -> None:
    text = "origin,dest,fare\nParis,Rome,10\nRome,Oslo,20\n"

    answer = _answerer(tmp_path, trips=text).answer("What is the total fare for Rome?")

    assert isinstance(answer, Clarification)
    assert "Rome" in answer.prompt
    assert answer.options == (
        "What is the total fare where origin is Rome?",
        "What is the total fare where dest is Rome?",
    )


def test_period_needs_exactly_one_date_column(tmp_path: Path) -> None:
    text = "start,stop,fare\n2025-01-01,2025-01-02,10\n2025-02-01,2025-02-02,20\n"

    assert _answerer(tmp_path, t=text).answer("What is the total fare in 2025") is None


def test_total_rows_are_left_out_unless_chosen(tmp_path: Path) -> None:
    answerer = _answerer(tmp_path, sales=SALES)

    assert _value(answerer.answer("What is the total amount?")) == 81
    assert _value(answerer.answer("What is the total amount?")) == 81
    assert _value(answerer.answer("What is the total amount for Total?")) == 81


def test_empty_value_goes_to_the_model(tmp_path: Path) -> None:
    text = "kind,bonus\na,\nb,5\n"

    assert _answerer(tmp_path, t=text).answer("What is the total bonus for a?") is None


def test_failed_query_goes_to_the_model(tmp_path: Path) -> None:
    class Failing(DuckDBExecutor):
        def execute(self, dataset: LoadedDataset, query: str) -> QueryResult:
            raise QueryRuntimeError("no")

    answerer = DirectAnswerer(_dataset(tmp_path, orders=ORDERS), Failing())

    assert answerer.answer("What is the total amount?") is None


class _Script:
    def __init__(self, items: list[str | Exception]) -> None:
        self.items = list(items)

    def generate(self, prompt: str) -> str:
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _investigate(
    tmp_path: Path,
    plan: list[str | Exception],
    conclusion: str = "The total is 600.",
    expected: str = "600",
    *,
    question: str = "What is the total amount?",
    contract: bool = True,
) -> InvestigationResult:
    path = tmp_path / "orders.csv"
    path.write_text(ORDERS, encoding="utf-8")
    decisions: list[str | Exception] = [
        json.dumps({"action": "investigate", "reasoning": "r", "question": "Sum"}),
        json.dumps({"action": "finish", "reasoning": "r", "question": None}),
    ]
    claim = {
        "operation": "value",
        "expected": expected,
        "left": {"observation_index": 0, "row_index": 0, "column": "total"},
        "right": None,
    }
    synthesis = json.dumps({"conclusion": conclusion, "claims": [claim]})
    return VeriSight(
        settings=SETTINGS,
        planner=GenerativeQueryPlanner(_Script(plan)),
        investigator=GenerativeInvestigator(_Script(decisions)),
        synthesizer=StructuredInvestigationSynthesizer(_Script([synthesis, synthesis])),
    ).investigate(
        path,
        question,
        max_steps=2,
        claim_output_contract=(
            ClaimOutputContract((ClaimOperation.VALUE,)) if contract else None
        ),
        cross_check=True,
    )


GOOD = "SELECT SUM(amount) AS total FROM orders"
SECOND = "SELECT SUM(amount) AS cross_check_answer FROM orders"


def _level(result: InvestigationResult) -> TrustLevel:
    assert result.trust is not None
    return result.trust.level


def test_all_checks_passing_earns_verified(tmp_path: Path) -> None:
    result = _investigate(tmp_path, [GOOD, SECOND])

    assert _level(result) is TrustLevel.VERIFIED
    assert result.trust is not None
    assert [check.name for check in result.trust.checks] == [
        "number_matches_sql",
        "sql_audit",
        "population_review",
        "second_query",
        "second_query_audit",
    ]


def test_second_query_agreeing_on_a_flawed_query_is_not_enough(tmp_path: Path) -> None:
    flawed = "SELECT SUM(amount) AS total FROM orders WHERE region = 'Nowhere' OR 1 = 1"

    result = _investigate(tmp_path, [flawed, SECOND])

    assert _level(result) is TrustLevel.NEEDS_REVIEW
    assert result.trust is not None
    assert "never contains" in result.trust.checks[1].detail


def test_disagreement_needs_review(tmp_path: Path) -> None:
    other = "SELECT SUM(bonus) AS cross_check_answer FROM orders"

    result = _investigate(tmp_path, [GOOD, other])

    assert _level(result) is TrustLevel.NEEDS_REVIEW
    assert result.trust is not None
    assert "instead of" in result.trust.checks[3].detail


def test_flawed_second_query_needs_review(tmp_path: Path) -> None:
    flawed = (
        "SELECT SUM(amount) AS cross_check_answer FROM orders "
        "WHERE region = 'Nowhere' OR 1 = 1"
    )

    assert _level(_investigate(tmp_path, [GOOD, flawed])) is TrustLevel.NEEDS_REVIEW


def test_sql_that_cannot_be_audited_is_only_a_number_match(tmp_path: Path) -> None:
    result = _investigate(
        tmp_path, ["SELECT 600 AS total", SECOND], question="Tell me the figure."
    )

    assert _level(result) is TrustLevel.NUMBER_MATCHED


def test_unavailable_second_query_is_only_a_number_match(tmp_path: Path) -> None:
    result = _investigate(tmp_path, [GOOD, GeminiTransientError("busy")])

    assert _level(result) is TrustLevel.NUMBER_MATCHED


def test_population_warning_needs_review(tmp_path: Path) -> None:
    sql = "SELECT SUM(amount) AS total FROM orders WHERE status = 'shipped'"
    second = sql.replace("total", "cross_check_answer")

    result = _investigate(
        tmp_path,
        [sql, second],
        "The total is 200.",
        "200",
        question="What is the total amount for Pending?",
    )

    assert _level(result) is TrustLevel.NEEDS_REVIEW


def test_rejected_answers_stop_at_the_first_check(tmp_path: Path) -> None:
    result = _investigate(
        tmp_path, [GOOD, SECOND], "The total is 601.", "601", contract=False
    )

    assert _level(result) is TrustLevel.NOT_VERIFIED
    assert result.trust is not None
    assert len(result.trust.checks) == 1


def test_trust_is_only_reported_with_the_second_query(tmp_path: Path) -> None:
    path = tmp_path / "orders.csv"
    path.write_text(ORDERS, encoding="utf-8")
    decisions: list[str | Exception] = [
        json.dumps({"action": "investigate", "reasoning": "r", "question": "Sum"}),
        json.dumps({"action": "finish", "reasoning": "r", "question": None}),
    ]
    synthesis = json.dumps({"conclusion": "Nothing.", "claims": []})

    result = VeriSight(
        settings=SETTINGS,
        planner=GenerativeQueryPlanner(_Script([GOOD])),
        investigator=GenerativeInvestigator(_Script(decisions)),
        synthesizer=StructuredInvestigationSynthesizer(_Script([synthesis])),
    ).investigate(path, "Total?", max_steps=2)

    assert result.trust is None
