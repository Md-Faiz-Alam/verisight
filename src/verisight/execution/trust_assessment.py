"""Combine every check on an answer into one trust level."""

from verisight.execution.claim_verification import VerificationStatus
from verisight.execution.context import QueryContext
from verisight.execution.cross_check import CrossCheckStatus
from verisight.execution.investigation_result import (
    InvestigationResult,
    InvestigationStatus,
)
from verisight.execution.metric_display import summarize_advisory_reviews
from verisight.execution.sql_audit import SqlAudit, audit_sql
from verisight.execution.trust import CheckStatus, TrustCheck, TrustLevel, TrustReport
from verisight.ingestion.models import LoadedDataset

MEASURE_CHECK = "data_holds_measure"
DEFINED_CHECK = "question_is_defined"
# Audit findings that leave no number worth showing, and the check each fails.
BLOCKING_FINDINGS = {
    "measure_not_in_data": MEASURE_CHECK,
    "assumed_definition": DEFINED_CHECK,
    "missing_comparison": DEFINED_CHECK,
}


def _audit_check(name: str, audits: list[SqlAudit]) -> TrustCheck:
    details = [f.detail for audit in audits for f in audit.findings]
    if details:
        return TrustCheck(name, CheckStatus.FAILED, " ".join(details))
    if audits and all(audit.assessed for audit in audits):
        return TrustCheck(
            name,
            CheckStatus.PASSED,
            "Joins, filters, totals and the calculation showed no known mistake.",
        )
    return TrustCheck(name, CheckStatus.NOT_ASSESSED, "The SQL could not be audited.")


def _number_check(result: InvestigationResult, accepted: bool) -> TrustCheck:
    supported = bool(result.verified_claims) and all(
        item.verification.status is VerificationStatus.SUPPORTED
        for item in result.verified_claims
    )
    if accepted and supported and result.status is InvestigationStatus.COMPLETE:
        return TrustCheck(
            "number_matches_sql",
            CheckStatus.PASSED,
            "Every number equals a cell of the executed SQL.",
        )
    return TrustCheck(
        "number_matches_sql",
        CheckStatus.FAILED,
        "The answer has no number that matches an executed SQL cell.",
    )


def _second_query_check(result: InvestigationResult) -> TrustCheck:
    check = result.cross_check
    if check is None or check.status is CrossCheckStatus.NOT_ASSESSED:
        return TrustCheck(
            "second_query",
            CheckStatus.NOT_ASSESSED,
            "No independent second calculation was available.",
        )
    if check.status is CrossCheckStatus.AGREED and check.identical_sql:
        return TrustCheck(
            "second_query",
            CheckStatus.NOT_ASSESSED,
            "The second query was written the same way as the first, so its "
            "agreement adds no independent evidence.",
        )
    if check.status is CrossCheckStatus.AGREED:
        return TrustCheck(
            "second_query",
            CheckStatus.PASSED,
            "A second query, written without seeing the first, got the same number.",
        )
    return TrustCheck(
        "second_query",
        CheckStatus.FAILED,
        f"A second query got {check.independent_value} instead of "
        f"{check.primary_value}.",
    )


def _review_check(result: InvestigationResult, cited: list[int]) -> TrustCheck:
    """Only the queries behind the answer count, not earlier exploration."""
    reviews = summarize_advisory_reviews(result)
    flagged = {
        *reviews.population_review_required_observations,
        *reviews.grain_review_required_observations,
    }
    if flagged.intersection(cited):
        return TrustCheck(
            "population_review",
            CheckStatus.FAILED,
            "The rows or counting unit may differ from what the question means.",
        )
    return TrustCheck(
        "population_review", CheckStatus.PASSED, "No population warning was raised."
    )


def assess_trust(
    result: InvestigationResult,
    *,
    dataset: LoadedDataset,
    context: QueryContext,
    accepted: bool,
) -> TrustReport:
    """Decide the level: any failed check blocks it, and agreement earns it."""
    number = _number_check(result, accepted)
    if number.status is CheckStatus.FAILED:
        return TrustReport(TrustLevel.NOT_VERIFIED, (number,))
    cited = sorted(
        {
            reference.observation_index
            for item in result.verified_claims
            for reference in (item.claim.left, item.claim.right)
            if reference is not None
        }
    )
    audits = [
        audit_sql(
            question=result.question,
            sql=result.observations[index].sql,
            result=result.observations[index].result,
            dataset=dataset,
            total_rows=context.total_rows,
            categories=context.review_categories,
        )
        for index in cited
    ]
    for code, name in BLOCKING_FINDINGS.items():
        blocked = [
            finding.detail
            for audit in audits
            for finding in audit.findings
            if finding.code == code
        ]
        if blocked:
            # The number answers something else, so no label can make it useful.
            check = TrustCheck(name, CheckStatus.FAILED, blocked[0])
            return TrustReport(TrustLevel.NOT_VERIFIED, (number, check))
    second = result.cross_check
    second_audits = (
        []
        if second is None or second.sql is None
        else [
            audit_sql(
                question=result.question,
                sql=second.sql,
                result=None,
                dataset=dataset,
                total_rows=context.total_rows,
                categories=context.review_categories,
            )
        ]
    )
    checks = (
        number,
        _audit_check("sql_audit", audits),
        _review_check(result, cited),
        _second_query_check(result),
        *([_audit_check("second_query_audit", second_audits)] if second_audits else ()),
    )
    if any(check.status is CheckStatus.FAILED for check in checks):
        return TrustReport(TrustLevel.NEEDS_REVIEW, checks)
    if all(check.status is CheckStatus.PASSED for check in checks):
        return TrustReport(TrustLevel.VERIFIED, checks)
    return TrustReport(TrustLevel.NUMBER_MATCHED, checks)
