"""Regression tests for budget-aware investigation compaction."""

from datetime import date
from decimal import Decimal
from typing import cast
from unittest.mock import MagicMock

import pytest

from verisight.analysis.result import DatasetAnalysisResult
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_compaction import (
    InvestigationCompaction,
)
from verisight.execution.models import QueryResult, QueryRow
from verisight.execution.observations import QueryObservation
from verisight.execution.prompt_budget import PromptBudgetExceededError


def _state(
    *,
    observations: tuple[QueryObservation, ...] = (),
    question: str = "Investigate revenue.",
) -> InvestigationState:
    """Build an investigation state with a minimal analysis fixture."""

    analysis = MagicMock(spec=DatasetAnalysisResult)

    analysis.summary.table_count = 0
    analysis.summary.total_row_count = 0
    analysis.summary.total_column_count = 0
    analysis.summary.issue_count = 0
    analysis.summary.info_issue_count = 0
    analysis.summary.warning_issue_count = 0
    analysis.summary.error_issue_count = 0

    analysis.insights = ()
    analysis.analysis.issues = ()
    analysis.analysis.schema.tables = ()

    return InvestigationState(
        question=question,
        analysis=cast(DatasetAnalysisResult, analysis),
        observations=observations,
    )


def _observation(
    index: int,
    *,
    rows: tuple[QueryRow, ...] | None = None,
) -> QueryObservation:
    """Build a query observation with correctly typed result rows."""

    if rows is None:
        rows = tuple((f"value-{index}-{row_index}",) for row_index in range(5))

    return QueryObservation(
        question=f"Question {index}",
        sql=f"SELECT value FROM table_{index}",
        result=QueryResult(
            columns=("value",),
            rows=rows,
        ),
    )


def _candidate_lengths(
    state: InvestigationState,
) -> tuple[int, int, int]:
    """Measure the three row-retention prompt candidates."""

    compaction = InvestigationCompaction(
        max_prompt_chars=1_000_000,
    )

    full_prompt = compaction.investigator_prompt(state)

    marker = "\n\nEXECUTED OBSERVATIONS\nTotal executed observations:"

    prefix = full_prompt.split(marker, maxsplit=1)[0]

    def candidate_length(row_limit: int) -> int:
        context = compaction._observation_context(
            state,
            row_limit=row_limit,
            max_observations=None,
        )

        return len(prefix + "\n\n" + context)

    return (
        candidate_length(3),
        candidate_length(1),
        candidate_length(0),
    )


def test_compaction_accepts_positive_budget() -> None:
    compaction = InvestigationCompaction(
        max_prompt_chars=1_000_000,
    )

    prompt = compaction.investigator_prompt(_state())

    assert "Investigate revenue." in prompt
    assert "EXECUTED OBSERVATIONS" in prompt
    assert len(prompt) <= 1_000_000


def test_compaction_rejects_invalid_budget() -> None:
    with pytest.raises(ValueError):
        InvestigationCompaction(max_prompt_chars=0)


def test_compaction_preserves_visible_rows() -> None:
    state = _state(
        observations=(
            _observation(
                1,
                rows=(("first",), ("second",)),
            ),
        )
    )

    prompt = InvestigationCompaction().investigator_prompt(state)

    assert "OBSERVATION 1" in prompt
    assert '["first"]' in prompt
    assert '["second"]' in prompt
    assert "Rows omitted:" not in prompt


def test_compaction_reduces_rows_to_one() -> None:
    state = _state(
        observations=(_observation(1),),
    )

    three_rows, one_row, zero_rows = _candidate_lengths(state)

    assert three_rows > one_row > zero_rows

    prompt = InvestigationCompaction(
        max_prompt_chars=one_row,
    ).investigator_prompt(state)

    assert len(prompt) <= one_row
    assert '["value-1-0"]' in prompt
    assert '["value-1-1"]' not in prompt
    assert "Rows omitted: 4 of 5" in prompt


def test_compaction_reduces_rows_to_zero() -> None:
    state = _state(
        observations=(_observation(1),),
    )

    _, one_row, zero_rows = _candidate_lengths(state)

    assert one_row > zero_rows

    prompt = InvestigationCompaction(
        max_prompt_chars=zero_rows,
    ).investigator_prompt(state)

    assert len(prompt) <= zero_rows
    assert "OBSERVATION 1" in prompt
    assert "Rows omitted: 5 of 5" in prompt
    assert '["value-1-0"]' not in prompt


