"""Opt-in live evaluation on synthetic data, with independent numerical answers."""

import argparse
import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from verisight import VeriSight
from verisight.config import Settings
from verisight.error_reporting import to_public_error
from verisight.exceptions import ConfigurationError
from verisight.execution.claim_verification import ClaimOperation, VerificationStatus
from verisight.execution.gemini import GeminiGenerationError
from verisight.execution.investigation_result import (
    InvestigationResult,
    InvestigationStatus,
)


@dataclass(frozen=True)
class Case:
    files: tuple[tuple[str, str], ...]
    question: str
    answer: str


CASES = {
    "finance": Case(
        files=(
            (
                "ledger.csv",
                "cents,state\n12500,posted\n-2500,posted\n50,posted\n999,pending\n",
            ),
        ),
        question=(
            "What is the net posted amount in cents? Exclude pending transactions."
        ),
        answer="10050",
    ),
    "retail": Case(
        files=(
            ("lines.csv", "sku,quantity\nA,2\nB,3\nA,1\n"),
            ("prices.csv", "sku,unit_price\nA,10\nB,20\n"),
        ),
        question=(
            "What is the total line value? Match each line to its SKU's unit price."
        ),
        answer="90",
    ),
    "manufacturing": Case(
        files=(("inspections.csv", "id,defective\n1,1\n2,0\n3,0\n4,0\n5,\n"),),
        question=(
            "What percentage of known inspection outcomes are defective? "
            "Defective is 1 for defective and 0 otherwise. Exclude unknown outcomes."
        ),
        answer="25",
    ),
}

REQUEST = (
    " Answer only this metric. Use one analytical query and then finish. "
    "Return exactly one numerical VALUE claim referring to the final metric cell. "
    "Do not add numerical claims for intermediate values. "
    "If the evidence is insufficient, explain that and return no claims."
)


def score_result(result: InvestigationResult, answer: str) -> dict[str, object]:
    """Score the single submitted metric, never certify its prose or SQL semantics."""
    report: dict[str, object] = {
        "expected": answer,
        "observation_count": result.observation_count,
        "claim_count": len(result.verified_claims),
        "narrative_verified": False,
    }
    if result.status is InvestigationStatus.INCOMPLETE:
        report["outcome"] = "incomplete"
    elif not result.verified_claims:
        report["outcome"] = "no_claims"
    elif len(result.verified_claims) != 1:
        report["outcome"] = "ambiguous_claims"
    else:
        item = result.verified_claims[0]
        report["verification_status"] = item.verification.status.value
        if item.claim.operation is not ClaimOperation.VALUE:
            report["outcome"] = "unsupported_answer_format"
        elif item.verification.status is not VerificationStatus.SUPPORTED:
            report["outcome"] = "unverified_answer"
        else:
            report["actual"] = str(item.verification.actual)
            report["outcome"] = (
                "correct_numeric"
                if item.verification.actual == Decimal(answer)
                else "incorrect_numeric"
            )
    return report


def failure_report(error: Exception) -> dict[str, object]:
    """Classify provider causes without exposing exception text or credentials."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, GeminiGenerationError):
            report: dict[str, object] = {"outcome": "provider_error"}
            if current.diagnostics is not None:
                report["diagnostics"] = asdict(current.diagnostics)
            return report
        current = current.__cause__
    return {"outcome": "application_error", "code": to_public_error(error).code.value}


def run_case(case: Case, settings: Settings) -> dict[str, object]:
    """Use temporary synthetic files and the real default investigation path."""
    try:
        with TemporaryDirectory(prefix="verisight-evaluation-") as directory:
            paths = []
            for filename, content in case.files:
                path = Path(directory) / filename
                path.write_text(content, encoding="utf-8")
                paths.append(path)
            result = VeriSight(settings=settings).investigate(
                paths, case.question + REQUEST, max_steps=1
            )
            return score_result(result, case.answer)
    except Exception as error:
        return failure_report(error)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Allow Gemini calls using synthetic data."
    )
    parser.add_argument("--case", choices=[*CASES, "all"], default="finance")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to authorize provider calls; API charges may apply.")

    try:
        settings = Settings(
            allow_llm_data_disclosure=True,
            gemini_max_retries=0,
            gemini_request_timeout_seconds=20.0,
            max_query_execution_seconds=5.0,
            max_query_result_rows=20,
        )
        if settings.gemini_api_key is None or not settings.gemini_api_key.strip():
            raise ConfigurationError("An API key is required.")
    except Exception as error:
        print(json.dumps(failure_report(error), indent=2))
        return 2

    selected = CASES if args.case == "all" else {args.case: CASES[args.case]}
    results = {name: run_case(case, settings) for name, case in selected.items()}
    counts = Counter(str(result["outcome"]) for result in results.values())
    report = {
        "schema_version": 1,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "model": settings.gemini_model,
        "max_steps_per_case": 1,
        "provider_retries": 0,
        "scoring_scope": "single_claim_numeric_answer_only",
        "limitations": (
            "No narrative or general semantic certification. No-claims responses "
            "are not automatically proven abstentions. These are known development "
            "fixtures, not a held-out generalization benchmark."
        ),
        "case_count": len(results),
        "outcome_counts": dict(counts),
        "results": results,
    }
    print(json.dumps(report, indent=2))
    return 0 if counts.get("correct_numeric", 0) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
