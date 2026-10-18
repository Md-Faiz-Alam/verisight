import json
from pathlib import Path
from typing import Any

import pytest

from verisight import VeriSight
from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.config import Settings
from verisight.exceptions import ConfigurationError
from verisight.execution.claim_verification import VerificationStatus
from verisight.execution.decisions import InvestigationAction, InvestigationDecision
from verisight.execution.exceptions import InvestigationError
from verisight.execution.gemini import GeminiGenerationError, GeminiTransientError
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_result import InvestigationStatus
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation
from verisight.execution.planning import QueryPlan, QueryRequest
from verisight.execution.prompt_budget import PromptBudgetExceededError
from verisight.execution.structured_synthesis import StructuredInvestigationSynthesizer
from verisight.execution.synthesis import InvestigationSynthesizer, StructuredSynthesis
from verisight.ingestion.schema import DatasetSchema
from verisight.profiling.models import DatasetProfile
from verisight.serialization import to_jsonable


class StubInvestigationSynthesizer:
    """Deterministic investigation synthesizer for contract tests."""

    def synthesize(self, state: InvestigationState) -> str:
        return f"Conclusion for: {state.question}"


def _build_state() -> InvestigationState:
    analysis = DatasetAnalysis(
        schema=DatasetSchema(tables=()),
        profile=DatasetProfile(tables=()),
        issues=(),
    )

    return InvestigationState(
        question="Why did revenue decline?",
        analysis=AnalysisResultBuilder().build(analysis),
    )


def _synthesize(
    synthesizer: InvestigationSynthesizer,
    state: InvestigationState,
) -> str | StructuredSynthesis:
    return synthesizer.synthesize(state)


def test_investigation_synthesizer_contract() -> None:
    conclusion = _synthesize(
        StubInvestigationSynthesizer(),
        _build_state(),
    )

    assert conclusion == "Conclusion for: Why did revenue decline?"


class _Client:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.response


def _claim(expected: str = "30") -> dict[str, Any]:
    return {
        "operation": "value",
        "expected": expected,
        "left": {"observation_index": 0, "row_index": 0, "column": "total"},
        "right": None,
    }


def _response(claims: list[dict[str, Any]]) -> str:
    return json.dumps(
        {"conclusion": "The totals require interpretation.", "claims": claims}
    )


def test_structured_synthesis_preserves_exact_expected_values() -> None:
    client = _Client(_response([_claim("9007199254740993.125")]))
    result = StructuredInvestigationSynthesizer(client).synthesize(_build_state())

    assert str(result.claims[0].expected) == "9007199254740993.125"
    assert result.claims[0].absolute_tolerance == 0
    assert result.claims[0].left.observation_index == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("expected", 30),
        ("expected", True),
        ("expected", "NaN"),
        ("expected", "Infinity"),
        ("expected", "1e" + "9" * 100),
        ("expected", "9" * 129),
        ("operation", "ratio"),
        ("operation", "difference"),
        ("absolute_tolerance", "1000000"),
        ("right", {"observation_index": 0, "row_index": 0, "column": "total"}),
        ("left", {"observation_index": True, "row_index": 0, "column": "total"}),
        ("left", {"observation_index": -1, "row_index": 0, "column": "total"}),
        ("left", {"observation_index": 0, "row_index": -1, "column": "total"}),
        ("left", {"observation_index": 0, "row_index": 0, "column": ""}),
        (
            "left",
            {"observation_index": 0, "row_index": 0, "column": "total", "extra": 1},
        ),
    ],
)
def test_structured_synthesis_rejects_invalid_claims(field: str, value: Any) -> None:
    claim = _claim()
    claim[field] = value
    client = _Client(_response([claim]))

    with pytest.raises(InvestigationError, match="response is invalid"):
        StructuredInvestigationSynthesizer(client).synthesize(_build_state())


@pytest.mark.parametrize(
    "response",
    [
        "",
        "not json",
        "[]",
        '{"conclusion":"Done.","conclusion":"Other.","claims":[]}',
        '{"conclusion":"Done.","claims":[],"extra":NaN}',
        '{"conclusion":"Done.","claims":[],"extra":1}',
        '{"conclusion":"  ","claims":[]}',
        '{"conclusion":"Done."}',
        _response([_claim()] * 51),
    ],
)
def test_structured_synthesis_rejects_invalid_responses(response: str) -> None:
    with pytest.raises(InvestigationError, match="response is invalid"):
        StructuredInvestigationSynthesizer(_Client(response)).synthesize(_build_state())


def test_structured_synthesis_rejects_oversized_response() -> None:
    with pytest.raises(InvestigationError, match="response is too large"):
        StructuredInvestigationSynthesizer(_Client("x" * 60_001)).synthesize(
            _build_state()
        )


def test_structured_synthesis_preserves_full_evidence_and_zero_based_indices() -> None:
    base = _build_state()
    state = InvestigationState(
        question=base.question,
        analysis=base.analysis,
        observations=(
            QueryObservation(
                question="Read synthetic values",
                sql="SELECT value FROM synthetic",
                result=QueryResult(
                    columns=("value",), rows=tuple((i,) for i in range(105))
                ),
            ),
        ),
    )
    client = _Client(_response([]))

    result = StructuredInvestigationSynthesizer(client).synthesize(state)

    assert result.claims == ()
    prompt = client.prompts[0]
    assert "ZERO-BASED" in prompt
    assert "untrusted data" in prompt
    payload = json.loads(prompt.split("INVESTIGATION STATE:\n", 1)[1])
    assert payload["observations"][0]["result"]["rows"][-1] == [104]
    assert len(payload["observations"][0]["result"]["rows"]) == 105