def test_compaction_removes_older_observations() -> None:
    state = _state(
        observations=(
            _observation(1),
            _observation(2),
            _observation(3),
        )
    )

    compaction = InvestigationCompaction(
        max_prompt_chars=1_000_000,
    )

    all_observations = compaction._observation_context(
        state,
        row_limit=0,
        max_observations=None,
    )

    latest_two = compaction._observation_context(
        state,
        row_limit=0,
        max_observations=2,
    )

    full_prompt = compaction.investigator_prompt(state)

    marker = "\n\nEXECUTED OBSERVATIONS\nTotal executed observations:"

    prefix = full_prompt.split(marker, maxsplit=1)[0]

    budget = len(prefix + "\n\n" + latest_two)

    assert len(prefix + "\n\n" + all_observations) > budget

    prompt = InvestigationCompaction(
        max_prompt_chars=budget,
    ).investigator_prompt(state)

    assert "EVIDENCE COMPACTED: 1 of 3" in prompt
    assert "OBSERVATION 1\n" not in prompt
    assert "OBSERVATION 2\n" in prompt
    assert "OBSERVATION 3\n" in prompt
    assert len(prompt) <= budget


def test_compaction_can_omit_all_observations() -> None:
    state = _state(
        observations=(
            _observation(1),
            _observation(2),
        )
    )

    compaction = InvestigationCompaction(
        max_prompt_chars=1_000_000,
    )

    all_omitted = compaction._observation_context(
        state,
        row_limit=0,
        max_observations=0,
    )

    full_prompt = compaction.investigator_prompt(state)

    marker = "\n\nEXECUTED OBSERVATIONS\nTotal executed observations:"

    prefix = full_prompt.split(marker, maxsplit=1)[0]

    budget = len(prefix + "\n\n" + all_omitted)

    prompt = InvestigationCompaction(
        max_prompt_chars=budget,
    ).investigator_prompt(state)

    assert "EVIDENCE COMPACTED: 2 of 2" in prompt
    assert "OBSERVATION 1\n" not in prompt
    assert "OBSERVATION 2\n" not in prompt
    assert len(prompt) <= budget


def test_compaction_raises_when_minimum_exceeds_budget() -> None:
    state = _state(
        observations=(_observation(1),),
    )

    with pytest.raises(PromptBudgetExceededError):
        InvestigationCompaction(
            max_prompt_chars=1,
        ).investigator_prompt(state)


def test_compaction_serializes_non_json_sql_scalars() -> None:
    state = _state(
        observations=(
            _observation(
                1,
                rows=(
                    (
                        Decimal("12.50"),
                        date(2026, 1, 2),
                    ),
                ),
            ),
        )
    )

    prompt = InvestigationCompaction().investigator_prompt(state)

    assert "12.50" in prompt
    assert "2026-01-02" in prompt


def test_synthesis_prompt_contains_all_result_rows() -> None:
    rows: tuple[QueryRow, ...] = tuple((index,) for index in range(125))

    state = _state(observations=(_observation(1, rows=rows),))

    prompt = InvestigationCompaction().synthesis_prompt(state)

    assert "Row count: 125" in prompt
    assert "[0]" in prompt
    assert "[124]" in prompt
    assert "Rows omitted:" not in prompt


def test_synthesis_prompt_rejects_oversized_evidence() -> None:
    state = _state(
        observations=(
            _observation(
                1,
                rows=(("X" * 10_000,),),
            ),
        )
    )

    with pytest.raises(PromptBudgetExceededError):
        InvestigationCompaction(
            max_prompt_chars=1_000,
        ).synthesis_prompt(state)


def test_synthesis_prompt_handles_no_observations() -> None:
    prompt = InvestigationCompaction().synthesis_prompt(_state())

    assert "EXECUTED OBSERVATIONS" in prompt
    assert "None" in prompt


def test_observation_context_keeps_latest_observation() -> None:
    state = _state(
        observations=(
            _observation(1),
            _observation(2),
            _observation(3),
        )
    )

    context = InvestigationCompaction._observation_context(
        state,
        row_limit=1,
        max_observations=1,
    )

    assert "EVIDENCE COMPACTED: 2 of 3" in context
    assert "OBSERVATION 3\n" in context
    assert "OBSERVATION 1\n" not in context
    assert "OBSERVATION 2\n" not in context
    assert '["value-3-0"]' in context


def test_observation_context_handles_empty_result() -> None:
    state = _state(observations=(_observation(1, rows=()),))

    context = InvestigationCompaction._observation_context(
        state,
        row_limit=3,
        max_observations=None,
    )

    assert "Row count: 0" in context
    assert "Rows omitted:" not in context
