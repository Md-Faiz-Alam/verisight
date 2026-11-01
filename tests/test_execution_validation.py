from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest
from sqlglot.errors import ParseError

from verisight.error_reporting import ErrorCode
from verisight.execution.context import QueryContext
from verisight.execution.engine import DuckDBExecutor
from verisight.execution.exceptions import (
    QueryExecutionError,
    QueryValidationError,
)
from verisight.execution.validation import (
    AnalyticalQueryValidator,
    _mask_sql_literals_and_comments,
    validate_dataset_relations,
)
from verisight.ingestion.models import LoadedDataset, LoadedTable, SourceMetadata
from verisight.public_api import run_public_operation


@pytest.mark.parametrize(
    "query",
    [
        "SELECT 1",
        "SELECT 1 + 2 AS value",
        """
        WITH values_cte AS (
            SELECT 1 AS value
        )
        SELECT value
        FROM values_cte
        """,
        """
        SELECT customer_id, SUM(amount)
        FROM orders
        GROUP BY customer_id
        """,
        """
        SELECT *
        FROM customers
        JOIN orders
            ON customers.customer_id = orders.customer_id
        """,
        """
        SELECT
            customer_id,
            ROW_NUMBER() OVER (
                ORDER BY customer_id
            ) AS row_number
        FROM customers
        """,
        """
        SELECT customer_id
        FROM customers
        UNION
        SELECT customer_id
        FROM orders
        """,
    ],
)
def test_accepts_analytical_select_queries(query: str) -> None:
    AnalyticalQueryValidator().validate(query)


@pytest.mark.parametrize(
    "query",
    [
        "CREATE TABLE example AS SELECT 1",
        "INSERT INTO example VALUES (1)",
        "UPDATE example SET value = 2",
        "DELETE FROM example",
        "DROP TABLE example",
        "COPY (SELECT 1) TO 'output.csv'",
        "ATTACH 'database.db' AS external_db",
        "DETACH external_db",
        "INSTALL httpfs",
        "LOAD httpfs",
        "CALL checkpoint()",
        "EXPORT DATABASE 'export_dir'",
        "SET threads = 1",
        "RESET threads",
        "VACUUM",
    ],
)
def test_rejects_non_select_statements(query: str) -> None:
    with pytest.raises(
        QueryValidationError,
        match="Only read-only analytical SELECT queries are allowed.",
    ):
        AnalyticalQueryValidator().validate(query)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT * FROM read_csv_auto('data.csv')",
        "SELECT * FROM read_csv('data.csv')",
        "SELECT * FROM read_parquet('data.parquet')",
        "SELECT * FROM read_json_auto('data.json')",
        "SELECT * FROM read_json('data.json')",
        "SELECT read_blob('data.txt')",
        "SELECT * FROM glob('*')",
        "SELECT getenv('PATH')",
        "SELECT * FROM read_text('data.txt')",
        "SELECT * FROM read_ndjson('data.ndjson')",
        "SELECT * FROM read_ndjson_auto('data.ndjson')",
        "SELECT * FROM read_csv/**/('data.csv')",
    ],
)
def test_rejects_external_access_from_select(query: str) -> None:
    with pytest.raises(
        QueryValidationError,
        match="External data access is not allowed",
    ):
        AnalyticalQueryValidator().validate(query)


@pytest.mark.parametrize(
    "query",
    [
        "PRAGMA version",
        "PRAGMA database_list",
    ],
)
def test_rejects_pragma_queries(query: str) -> None:
    with pytest.raises(
        QueryValidationError,
        match="PRAGMA statements are not allowed",
    ):
        AnalyticalQueryValidator().validate(query)


def test_rejects_multiple_statements() -> None:
    with pytest.raises(
        QueryValidationError,
        match="requires exactly one SQL statement",
    ):
        AnalyticalQueryValidator().validate("SELECT 1; SELECT 2")


@pytest.mark.parametrize(
    "query",
    [
        "",
        " ",
        "\n\t",
    ],
)
def test_rejects_empty_query(query: str) -> None:
    with pytest.raises(
        QueryValidationError,
        match="Analytical query must not be empty.",
    ):
        AnalyticalQueryValidator().validate(query)


def test_invalid_sql_raises_validation_error() -> None:
    with pytest.raises(
        QueryValidationError,
        match="Analytical query validation failed:",
    ):
        AnalyticalQueryValidator().validate("SELECT FROM")


