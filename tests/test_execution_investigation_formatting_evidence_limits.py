"""Tests for bounded investigation evidence and failure formatting."""

from dataclasses import replace

import pytest

from verisight.analysis.insights import (
    AnalysisInsight,
    InsightScope,
    InsightType,
)
from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import (
    AnalysisResultBuilder,
)
from verisight.evidence import EvidenceInput
from verisight.execution.investigation import (
    FailedQueryAttempt,
    InvestigationState,
)
from verisight.execution.investigation_formatting import (
    InvestigationStateFormatter,
)
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile
from verisight.quality.models import (
    QualityIssue,
    QualityIssueType,
    QualityScope,
    QualitySeverity,
)


def _build_state(
    *,
    insights: tuple[AnalysisInsight, ...] = (),
    issues: tuple[QualityIssue, ...] = (),
    attempts: tuple[FailedQueryAttempt, ...] = (),
) -> InvestigationState:
    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=issues,
    )

    result = AnalysisResultBuilder().build(analysis)
    result = replace(result, insights=insights)

    return InvestigationState(
        question="What happened?",
        analysis=result,
        failed_attempts=attempts,
    )


def _insight(message: str, evidence: EvidenceInput) -> AnalysisInsight:
    return AnalysisInsight(
        insight_type=InsightType.DATA_QUALITY,
        scope=InsightScope.TABLE,
        message=message,
        table_name="Observations",
        relation_name="observations",
        column_name=None,
        evidence=evidence,
    )


def _issue(message: str, evidence: EvidenceInput) -> QualityIssue:
    return QualityIssue(
        issue_type=QualityIssueType.MISSING_VALUES,
        severity=QualitySeverity.WARNING,
        scope=QualityScope.TABLE,
        table_name="Observations",
        relation_name="observations",
        column_name=None,
        message=message,
        affected_count=1,
        affected_ratio=0.1,
        evidence=evidence,
    )


def _attempt(message: str) -> FailedQueryAttempt:
    return FailedQueryAttempt(
        question="What is the measurement?",
        error_type="QueryRuntimeError",
        message=message,
    )


@pytest.mark.parametrize(
    ("parameter", "value", "expected"),
    [
        ("max_insights", 0, "Maximum insights"),
        ("max_quality_issues", -1, "Maximum quality issues"),
        ("max_failed_attempts", 0, "Maximum failed attempts"),
        ("max_message_chars", 0, "Maximum message characters"),
        ("max_evidence_chars", -1, "Maximum evidence characters"),
        ("max_error_chars", 0, "Maximum error characters"),
    ],
)
def test_rejects_invalid_limits(
    parameter: str,
    value: int,
    expected: str,
) -> None:
    options = {parameter: value}

    with pytest.raises(ValueError, match=expected):
        InvestigationStateFormatter(**options)


def test_limits_insight_count() -> None:
    state = _build_state(
        insights=tuple(_insight(f"Insight {index}", {}) for index in range(4)),
    )

    formatted = InvestigationStateFormatter(
        max_insights=2,
    ).format(state)

    assert "Insight 0" in formatted
    assert "Insight 1" in formatted
    assert "Insight 2" not in formatted
    assert "Insights omitted: 2 of 4" in formatted
    assert len(state.analysis.insights) == 4


def test_limits_quality_finding_count() -> None:
    state = _build_state(
        issues=tuple(_issue(f"Issue {index}", {}) for index in range(3)),
    )

    formatted = InvestigationStateFormatter(
        max_quality_issues=1,
    ).format(state)

    assert "Issue 0" in formatted
    assert "Issue 1" not in formatted
    assert "Quality findings omitted: 2 of 3" in formatted
    assert len(state.analysis.analysis.issues) == 3


