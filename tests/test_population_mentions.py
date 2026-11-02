"""Category-mention rules for the advisory population review."""

import pytest

from verisight.execution.context import ObservedCategoryValues, QueryContext
from verisight.execution.validation import (
    _question_assigns_category,
    _question_mentions_category,
    review_population,
)


def _context() -> QueryContext:
    return QueryContext(
        relations=(),
        observed_categories=(
            ObservedCategoryValues("readings", "kind", ("double", "single")),
            ObservedCategoryValues("readings", "flagged", ("no", "unknown", "yes")),
            ObservedCategoryValues("readings", "verified", ("no", "yes")),
            ObservedCategoryValues("readings", "review_state", ("no", "yes")),
        ),
    )


def _status(question: str, sql: str) -> str:
    return review_population(question, sql, _context()).status


@pytest.mark.parametrize(
    "question",
    [
        "What is the mean amount? Report it as a single number.",
        "What is the mean amount, and return it as a single value?",
        "Give the mean amount as a single figure; nothing else.",
        "Mean amount. Express the answer as one single number.",
    ],
)
def test_reporting_format_words_are_not_category_mentions(question: str) -> None:
    assert not _question_mentions_category(question, "single")
    assert _status(question, "SELECT AVG(amount) FROM readings") == "not_assessed"


def test_category_before_the_format_complement_is_still_reviewed() -> None:
    question = "Mean amount of single readings. Report it as a single number."
    assert _question_mentions_category(question, "single")
    unfiltered = review_population(
        question, "SELECT AVG(amount) FROM readings", _context()
    )
    assert unfiltered.status == "review_required"
    assert unfiltered.warnings[0].column == "kind"
    assert unfiltered.warnings[0].mentioned_value == "single"
    filtered = "SELECT AVG(amount) FROM readings WHERE kind = 'single'"
    assert _status(question, filtered) == "no_warning_detected"


def test_report_without_as_keeps_the_mention() -> None:
    question = "Report the mean amount for single readings."
    assert _question_mentions_category(question, "single")


@pytest.mark.parametrize(
    "phrase",
    [
        "flagged is no",
        "flagged status is no",
        "flagged = 'no'",
        "flagged == no",
        "flagged equals no",
        "Flagged equal to NO",
    ],
)
def test_shared_value_is_attributed_to_the_named_column(phrase: str) -> None:
    question = f"Among readings where {phrase}, what is the mean amount?"
    trap = review_population(
        question, "SELECT AVG(amount) FROM readings WHERE flagged <> 'yes'", _context()
    )
    assert trap.status == "review_required"
    assert trap.warnings[0].column == "flagged"
    assert trap.warnings[0].mentioned_value == "no"
    assert trap.task_semantics_verified is False
    control = "SELECT AVG(amount) FROM readings WHERE flagged = 'no'"
    assert _status(question, control) == "no_warning_detected"


def test_underscored_column_names_match_spaced_mentions() -> None:
    question = "Where the review state is no, what is the mean amount?"
    result = review_population(question, "SELECT AVG(amount) FROM readings", _context())
    assert result.status == "review_required"
    assert result.warnings[0].column == "review_state"


@pytest.mark.parametrize(
    "question",
    [
        # Shared value with no column named for it.
        "Mean amount for readings with no review",
        # Shared value named for two columns.
        "Mean amount where flagged is no and verified is no",
        # Different values are still ambiguous, even when one is attributed.
        "Mean amount of single readings where flagged is no",
        # A column/value statement inside the format complement is ignored.
        "Mean amount. Report it as flagged is no.",
    ],
)
def test_ambiguous_mentions_remain_unassessed(question: str) -> None:
    assert _status(question, "SELECT AVG(amount) FROM readings") == "not_assessed"


@pytest.mark.parametrize(
    ("column", "value"), [(" ", "no"), ("_", "no"), ("flagged", " ")]
)
def test_blank_assignment_parts_never_match(column: str, value: str) -> None:
    assert not _question_assigns_category("flagged is no", column, value)
