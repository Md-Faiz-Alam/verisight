"""Deterministic formatting for autonomous investigation state."""

import json

from verisight.evidence import evidence_to_jsonable, freeze_evidence
from verisight.execution.context import QueryRelation
from verisight.execution.investigation import InvestigationState
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation


class InvestigationStateFormatter:
    """Format investigation state for an analytical investigator."""

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

    @staticmethod
    def _format_insights(state: InvestigationState) -> str:
        """Format deterministic analytical insights."""

        if not state.analysis.insights:
            return "DETERMINISTIC INSIGHTS\nNone"

        lines = ["DETERMINISTIC INSIGHTS"]

        for index, insight in enumerate(
            state.analysis.insights,
            start=1,
        ):
            lines.append(f"{index}. [{insight.insight_type.value}] {insight.message}")

            evidence = evidence_to_jsonable(freeze_evidence(insight.evidence))

            if evidence:
                lines.append(
                    "   Evidence: "
                    + json.dumps(
                        evidence,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )

        return "\n".join(lines)

    @staticmethod
    def _format_quality_issues(state: InvestigationState) -> str:
        """Format deterministic data-quality findings."""

        issues = state.analysis.analysis.issues

        if not issues:
            return "DATA QUALITY FINDINGS\nNone"

        lines = ["DATA QUALITY FINDINGS"]

        for index, issue in enumerate(issues, start=1):
            location = issue.relation_name

            if issue.column_name is not None:
                location = f"{location}.{issue.column_name}"

            lines.append(
                f"{index}. [{issue.severity.value}] "
                f"[{issue.issue_type.value}] "
                f"{location}: {issue.message}"
            )

            evidence = evidence_to_jsonable(freeze_evidence(issue.evidence))

            if evidence:
                lines.append(
                    "   Evidence: "
                    + json.dumps(
                        evidence,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )

        return "\n".join(lines)

    def _format_observations(
        self,
        state: InvestigationState,
    ) -> str:
        """Format previously executed analytical observations."""

        if not state.observations:
            return "EXECUTED OBSERVATIONS\nNone"

        sections = ["EXECUTED OBSERVATIONS"]

        for index, observation in enumerate(
            state.observations,
            start=1,
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

    @staticmethod
    def _format_result(result: QueryResult) -> str:
        """Format one structured query result."""

        if result.is_empty:
            return "Columns: " + ", ".join(result.columns) + "\nRows: None"

        lines = [
            "Columns: " + ", ".join(result.columns),
            f"Row count: {result.row_count}",
            "Rows:",
        ]

        lines.extend(
            json.dumps(
                list(row),
                separators=(",", ":"),
            )
            for row in result.rows
        )

        return "\n".join(lines)
