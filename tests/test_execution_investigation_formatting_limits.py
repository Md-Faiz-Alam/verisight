"""Regression tests for bounded investigation result formatting."""

import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_formatting import (
    InvestigationStateFormatter,
)
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile


def _state_with_result(result: QueryResult) -> InvestigationState:
    """Build a deterministic investigation state with one observation."""

    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(),
    )

    observation = QueryObservation(
        question="Show the measurements.",
        sql="SELECT measurement FROM observations",
        result=result,
    )

    return InvestigationState(
        question="What measurements are available?",
        analysis=AnalysisResultBuilder().build(analysis),
        observations=(observation,),
    )


@pytest.mark.parametrize("limit", [0, -1, -100])
def test_rejects_non_positive_row_limit(limit: int) -> None:
    with pytest.raises(
        ValueError,
        match="Maximum result rows must be positive.",
    ):
        InvestigationStateFormatter(max_result_rows=limit)


def test_default_limit_displays_one_hundred_rows() -> None:
    result = QueryResult(
        columns=("measurement",),
        rows=tuple((index,) for index in range(150)),
    )

    formatted = InvestigationStateFormatter().format(_state_with_result(result))

    assert "Row count: 150" in formatted
    assert "[0]" in formatted
    assert "[99]" in formatted
    assert "\n[100]\n" not in formatted
    assert "Rows omitted: 50 of 150" in formatted


def test_custom_limit_displays_requested_number_of_rows() -> None:
    result = QueryResult(
        columns=("measurement",),
        rows=((10,), (20,), (30,), (40,)),
    )

    formatted = InvestigationStateFormatter(max_result_rows=2).format(
        _state_with_result(result)
    )

    assert "Row count: 4" in formatted
    assert "\n[10]\n" in formatted
    assert "\n[20]\n" in formatted
    assert "\n[30]\n" not in formatted
    assert "Rows omitted: 2 of 4" in formatted


def test_result_at_limit_is_not_truncated() -> None:
    result = QueryResult(
        columns=("measurement",),
        rows=((10,), (20,)),
    )

    formatted = InvestigationStateFormatter(max_result_rows=2).format(
        _state_with_result(result)
    )

    assert "[10]" in formatted
    assert "[20]" in formatted
    assert "Rows omitted:" not in formatted


def test_small_result_preserves_existing_format() -> None:
    result = QueryResult(
        columns=("category", "measurement"),
        rows=(("A", 12.5), ("B", 14.0)),
    )

    formatted = InvestigationStateFormatter().format(_state_with_result(result))

    assert (
        'Columns: category, measurement\nRow count: 2\nRows:\n["A",12.5]\n["B",14.0]'
    ) in formatted

    assert "Rows omitted:" not in formatted


def test_empty_result_preserves_existing_format() -> None:
    result = QueryResult(
        columns=("measurement",),
        rows=(),
    )

    formatted = InvestigationStateFormatter(max_result_rows=1).format(
        _state_with_result(result)
    )

    assert "Columns: measurement\nRows: None" in formatted
    assert "Rows omitted:" not in formatted


def test_truncation_preserves_underlying_evidence() -> None:
    result = QueryResult(
        columns=("measurement",),
        rows=((10,), (20,), (30,)),
    )

    state = _state_with_result(result)

    formatted = InvestigationStateFormatter(max_result_rows=1).format(state)

    assert "Rows omitted: 2 of 3" in formatted
    assert result.rows == ((10,), (20,), (30,))
    assert state.observations[0].result is result
    assert state.observation_count == 1


def test_bounded_formatting_is_deterministic() -> None:
    result = QueryResult(
        columns=("measurement",),
        rows=((10,), (20,), (30,)),
    )

    state = _state_with_result(result)
    formatter = InvestigationStateFormatter(max_result_rows=2)

    assert formatter.format(state) == formatter.format(state)


def test_row_limit_applies_to_each_observation() -> None:
    result = QueryResult(
        columns=("measurement",),
        rows=((10,), (20,), (30,)),
    )

    state = _state_with_result(result)

    second_observation = QueryObservation(
        question="Show another measurement.",
        sql="SELECT measurement FROM observations",
        result=result,
    )

    state = state.add_observation(second_observation)

    formatted = InvestigationStateFormatter(max_result_rows=1).format(state)

    assert "OBSERVATION 1" in formatted
    assert "OBSERVATION 2" in formatted
    assert formatted.count("Rows omitted: 2 of 3") == 2
