"""Contract-mode claim references and CLI generation-call timing."""

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.cli import main
from verisight.execution.claim_verification import ClaimOperation
from verisight.execution.exceptions import SynthesisValidationError
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_result import ClaimOutputContract
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation
from verisight.execution.structured_synthesis import StructuredInvestigationSynthesizer
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile


class _Sequence:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.responses[len(self.prompts) - 1]


def _state(*, contract: bool = True) -> InvestigationState:
    analysis = AnalysisResultBuilder().build(
        DatasetAnalysis(
            schema=DatasetSchema(tables=()),
            profile=DatasetProfile(tables=()),
            issues=(),
        )
    )
    state = InvestigationState(
        question="Among known outcomes, what percentage succeeded?",
        analysis=analysis,
    ).add_observation(
        QueryObservation(
            question="Count successes and failures.",
            sql="SELECT 1373 AS success_count, 4252 AS failure_count, 'x' AS label",
            result=QueryResult(
                columns=("success_count", "failure_count", "label"),
                rows=((1373, 4252, "x"),),
            ),
        )
    )
    if not contract:
        return state
    return replace(
        state, claim_output_contract=ClaimOutputContract((ClaimOperation.VALUE,))
    )


def _ref(column: str, *, observation: int = 0, row: int = 0) -> dict[str, Any]:
    return {"observation_index": observation, "row_index": row, "column": column}


def _value(expected: str, left: dict[str, Any]) -> dict[str, Any]:
    return {"operation": "value", "expected": expected, "left": left, "right": None}


def _response(conclusion: str, claims: list[dict[str, Any]]) -> str:
    return json.dumps({"conclusion": conclusion, "claims": claims})


_INVENTED = _response(
    "The success percentage is 24.41777.",
    [_value("24.41777", _ref("percentage_success"))],
)
_LIMITATION = _response(
    "Only component counts were collected; the final percentage is unavailable.",
    [],
)


@pytest.mark.parametrize(
    "left",
    [
        _ref("percentage_success"),
        _ref("success_count", observation=1),
        _ref("success_count", row=1),
        _ref("label"),
    ],
    ids=["missing-column", "missing-observation", "missing-row", "text-cell"],
)
def test_contract_mode_repairs_unresolvable_references(left: dict[str, Any]) -> None:
    rejected = _response("The value is 24.41777.", [_value("24.41777", left)])
    client = _Sequence([rejected, _LIMITATION])

    synthesis = StructuredInvestigationSynthesizer(client).synthesize(_state())

    assert synthesis.claims == ()
    assert len(client.prompts) == 2
    assert '"validation_error": "invalid_claim_reference"' in client.prompts[1]
    assert "24.41777" not in client.prompts[1]
    assert "must name an existing numeric result cell" in client.prompts[1]


def test_contract_mode_rejects_a_difference_of_one_cell_with_itself() -> None:
    same = _ref("success_count")
    degenerate = _response(
        "The difference is 0.",
        [{"operation": "difference", "expected": "0", "left": same, "right": same}],
    )
    client = _Sequence([degenerate, degenerate])
    state = replace(
        _state(),
        claim_output_contract=ClaimOutputContract((ClaimOperation.DIFFERENCE,)),
    )

    with pytest.raises(SynthesisValidationError) as caught:
        StructuredInvestigationSynthesizer(client).synthesize(state)

    assert caught.value.reason == "invalid_claim_reference"
    assert caught.value.repair_attempted is True
    assert len(client.prompts) == 2


def test_contract_mode_keeps_valid_differences_and_contradictions() -> None:
    contradicted = _response(
        "The difference is 1.",
        [
            {
                "operation": "difference",
                "expected": "1",
                "left": _ref("failure_count"),
                "right": _ref("success_count"),
            }
        ],
    )
    client = _Sequence([contradicted])
    state = replace(
        _state(),
        claim_output_contract=ClaimOutputContract((ClaimOperation.DIFFERENCE,)),
    )

    synthesis = StructuredInvestigationSynthesizer(client).synthesize(state)

    assert len(synthesis.claims) == 1
    assert len(client.prompts) == 1