def test_validation_error_is_query_execution_error() -> None:
    error = QueryValidationError("Invalid query")

    assert isinstance(error, QueryExecutionError)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT 'read_csv(' AS value",
        "SELECT 'read_parquet(' AS value",
        "SELECT 'getenv(' AS value",
        "SELECT 'it''s read_csv(' AS value",
        "SELECT 1 -- read_csv('data.csv')",
        """
        SELECT 1
        /* read_parquet('data.parquet') */
        """,
    ],
)
def test_external_access_names_inside_literals_and_comments_are_allowed(
    query: str,
) -> None:
    AnalyticalQueryValidator().validate(query)


def test_masks_unterminated_single_quoted_literal_preserving_newline() -> None:
    query = "SELECT 'external\nread_csv("

    masked = _mask_sql_literals_and_comments(query)

    assert masked == "SELECT          \n         "


def test_nested_block_comment_does_not_trigger_external_access_block() -> None:
    query = "SELECT 1 /* outer /* inner */ read_csv('data.csv') */"

    AnalyticalQueryValidator().validate(query)


@pytest.mark.parametrize(
    "query",
    [
        "SELECT 1 /* outer /* inner */ outer */",
        "SELECT 1 /* outer\n/* inner */\nouter */",
        "SELECT 1 /* outer /* inner */",
    ],
)
def test_masks_nested_block_comments(query: str) -> None:
    masked = _mask_sql_literals_and_comments(query)

    expected = "SELECT 1" + "".join(
        character if character in "\r\n" else " "
        for character in query[len("SELECT 1") :]
    )

    assert masked == expected
    assert len(masked) == len(query)


def test_masks_unterminated_block_comment_preserving_newline() -> None:
    query = "SELECT 1 /* external\nread_csv("

    masked = _mask_sql_literals_and_comments(query)

    assert masked == "SELECT 1            \n         "


@pytest.mark.parametrize(
    "query",
    [
        """SELECT * FROM "read_csv"('data.csv')""",
        """SELECT * FROM "read_csv_auto"('data.csv')""",
        """SELECT * FROM "read_parquet"('data.parquet')""",
        """SELECT * FROM "read_json"('data.json')""",
        """SELECT * FROM "read_json_auto"('data.json')""",
        """SELECT * FROM "read_text"('data.txt')""",
        """SELECT * FROM "read_ndjson"('data.ndjson')""",
        """SELECT * FROM "read_ndjson_auto"('data.ndjson')""",
        """SELECT "read_blob"('data.txt')""",
        """SELECT * FROM "glob"('*')""",
        """SELECT "getenv"('PATH')""",
    ],
)
def test_rejects_quoted_external_access_functions(
    query: str,
) -> None:
    with pytest.raises(
        QueryValidationError,
        match="External data access is not allowed",
    ):
        AnalyticalQueryValidator().validate(query)


@pytest.mark.parametrize(
    "error",
    [
        ParseError("SQL parsing failed"),
        ValueError("SQL scope analysis failed"),
    ],
)
def test_dataset_relation_validation_rejects_sql_analysis_errors(
    error: Exception,
) -> None:
    with (
        patch(
            "verisight.execution.validation.sqlglot.parse_one",
            side_effect=error,
        ),
        pytest.raises(
            QueryValidationError,
            match="Dataset access is not allowed: SQL analysis failed",
        ),
    ):
        validate_dataset_relations(
            "SELECT * FROM orders",
            frozenset({"orders"}),
        )


def test_dataset_relation_validation_rejects_unresolved_scopes() -> None:
    with (
        patch(
            "verisight.execution.validation.traverse_scope",
            return_value=[],
        ),
        pytest.raises(
            QueryValidationError,
            match="Dataset access is not allowed: SQL scopes could not be resolved",
        ),
    ):
        validate_dataset_relations(
            "SELECT * FROM orders",
            frozenset({"orders"}),
        )


def test_dataset_relation_validation_rejects_unsupported_source() -> None:
    class UnsupportedScope:
        selected_sources = {"unsupported": (None, object())}

    with (
        patch(
            "verisight.execution.validation.traverse_scope",
            return_value=[UnsupportedScope()],
        ),
        pytest.raises(
            QueryValidationError,
            match="Dataset access is not allowed: unsupported SQL source",
        ),
    ):
        validate_dataset_relations(
            "SELECT * FROM orders",
            frozenset({"orders"}),
        )