def test_structured_synthesis_checks_budget_before_generation() -> None:
    client = _Client(_response([]))

    with pytest.raises(PromptBudgetExceededError):
        StructuredInvestigationSynthesizer(client, max_prompt_chars=1).synthesize(
            _build_state()
        )

    assert client.prompts == []


@pytest.mark.parametrize(
    "error",
    [
        GeminiGenerationError("private"),
        GeminiTransientError("private"),
        RuntimeError("private"),
    ],
)
def test_structured_synthesis_preserves_error_classification(error: Exception) -> None:
    class FailingClient:
        def generate(self, prompt: str) -> str:
            raise error

    synthesizer = StructuredInvestigationSynthesizer(FailingClient())
    if type(error) is GeminiGenerationError:
        with pytest.raises(InvestigationError, match="generation failed") as caught:
            synthesizer.synthesize(_build_state())
        assert caught.value.__cause__ is error
    else:
        with pytest.raises(type(error)) as caught_original:
            synthesizer.synthesize(_build_state())
        assert caught_original.value is error


@pytest.mark.parametrize(
    ("permission", "key"), [(False, "synthetic"), (True, None), (True, " ")]
)
def test_structured_factory_requires_permission_and_credentials(
    permission: bool, key: str | None
) -> None:
    with pytest.raises(ConfigurationError):
        StructuredInvestigationSynthesizer.from_settings(
            Settings(allow_llm_data_disclosure=permission, gemini_api_key=key)
        )


def test_structured_factory_configures_gemini_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def factory(**kwargs: Any) -> _Client:
        captured.update(kwargs)
        return _Client(_response([]))

    monkeypatch.setattr(
        "verisight.execution.structured_synthesis.GeminiTextGenerationClient", factory
    )
    synthesizer = StructuredInvestigationSynthesizer.from_settings(
        Settings(
            allow_llm_data_disclosure=True,
            gemini_api_key="synthetic",
            gemini_model="test-model",
        )
    )

    assert synthesizer.synthesize(_build_state()).claims == ()
    schema = captured["response_json_schema"]
    assert set(schema["required"]) == {"conclusion", "claims"}
    assert schema["additionalProperties"] is False
    assert schema["$defs"]["_Claim"]["properties"]["expected"]["type"] == "string"
    assert captured["model"] == "test-model"


class _Planner:
    def plan(self, request: QueryRequest) -> QueryPlan:
        return QueryPlan(
            request.question, "SELECT SUM(value) AS total FROM measurements"
        )


class _Investigator:
    def decide(self, state: InvestigationState) -> InvestigationDecision:
        if state.observations:
            return InvestigationDecision(
                InvestigationAction.FINISH, "Evidence collected."
            )
        return InvestigationDecision(
            InvestigationAction.INVESTIGATE, "Need a total.", "What is the total?"
        )


def test_generated_claims_are_verified_automatically_in_real_investigation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "measurements.csv"
    path.write_text("value\n10\n20\n", encoding="utf-8")
    missing = _claim()
    missing["left"]["observation_index"] = 99
    difference = _claim("0")
    difference["operation"] = "difference"
    difference["right"] = dict(difference["left"])
    client = _Client(_response([_claim(), _claim("31"), missing, difference]))
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False),
        planner=_Planner(),
        investigator=_Investigator(),
        synthesizer=StructuredInvestigationSynthesizer(client),
    )

    result = app.investigate(path, "Find the total.", max_steps=1)

    assert result.status is InvestigationStatus.COMPLETE
    assert len(result.generated_claims) == 4
    assert result.narrative_verified is False
    assert [item.verification.status for item in result.verified_claims] == [
        VerificationStatus.SUPPORTED,
        VerificationStatus.CONTRADICTED,
        VerificationStatus.UNVERIFIABLE,
        VerificationStatus.SUPPORTED,
    ]
    assert len(client.prompts) == 1
    serialized = json.loads(json.dumps(to_jsonable(result)))
    assert serialized["verified_claims"][0]["verification"]["actual"] == "30"
    assert serialized["verified_claims"][1]["verification"]["status"] == "contradicted"
    assert serialized["verification_scope"] == "referenced_numeric_values_only"
    assert serialized["narrative_verified"] is False
    assert (
        serialized["observations"][0]["sql"]
        == "SELECT SUM(value) AS total FROM measurements"
    )


def test_structured_budget_failure_preserves_incomplete_investigation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "measurements.csv"
    path.write_text("value\n10\n", encoding="utf-8")
    client = _Client(_response([]))
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False),
        planner=_Planner(),
        investigator=_Investigator(),
        synthesizer=StructuredInvestigationSynthesizer(client, max_prompt_chars=1),
    )

    result = app.investigate(path, "Find the total.", max_steps=1)

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == 1
    assert result.verified_claims == ()
    assert client.prompts == []