def test_without_a_contract_unresolvable_claims_are_returned_unchanged() -> None:
    client = _Sequence([_INVENTED])

    synthesis = StructuredInvestigationSynthesizer(client).synthesize(
        _state(contract=False)
    )

    assert synthesis.claims[0].left.column == "percentage_success"
    assert len(client.prompts) == 1


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "campaign.csv"
    source.write_text(
        "poutcome,y\nsuccess,yes\nfailure,no\nfailure,no\nnonexistent,no\n",
        encoding="utf-8",
    )
    return source


def _args(source: Path, *extra: str) -> list[str]:
    return [
        "investigate",
        str(source),
        "--question",
        "Among known previous outcomes, what percentage were successes?",
        "--require-claim",
        "value",
        "--max-steps",
        "1",
        "--allow-llm-data-disclosure",
        *extra,
    ]


def _replies(*texts: str) -> list[SimpleNamespace]:
    return [SimpleNamespace(text=text) for text in texts]


def test_cli_reports_call_timing_and_repairs_invented_metric(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERISIGHT_GEMINI_API_KEY", "offline-key")
    decide = json.dumps(
        {"action": "investigate", "reasoning": "Measure", "question": "Measure"}
    )
    sql = (
        "SELECT SUM(CASE WHEN poutcome = 'success' THEN 1 ELSE 0 END) "
        "AS success_count, SUM(CASE WHEN poutcome = 'failure' THEN 1 ELSE 0 END) "
        "AS failure_count FROM campaign WHERE poutcome IN ('success', 'failure')"
    )
    invented = _response(
        "The success percentage is 33.4.",
        [_value("33.4", _ref("percentage_success"))],
    )

    with patch(
        "verisight.execution.gemini.GeminiTextGenerationClient._request",
        side_effect=_replies(decide, sql, invented, invented),
    ) as request:
        assert main(_args(_source(tmp_path))) == 1

    assert request.call_count == 4
    report = json.loads(capsys.readouterr().out)
    investigation = report["investigation"]
    assert report["workflow_status"] == "incomplete"
    assert investigation["synthesis_failure"]["validation_reason"] == (
        "invalid_claim_reference"
    )
    assert investigation["synthesis_failure"]["repair_attempted"] is True
    assert investigation["observations"][0]["result"]["rows"] == [[1, 2]]
    calls = report["generation_calls"]
    assert [call["stage"] for call in calls] == [
        "investigator",
        "text_generation",
        "structured_synthesis",
        "structured_synthesis",
    ]
    assert all(call["attempts"] == 1 and call["returned_text"] for call in calls)
    assert all(call["elapsed_seconds"] >= 0 for call in calls)
    assert set(calls[0]) == {
        "stage",
        "call_number",
        "attempts",
        "elapsed_seconds",
        "returned_text",
    }


def test_cli_reports_call_timing_for_failures_before_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERISIGHT_GEMINI_API_KEY", "offline-key")

    with patch(
        "verisight.execution.gemini.GeminiTextGenerationClient._request",
        side_effect=ValueError("synthetic-private-provider-detail"),
    ):
        assert main(_args(_source(tmp_path))) == 1

    output = capsys.readouterr().out
    report = json.loads(output)
    assert report["kind"] == "operation_error"
    assert report["generation_calls"] == [
        {
            "stage": "investigator",
            "call_number": 1,
            "attempts": 1,
            "elapsed_seconds": report["generation_calls"][0]["elapsed_seconds"],
            "returned_text": False,
        }
    ]
    assert "synthetic-private-provider-detail" not in output


def test_cli_preview_has_no_generation_calls(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with patch(
        "verisight.execution.gemini.GeminiTextGenerationClient._request",
        side_effect=AssertionError("No provider calls permitted"),
    ):
        assert main(_args(_source(tmp_path), "--preview")) == 0

    assert "generation_calls" not in json.loads(capsys.readouterr().out)
