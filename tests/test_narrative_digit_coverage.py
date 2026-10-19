"""Digit coverage is separate from token linkage and analytical verification."""

import json
from dataclasses import asdict, replace
from pathlib import Path
from unittest.mock import patch

import pytest
from scripts.live_evaluation import main, score_result

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.config import Settings
from verisight.execution.claim_verification import (
    ClaimOperation,
    EvidenceReference,
    NumericalClaim,
    VerificationStatus,
)
from verisight.execution.investigation_result import InvestigationResult
from verisight.execution.models import QueryResult
from verisight.execution.narrative_audit import (
    audit_narrative_digit_coverage,
    find_narrative_numbers,
)
from verisight.execution.observations import QueryObservation
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile
from verisight.serialization import to_jsonable


@pytest.mark.parametrize(
    "text,total,parsed,status",
    [
        pytest.param("No numerical finding.", 0, 0, "no_digits", id="no-digits"),
        pytest.param("Thirty rows.", 0, 0, "no_digits", id="number-word"),
        pytest.param("−4521", 4, 0, "unparsed_digits", id="unicode-minus"),
        pytest.param("3.5x", 2, 0, "unparsed_digits", id="multiplier"),
        pytest.param("12k", 2, 0, "unparsed_digits", id="thousands-suffix"),
        pytest.param("$5M", 1, 0, "unparsed_digits", id="millions-suffix"),
        pytest.param("2B", 1, 0, "unparsed_digits", id="billions-suffix"),
        pytest.param("10-15", 4, 0, "unparsed_digits", id="range"),
        pytest.param("3/4", 2, 0, "unparsed_digits", id="ratio"),
        pytest.param("9999rows", 4, 0, "unparsed_digits", id="glued-unit"),
        pytest.param("４５２１", 4, 0, "unparsed_digits", id="fullwidth"),
        pytest.param("٤٥٢١", 4, 0, "unparsed_digits", id="arabic-indic"),
        pytest.param("²", 1, 0, "unparsed_digits", id="superscript"),
        pytest.param("1,23", 3, 0, "unparsed_digits", id="rejected-grouping"),
        pytest.param("01", 2, 0, "unparsed_digits", id="rejected-leading-zero"),
        pytest.param("9" * 129, 129, 0, "unparsed_digits", id="token-size-limit"),
        pytest.param(
            "1e999999999999999999999999",
            25,
            0,
            "unparsed_digits",
            id="decimal-conversion-limit",
        ),
        pytest.param("2025-10-19", 8, 0, "unparsed_digits", id="date"),
        pytest.param("v1.2.3", 3, 0, "unparsed_digits", id="version"),
        pytest.param("30 and 12k", 4, 2, "unparsed_digits", id="mixed"),
        pytest.param(
            "up 3.5x from −2.1% in 2025",
            8,
            4,
            "unparsed_digits",
            id="review-example",
        ),
        pytest.param(
            "0.30; 1e3; 25%; -4; +5; .6",
            10,
            10,
            "all_digits_parsed",
            id="supported-syntax",
        ),
        pytest.param("30 then 30", 4, 4, "all_digits_parsed", id="occurrences"),
    ],
)
def test_coverage_counts_digit_characters_even_without_tokens(
    text: str, total: int, parsed: int, status: str
) -> None:
    tokens = find_narrative_numbers(text, ())
    coverage = audit_narrative_digit_coverage(text, tokens)
    assert asdict(coverage) == {
        "total_digit_count": total,
        "parsed_digit_count": parsed,
        "unparsed_digit_count": total - parsed,
        "status": status,
    }


def _result(conclusion: str, *, expected: int = 30) -> InvestigationResult:
    analysis = AnalysisResultBuilder().build(
        DatasetAnalysis(
            schema=DatasetSchema(tables=()),
            profile=DatasetProfile(tables=()),
            issues=(),
        )
    )
    return InvestigationResult(
        question="What is the total?",
        conclusion=conclusion,
        analysis=analysis,
        observations=(
            QueryObservation(
                question="What is the total?",
                sql="SELECT SUM(value) AS total FROM measurements",
                result=QueryResult(columns=("total",), rows=((30,),)),
            ),
        ),
        generated_claims=(
            NumericalClaim(
                ClaimOperation.VALUE, expected, EvidenceReference(0, 0, "total")
            ),
        ),
    )


def test_empty_unlinked_list_can_coexist_with_unparsed_digits() -> None:
    result = _result("The total is 30, up 3.5x from −2.1%.")
    assert result.unlinked_numbers == ()
    assert result.narrative_digit_coverage.unparsed_digit_count == 4
    assert result.narrative_digit_coverage.status == "unparsed_digits"
    assert result.narrative_verified is False
    report = score_result(result, "30")
    assert report["outcome"] == "correct_numeric"
    assert report["unlinked_number_count"] == 0
    assert report["narrative_digit_coverage"] == {
        "total_digit_count": 6,
        "parsed_digit_count": 2,
        "unparsed_digit_count": 4,
        "status": "unparsed_digits",
    }
    payload = json.loads(json.dumps(to_jsonable(result)))
    assert payload["narrative_digit_coverage"] == report["narrative_digit_coverage"]


@pytest.mark.parametrize(
    "conclusion,expected,verdict,unlinked",
    [
        ("The total is 9999.", 30, VerificationStatus.SUPPORTED, ("9999",)),
        ("The total is 9999.", 9999, VerificationStatus.CONTRADICTED, ()),
    ],
    ids=["unlinked-number", "linked-contradicted-claim"],
)
def test_all_digits_parsed_does_not_establish_claim_or_narrative_truth(
    conclusion: str,
    expected: int,
    verdict: VerificationStatus,
    unlinked: tuple[str, ...],
) -> None:
    result = _result(conclusion, expected=expected)
    assert result.narrative_digit_coverage.status == "all_digits_parsed"
    assert result.verified_claims[0].verification.status is verdict
    assert result.unlinked_numbers == unlinked
    assert result.narrative_verified is False


def test_replacing_conclusion_recomputes_digit_coverage() -> None:
    result = _result("The total is 30.")
    changed = replace(result, conclusion="Thirty rows.")
    assert result.narrative_digit_coverage.status == "all_digits_parsed"
    assert changed.narrative_digit_coverage.status == "no_digits"
    assert changed.narrative_digit_coverage.total_digit_count == 0
    assert changed.narrative_verified is False


def test_saved_evaluation_keeps_digit_coverage_without_raw_narrative(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    result = _result("synthetic-private-narrative 30 and 12k")
    report_path = tmp_path / "evaluation.json"
    with (
        patch(
            "sys.argv",
            ["live_evaluation", "--live", "--output", str(report_path)],
        ),
        patch(
            "scripts.live_evaluation.Settings",
            return_value=Settings(gemini_api_key="synthetic-key"),
        ),
        patch(
            "scripts.live_evaluation.run_case", return_value=score_result(result, "30")
        ),
        patch(
            "scripts.live_evaluation.repository_metadata",
            return_value={"commit": "synthetic", "tracked_changes": False},
        ),
    ):
        assert main() == 0
    saved = report_path.read_text(encoding="utf-8")
    printed = capsys.readouterr().out
    assert json.loads(saved) == json.loads(printed)
    coverage = json.loads(saved)["results"]["finance"]["narrative_digit_coverage"]
    assert coverage == {
        "total_digit_count": 4,
        "parsed_digit_count": 2,
        "unparsed_digit_count": 2,
        "status": "unparsed_digits",
    }
    assert "synthetic-private-narrative" not in saved
    assert "synthetic-key" not in saved