@pytest.mark.parametrize(
    "query",
    [
        "SELECT CAST(current_schemas(true) AS VARCHAR)",
        "SELECT CAST(CuRrEnT_ScHeMaS/* comment */(false) AS VARCHAR)",
        'SELECT CAST("CURRENT_SCHEMAS"(true) AS VARCHAR)',
        "SELECT CAST(main.current_schemas(true) AS VARCHAR)",
        'SELECT CAST(main."CURRENT_SCHEMAS"(true) AS VARCHAR)',
        "SELECT (SELECT CAST(current_schemas(true) AS VARCHAR))",
        "WITH unused AS (SELECT current_schemas(true)) SELECT 1",
        "SELECT name FROM UNNEST(current_schemas(true)) AS schemas(name)",
        "SELECT CASE WHEN false THEN CAST(current_schemas(true) AS VARCHAR) "
        "ELSE 'unused' END",
    ],
    ids=[
        "cast-to-scalar",
        "mixed-case-comment",
        "quoted",
        "qualified",
        "qualified-quoted",
        "nested-select",
        "unused-cte",
        "unnest",
        "unreachable-expression",
    ],
)
def test_schema_list_functions_are_rejected_before_connection(query: str) -> None:
    dataset = LoadedDataset(tables=[])
    executor = DuckDBExecutor(
        memory_limit_mb=64, execution_timeout_seconds=1, max_result_rows=20
    )
    with patch("verisight.execution.engine.duckdb.connect") as connect:
        with pytest.raises(QueryValidationError, match="internal metadata function"):
            executor.execute(dataset, query)
        outcome = run_public_operation(lambda: executor.execute(dataset, query))
        connect.assert_not_called()
    assert not outcome.succeeded
    assert outcome.value is None
    assert outcome.error is not None
    assert outcome.error.code is ErrorCode.QUERY_VALIDATION_ERROR
    assert query not in outcome.error.message


def test_schema_function_names_in_data_literals_and_comments_remain_queryable() -> None:
    data = pd.DataFrame({"current_schemas": [7]})
    original = data.copy(deep=True)
    dataset = LoadedDataset(
        tables=[
            LoadedTable(
                name="orders",
                data=data,
                source=SourceMetadata(Path("orders.csv"), "orders.csv", ".csv", 1),
            )
        ]
    )
    result = DuckDBExecutor(
        memory_limit_mb=64, execution_timeout_seconds=1, max_result_rows=20
    ).execute(
        dataset,
        "SELECT \"current_schemas\", 'current_schemas(true)' AS note FROM orders "
        "/* current_schemas(true) */",
    )
    assert result.columns == ("current_schemas", "note")
    assert result.rows == ((7, "current_schemas(true)"),)
    pd.testing.assert_frame_equal(data, original)


def _population_context() -> QueryContext:
    from verisight.execution.context import ObservedCategoryValues

    return QueryContext(
        relations=(),
        observed_categories=(
            ObservedCategoryValues(
                "generation", "kind", ("production", "test", "calibration")
            ),
        ),
    )