def test_limits_failed_attempt_count() -> None:
    state = _build_state(
        attempts=(
            _attempt("First failure"),
            _attempt("Second failure"),
            _attempt("Third failure"),
        ),
    )

    formatted = InvestigationStateFormatter(
        max_failed_attempts=1,
    ).format(state)

    assert "First failure" in formatted
    assert "Second failure" not in formatted
    assert "Failed attempts omitted: 2 of 3" in formatted
    assert state.failed_attempt_count == 3


def test_truncates_insight_message() -> None:
    state = _build_state(
        insights=(_insight("ABCDEFGHIJ", {}),),
    )

    formatted = InvestigationStateFormatter(
        max_message_chars=4,
    ).format(state)

    assert "ABCD [TRUNCATED: 6 characters omitted]" in formatted
    assert "ABCDEFGHIJ" not in formatted


def test_truncates_quality_message() -> None:
    state = _build_state(
        issues=(_issue("ABCDEFGHIJ", {}),),
    )

    formatted = InvestigationStateFormatter(
        max_message_chars=5,
    ).format(state)

    assert "ABCDE [TRUNCATED: 5 characters omitted]" in formatted


def test_truncates_failed_attempt_error() -> None:
    state = _build_state(
        attempts=(_attempt("ABCDEFGHIJ"),),
    )

    formatted = InvestigationStateFormatter(
        max_error_chars=3,
    ).format(state)

    assert "Error: ABC [TRUNCATED: 7 characters omitted]" in formatted
    assert state.failed_attempts[0].message == "ABCDEFGHIJ"


def test_omits_oversized_insight_evidence() -> None:
    state = _build_state(
        insights=(_insight("Insight", {"value": "X" * 100}),),
    )

    formatted = InvestigationStateFormatter(
        max_evidence_chars=20,
    ).format(state)

    assert "[EVIDENCE OMITTED:" in formatted
    assert "actual size:" in formatted
    assert '"value":"XXXX' not in formatted


def test_omits_oversized_quality_evidence() -> None:
    state = _build_state(
        issues=(_issue("Issue", {"value": "Y" * 100}),),
    )

    formatted = InvestigationStateFormatter(
        max_evidence_chars=20,
    ).format(state)

    assert "[EVIDENCE OMITTED:" in formatted
    assert '"value":"YYYY' not in formatted


def test_preserves_small_serialized_evidence() -> None:
    state = _build_state(
        insights=(_insight("Insight", {"count": 3}),),
        issues=(_issue("Issue", {"count": 2}),),
    )

    formatted = InvestigationStateFormatter().format(state)

    assert 'Evidence: {"count":3}' in formatted
    assert 'Evidence: {"count":2}' in formatted
    assert "EVIDENCE OMITTED" not in formatted


def test_preserves_messages_at_exact_limit() -> None:
    state = _build_state(
        insights=(_insight("ABCDE", {}),),
        attempts=(_attempt("12345"),),
    )

    formatted = InvestigationStateFormatter(
        max_message_chars=5,
        max_error_chars=5,
    ).format(state)

    assert "ABCDE" in formatted
    assert "Error: 12345" in formatted
    assert "TRUNCATED" not in formatted


def test_preserves_entries_at_exact_limit() -> None:
    state = _build_state(
        insights=(_insight("Insight", {}),),
        issues=(_issue("Issue", {}),),
        attempts=(_attempt("Failure"),),
    )

    formatted = InvestigationStateFormatter(
        max_insights=1,
        max_quality_issues=1,
        max_failed_attempts=1,
    ).format(state)

    assert "Insights omitted:" not in formatted
    assert "Quality findings omitted:" not in formatted
    assert "Failed attempts omitted:" not in formatted


def test_bounded_evidence_formatting_is_deterministic() -> None:
    state = _build_state(
        insights=(_insight("X" * 50, {"value": "Y" * 50}),),
        attempts=(_attempt("Z" * 50),),
    )

    formatter = InvestigationStateFormatter(
        max_message_chars=10,
        max_evidence_chars=10,
        max_error_chars=10,
    )

    assert formatter.format(state) == formatter.format(state)
