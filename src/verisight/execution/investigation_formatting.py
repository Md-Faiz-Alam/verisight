"""Deterministic formatting for autonomous investigation state."""

import json

from verisight.evidence import (
    EvidenceInput,
    evidence_to_jsonable,
    freeze_evidence,
)
from verisight.execution.context import QueryRelation
from verisight.execution.investigation import (
    FailedQueryAttempt,
    InvestigationState,
)
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation
from verisight.serialization import to_jsonable


class InvestigationStateFormatter:
    """Format investigation state for an analytical investigator."""

    def __init__(
        self,
        *,
        max_result_rows: int = 100,
        max_observations: int | None = None,
        max_insights: int = 50,
        max_quality_issues: int = 50,
        max_failed_attempts: int = 20,
        max_message_chars: int = 1_000,
        max_evidence_chars: int = 2_000,
        max_error_chars: int = 1_000,
    ) -> None:
        """Initialize configurable limits for LLM-facing evidence."""

        limits = {
            "Maximum result rows": max_result_rows,
            "Maximum insights": max_insights,
            "Maximum quality issues": max_quality_issues,
            "Maximum failed attempts": max_failed_attempts,
            "Maximum message characters": max_message_chars,
            "Maximum evidence characters": max_evidence_chars,
            "Maximum error characters": max_error_chars,
        }

        for name, value in limits.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive.")

        if max_observations is not None and max_observations < 0:
            raise ValueError("Maximum observations must not be negative.")

        self._max_observations = max_observations
        self._max_result_rows = max_result_rows
        self._max_insights = max_insights
        self._max_quality_issues = max_quality_issues
        self._max_failed_attempts = max_failed_attempts
        self._max_message_chars = max_message_chars
        self._max_evidence_chars = max_evidence_chars
        self._max_error_chars = max_error_chars

    def format(self, state: InvestigationState) -> str:
        """Format deterministic analysis and observations for investigation."""

        sections = [
            self._format_question(state),
            self._format_summary(state),
            self._format_query_context(state),
            self._format_insights(state),
            self._format_quality_issues(state),
            self._format_observations(state),
        ]

        if state.failed_attempts:
            sections.append(self._format_failed_attempts(state))

        return "\n\n".join(sections)

    @staticmethod
    def _format_question(state: InvestigationState) -> str:
        """Format the original investigation question."""

        return f"ORIGINAL QUESTION\n{state.question}"

    @staticmethod
    def _format_summary(state: InvestigationState) -> str:
        """Format the deterministic dataset summary."""

        summary = state.analysis.summary

        return (
            "DATASET SUMMARY\n"
            f"Tables: {summary.table_count}\n"
            f"Rows: {summary.total_row_count}\n"
            f"Columns: {summary.total_column_count}\n"
            f"Quality issues: {summary.issue_count}\n"
            f"Info issues: {summary.info_issue_count}\n"
            f"Warning issues: {summary.warning_issue_count}\n"
            f"Error issues: {summary.error_issue_count}"
        )

    def _format_query_context(
        self,
        state: InvestigationState,
    ) -> str:
        """Format deterministic queryable dataset structure."""

        context = state.context

        if not context.relations:
            return "QUERYABLE DATASET STRUCTURE\nNone"

        sections = ["QUERYABLE DATASET STRUCTURE"]

        for relation in context.relations:
            sections.append(self._format_relation(relation))

        return "\n\n".join(sections)

    @staticmethod
    def _format_relation(relation: QueryRelation) -> str:
        """Format one queryable relation for investigation."""

        lines = [
            f"RELATION {relation.relation_name}",
            f"Display name: {relation.name}",
            f"Rows: {relation.row_count}",
            "Columns:",
        ]

        if not relation.columns:
            lines.append("None")
            return "\n".join(lines)

        lines.extend(
            (
                f"- {column.name} | "
                f"logical_type={column.logical_type.value} | "
                f"physical_dtype={column.physical_dtype} | "
                f"nullable={str(column.nullable).lower()}"
            )
            for column in relation.columns
        )

        return "\n".join(lines)

    def _format_insights(self, state: InvestigationState) -> str:
        """Format a bounded number of deterministic analytical insights."""

        insights = state.analysis.insights

        if not insights:
            return "DETERMINISTIC INSIGHTS\nNone"

        lines = ["DETERMINISTIC INSIGHTS"]

        for index, insight in enumerate(
            insights[: self._max_insights],
            start=1,
        ):
            message = self._bounded_text(
                insight.message,
                self._max_message_chars,
            )

            lines.append(f"{index}. [{insight.insight_type.value}] {message}")

            evidence = self._format_evidence(insight.evidence)

            if evidence is not None:
                lines.append(f"   Evidence: {evidence}")

        omitted = len(insights) - min(len(insights), self._max_insights)

        if omitted:
            lines.append(f"Insights omitted: {omitted} of {len(insights)}")

        return "\n".join(lines)

    def _format_quality_issues(self, state: InvestigationState) -> str:
        """Format a bounded number of deterministic quality findings."""

        issues = state.analysis.analysis.issues

        if not issues:
            return "DATA QUALITY FINDINGS\nNone"

        lines = ["DATA QUALITY FINDINGS"]

        for index, issue in enumerate(
            issues[: self._max_quality_issues],
            start=1,
        ):
            location = issue.relation_name

            if issue.column_name is not None:
                location = f"{location}.{issue.column_name}"

            message = self._bounded_text(
                issue.message,
                self._max_message_chars,
            )

            lines.append(
                f"{index}. [{issue.severity.value}] "
                f"[{issue.issue_type.value}] "
                f"{location}: {message}"
            )

            evidence = self._format_evidence(issue.evidence)

            if evidence is not None:
                lines.append(f"   Evidence: {evidence}")

        omitted = len(issues) - min(
            len(issues),
            self._max_quality_issues,
        )

        if omitted:
            lines.append(f"Quality findings omitted: {omitted} of {len(issues)}")

        return "\n".join(lines)

    def _format_observations(
        self,
        state: InvestigationState,
    ) -> str:
        """Format previously executed analytical observations."""

        if not state.observations:
            return "EXECUTED OBSERVATIONS\nNone"

        sections = ["EXECUTED OBSERVATIONS"]

        observations = state.observations

        if self._max_observations is not None:
            observations = (
                observations[-self._max_observations :]
                if self._max_observations
                else ()
            )

        omitted = len(state.observations) - len(observations)

        if omitted:
            sections.append(
                f"EVIDENCE COMPACTED: {omitted} of {len(state.observations)} "
                "executed observations omitted from this prompt. "
                "Do not assume omitted results support any conclusion."
            )

        for index, observation in enumerate(
            observations,
            start=len(state.observations) - len(observations) + 1,
        ):
            sections.append(
                self._format_observation(
                    index=index,
                    observation=observation,
                )
            )

        return "\n\n".join(sections)

    def _format_observation(
        self,
        *,
        index: int,
        observation: QueryObservation,
    ) -> str:
        """Format one executed analytical observation."""

        return (
            f"OBSERVATION {index}\n"
            f"Question: {observation.question}\n"
            "SQL:\n"
            f"{observation.sql}\n"
            "Result:\n"
            f"{self._format_result(observation.result)}"
        )

    def _format_result(self, result: QueryResult) -> str:
        """Format a query result with bounded displayed rows."""

        if result.is_empty:
            return "Columns: " + ", ".join(result.columns) + "\nRows: None"

        lines = [
            "Columns: " + ", ".join(result.columns),
            f"Row count: {result.row_count}",
            "Rows:",
        ]

        lines.extend(
            json.dumps(
                to_jsonable(row),
                separators=(",", ":"),
            )
            for row in result.rows[: self._max_result_rows]
        )

        omitted_rows = result.row_count - min(
            result.row_count,
            self._max_result_rows,
        )

        if omitted_rows:
            lines.append(f"Rows omitted: {omitted_rows} of {result.row_count}")

        return "\n".join(lines)

    def _format_failed_attempts(self, state: InvestigationState) -> str:
        """Format bounded failed attempts separately from evidence."""

        attempts = state.failed_attempts
        sections = ["FAILED QUERY ATTEMPTS"]

        for index, attempt in enumerate(
            attempts[: self._max_failed_attempts],
            start=1,
        ):
            sections.append(
                self._format_failed_attempt(
                    index=index,
                    attempt=attempt,
                )
            )

        omitted = len(attempts) - min(
            len(attempts),
            self._max_failed_attempts,
        )

        if omitted:
            sections.append(f"Failed attempts omitted: {omitted} of {len(attempts)}")

        return "\n\n".join(sections)

    def _format_failed_attempt(
        self,
        *,
        index: int,
        attempt: FailedQueryAttempt,
    ) -> str:
        """Format one unsuccessful analytical attempt."""

        message = self._bounded_text(
            attempt.message,
            self._max_error_chars,
        )

        return (
            f"FAILED ATTEMPT {index}\n"
            f"Question: {attempt.question}\n"
            f"Error type: {attempt.error_type}\n"
            f"Error: {message}\n"
            "Status: Failed; not analytical evidence."
        )

    @staticmethod
    def _bounded_text(value: str, maximum: int) -> str:
        """Bound text and explicitly disclose removed characters."""

        if len(value) <= maximum:
            return value

        omitted = len(value) - maximum

        return f"{value[:maximum]} [TRUNCATED: {omitted} characters omitted]"

    def _format_evidence(self, evidence: EvidenceInput) -> str | None:
        """Serialize evidence without emitting incomplete JSON."""

        serialized = evidence_to_jsonable(freeze_evidence(evidence))

        if not serialized:
            return None

        text = json.dumps(
            serialized,
            sort_keys=True,
            separators=(",", ":"),
        )

        if len(text) > self._max_evidence_chars:
            return (
                "[EVIDENCE OMITTED: serialized payload exceeds "
                f"{self._max_evidence_chars} characters; "
                f"actual size: {len(text)} characters]"
            )

        return text