@pytest.mark.parametrize(
    "sql,status",
    [
        ("SELECT SUM(amount) FROM generation", "review_required"),
        ("SELECT SUM(amount) FROM generation WHERE kind != 'test'", "review_required"),
        ("SELECT SUM(amount) FROM generation WHERE kind <> 'test'", "review_required"),
        (
            "SELECT SUM(amount) FROM generation WHERE kind NOT IN ('test')",
            "review_required",
        ),
        (
            "SELECT SUM(amount) FROM generation WHERE kind IN ('test', 'production')",
            "review_required",
        ),
        (
            "SELECT SUM(amount) FROM generation WHERE kind = 'production'",
            "no_warning_detected",
        ),
        (
            "SELECT SUM(amount) FROM generation WHERE 'production' = kind",
            "no_warning_detected",
        ),
        (
            "SELECT SUM(amount) FROM generation WHERE kind IN ('production')",
            "no_warning_detected",
        ),
        (
            "SELECT SUM(g.amount) FROM generation g WHERE (g.kind='production' "
            "AND g.amount>0)",
            "no_warning_detected",
        ),
        (
            "SELECT SUM(g.amount) FROM generation g WHERE g.kind != 'test' AND "
            "g.id IN (SELECT id FROM reviews WHERE decision='approved')",
            "review_required",
        ),
        (
            "SELECT SUM(g.amount) FROM generation g WHERE g.kind = "
            "'production' AND EXISTS (SELECT 1 FROM reviews r WHERE r.id=g.id)",
            "no_warning_detected",
        ),
        (
            "SELECT SUM(amount) FROM generation WHERE kind='production' OR amount>0",
            "not_assessed",
        ),
        (
            "SELECT SUM(CASE WHEN kind='production' THEN amount ELSE 0 END) "
            "FROM generation",
            "not_assessed",
        ),
        (
            "SELECT SUM(amount) FROM generation WHERE lower(kind)='production'",
            "not_assessed",
        ),
        (
            "SELECT SUM(amount) FROM generation WHERE kind IN (SELECT kind "
            "FROM reviews)",
            "not_assessed",
        ),
        ("SELECT SUM(amount) FROM generation WHERE kind=1", "not_assessed"),
        ("SELECT SUM(amount) FROM generation WHERE kind=other", "not_assessed"),
        ("SELECT SUM(amount) FROM generation WHERE NOT(kind='test')", "not_assessed"),
        (
            "SELECT SUM(amount) FROM generation WHERE x.kind='production'",
            "review_required",
        ),
        ("SELECT SUM(amount) FROM generation WHERE kind IN (1)", "not_assessed"),
        ("SELECT SUM(amount) FROM generation WHERE amount IN (1)", "review_required"),
        ("SELECT SUM(amount) FROM generation WHERE 1=1", "review_required"),
        ("SELECT SUM(amount) FROM generation WHERE 1<>2", "review_required"),
        ("SELECT SUM(amount) FROM generation WHERE kind='test'", "review_required"),
        ("SELECT SUM(amount) FROM generation WHERE amount>0", "review_required"),
        (
            "SELECT SUM(amount) FROM generation g WHERE EXISTS(SELECT 1 FROM "
            "reviews r WHERE r.kind='production')",
            "review_required",
        ),
        (
            "SELECT SUM(amount) FROM generation WHERE EXISTS(SELECT 1 FROM "
            "reviews WHERE kind='production')",
            "not_assessed",
        ),
        ("SELECT SUM(amount) FROM other", "not_assessed"),
        ("SELECT 1", "not_assessed"),
        ("SELECT SUM(amount) FROM (SELECT * FROM generation) g", "not_assessed"),
        (
            "WITH g AS (SELECT * FROM generation) SELECT SUM(amount) FROM g",
            "not_assessed",
        ),
        (
            "SELECT SUM(g.amount) FROM generation g JOIN reviews r ON r.id=g.id",
            "not_assessed",
        ),
        ("SELECT 1 UNION SELECT 2", "not_assessed"),
        ("SELECT * FROM main.generation", "not_assessed"),
        ("SELECT * FROM catalog.main.generation", "not_assessed"),
        ("SELECT 1; SELECT 2", "not_assessed"),
        ("SELECT (", "not_assessed"),
    ],
)
def test_population_review_is_conservative(sql: str, status: str) -> None:
    from verisight.execution.validation import review_population

    result = review_population(
        "Total production output. Exclude test records.", sql, _population_context()
    )
    assert result.status == status
    assert result.task_semantics_verified is False
    assert bool(result.warnings) == (status == "review_required")
    if result.warnings:
        assert result.warnings[0].mentioned_value == "production"


@pytest.mark.parametrize(
    "question",
    [
        "Exclude production records",
        "Excluding all production",
        "Without production",
        "Not production",
        "Except 'production'",
        "non-production readings",
        "Sum counterproduction",
        "Compare production and calibration",
        "Sum all readings",
    ],
)
def test_population_review_does_not_guess_negative_or_ambiguous_intent(
    question: str,
) -> None:
    from verisight.execution.validation import review_population

    assert (
        review_population(
            question, "SELECT SUM(amount) FROM generation", _population_context()
        ).status
        == "not_assessed"
    )


def test_population_review_caller_policy_and_shared_category() -> None:
    from dataclasses import replace

    from verisight.execution.context import ObservedCategoryValues, PopulationFilter
    from verisight.execution.validation import (
        _question_mentions_category,
        review_population,
    )

    context = _population_context()
    sql = "SELECT SUM(amount) FROM generation WHERE kind != 'test'"
    scoped = replace(
        context, population=(PopulationFilter("generation", "kind", ("production",)),)
    )
    assert (
        review_population("production output", sql, scoped).status
        == "no_warning_detected"
    )
    unrelated = replace(
        context, population=(PopulationFilter("other", "kind", ("production",)),)
    )
    assert (
        review_population("production output", sql, unrelated).status
        == "review_required"
    )
    shared = replace(
        context,
        observed_categories=(
            *context.observed_categories,
            ObservedCategoryValues("generation", "other", ("production", "test")),
        ),
    )
    assert review_population("production output", sql, shared).status == "not_assessed"
    assert not _question_mentions_category("all values", " ")


@pytest.mark.parametrize(
    "sql,status",
    [
        ("SELECT COUNT(*) FROM accounts", "review_required"),
        ("SELECT COUNT(outcome) FROM accounts", "review_required"),
        (
            "SELECT 100.0*COUNT(CASE WHEN outcome='renewed' THEN 1 END) "
            "/ NULLIF(COUNT(outcome),0) FROM accounts "
            "WHERE cycle=2026 AND state='live' "
            "AND outcome IN ('renewed','declined')",
            "review_required",
        ),
        ("SELECT COUNT(DISTINCT account_id) FROM accounts", "no_warning_detected"),
        (
            "SELECT 100.0*COUNT(DISTINCT CASE WHEN outcome='renewed' "
            "THEN account_id END)/NULLIF(COUNT(DISTINCT account_id),0) "
            "FROM accounts WHERE cycle=2026 AND state='live' "
            "AND outcome IN ('renewed','declined')",
            "no_warning_detected",
        ),
        (
            "SELECT COUNT(DISTINCT account_id)+COUNT(*) FROM accounts",
            "review_required",
        ),
        (
            "SELECT COUNT(DISTINCT outcome) FROM accounts",
            "no_warning_detected",
        ),
        (
            "SELECT COUNT(DISTINCT account_id) FROM accounts ORDER BY COUNT(*)",
            "no_warning_detected",
        ),
        (
            "SELECT COUNT(*) FILTER(WHERE outcome='renewed') FROM accounts",
            "review_required",
        ),
        ("SELECT SUM(amount)/COUNT(*) FROM accounts", "not_assessed"),
        ("SELECT SUM(amount) FROM accounts ORDER BY COUNT(*)", "not_assessed"),
        ("SELECT COUNT_IF(outcome='renewed') FROM accounts", "not_assessed"),
        ("SELECT COUNT(*) OVER() FROM accounts", "not_assessed"),
        ("SELECT COUNT(*) FROM accounts GROUP BY state", "not_assessed"),
        ("SELECT COUNT(*) FROM accounts HAVING COUNT(*)>0", "not_assessed"),
        (
            "SELECT COUNT(*) FROM accounts QUALIFY ROW_NUMBER() OVER()=1",
            "not_assessed",
        ),
        ("SELECT DISTINCT COUNT(*) FROM accounts", "not_assessed"),
        ("SELECT COUNT(*), COUNT(DISTINCT account_id) FROM accounts", "not_assessed"),
        (
            "WITH ids AS (SELECT DISTINCT account_id FROM accounts) "
            "SELECT COUNT(*) FROM ids",
            "not_assessed",
        ),
        (
            "SELECT COUNT(*) FROM (SELECT DISTINCT account_id FROM accounts) a",
            "not_assessed",
        ),
        (
            "SELECT COUNT(*) FROM accounts WHERE account_id IN "
            "(SELECT account_id FROM approved)",
            "not_assessed",
        ),
        (
            "SELECT COUNT(*) FROM accounts a JOIN approved b ON a.id=b.id",
            "not_assessed",
        ),
        ("SELECT COUNT(*)", "not_assessed"),
        (
            "SELECT COUNT(*) FROM accounts UNION SELECT COUNT(*) FROM approved",
            "not_assessed",
        ),
        ("SELECT COUNT(*) FROM accounts; SELECT 1", "not_assessed"),
        ("SELECT (", "not_assessed"),
    ],
)
def test_counting_grain_advisory_is_narrow(sql: str, status: str) -> None:
    from verisight.execution.validation import review_counting_grain

    review = review_counting_grain("Count account identities, not rows.", sql)
    assert review.status == status
    assert review.task_semantics_verified is False
    assert review.warnings == (
        ("row_counts_for_identity_request",) if status == "review_required" else ()
    )


@pytest.mark.parametrize(
    "question,assessed",
    [
        ("Count learner identities, not enrolment rows.", True),
        ("COUNT DISTINCT ENTITIES, NOT SOURCE ROWS.", True),
        ("Count account identities not rows.", True),
        ("Count identities, not rows.", True),
        ("Count rows, not identities.", False),
        ("Count events.", False),
        ("Do not count identities, not rows.", False),
        ("Never count account identities, not rows.", False),
        ("Avoid count account identities, not rows.", False),
        ("Don't count account identities, not rows.", False),
        ("Do not count entities, not rows. Count identities, not rows.", True),
    ],
)
def test_counting_grain_advisory_requires_positive_explicit_intent(
    question: str, assessed: bool
) -> None:
    from verisight.execution.validation import review_counting_grain

    review = review_counting_grain(question, "SELECT COUNT(*) FROM accounts")
    assert review.status == ("review_required" if assessed else "not_assessed")
