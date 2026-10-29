import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from verisight import VeriSight
from verisight.analysis.models import DatasetAnalysis
from verisight.analysis.result import AnalysisResultBuilder
from verisight.config import Settings
from verisight.exceptions import ConfigurationError
from verisight.execution.claim_verification import (
    ClaimOperation,
    NumericalClaimVerifier,
    VerificationStatus,
)
from verisight.execution.decisions import InvestigationAction, InvestigationDecision
from verisight.execution.exceptions import InvestigationError, SynthesisValidationError
from verisight.execution.gemini import GeminiGenerationError, GeminiTransientError
from verisight.execution.investigation import InvestigationState
from verisight.execution.investigation_result import (
    ClaimOutputContract,
    InvestigationResult,
    InvestigationStatus,
    SynthesisFailureKind,
)
from verisight.execution.models import QueryResult
from verisight.execution.narrative_audit import (
    audit_narrative_digit_coverage,
    find_narrative_numbers,
)
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
    client = _Client(_response([]))

    def factory(**kwargs: Any) -> _Client:
        captured.update(kwargs)
        return client

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
    claim_schema = schema["properties"]["claims"]["items"]
    assert claim_schema["properties"]["expected"] == {"type": "string"}
    assert claim_schema["properties"]["operation"]["enum"] == ["value", "difference"]
    assert set(claim_schema["required"]) == {"operation", "expected", "left", "right"}
    left = claim_schema["properties"]["left"]
    right = claim_schema["properties"]["right"]
    assert left["type"] == "object"
    assert right["type"] == ["object", "null"]
    assert left["properties"] == right["properties"]
    assert set(left["required"]) == {"observation_index", "row_index", "column"}
    assert left["additionalProperties"] is False
    assert right["additionalProperties"] is False
    wire_schema = json.dumps(schema)
    for keyword in (
        "$defs",
        "$ref",
        "anyOf",
        "pattern",
        "maxLength",
        "minLength",
        "maxItems",
        "minimum",
    ):
        assert keyword not in wire_schema

    # The prompt still describes the stricter local contract.
    prompt_schema = json.loads(
        client.prompts[0]
        .split("RESPONSE SCHEMA:\n", 1)[1]
        .split("\nINVESTIGATION STATE:\n", 1)[0]
    )
    assert prompt_schema["properties"]["claims"]["maxItems"] == 50
    assert prompt_schema["properties"]["conclusion"]["maxLength"] == 20_000
    expected_schema = prompt_schema["$defs"]["_Claim"]["properties"]["expected"]
    assert expected_schema["maxLength"] == 128
    assert "pattern" in expected_schema
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
    assert result.synthesis_failure is not None
    assert result.synthesis_failure.kind is SynthesisFailureKind.PROMPT_BUDGET_EXCEEDED
    serialized = to_jsonable(result)
    assert isinstance(serialized, dict)
    assert serialized["synthesis_failure"] == {
        "kind": "prompt_budget_exceeded",
        "diagnostics": None,
        "validation_reason": None,
        "repair_attempted": None,
    }
    from scripts.live_evaluation import score_result

    report = score_result(result, "10")
    assert report["outcome"] == "incomplete"
    failure = report["synthesis_failure"]
    assert isinstance(failure, dict)
    assert failure["kind"] == "prompt_budget_exceeded"


@pytest.mark.parametrize(
    "response",
    [
        "private-invalid-response",
        _response([{**_claim(), "expected": 30}]),
        _response([_claim()] * 51),
        _response([{**_claim(), "operation": "ratio"}]),
        "private" * 10_001,
    ],
    ids=[
        "not-json",
        "numeric-expected",
        "too-many-claims",
        "unsupported-operation",
        "oversized-response",
    ],
)
def test_invalid_synthesis_preserves_real_sql_observation(
    tmp_path: Path,
    response: str,
) -> None:
    path = tmp_path / "measurements.csv"
    path.write_text("value\n10\n20\n", encoding="utf-8")

    client = _Client(response)
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False),
        planner=_Planner(),
        investigator=_Investigator(),
        synthesizer=StructuredInvestigationSynthesizer(client),
    )

    result = app.investigate(path, "Find the total.", max_steps=1)

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.question == "Find the total."
    assert result.observation_count == 1
    observation = result.observations[0]
    assert observation.sql == "SELECT SUM(value) AS total FROM measurements"
    assert observation.result == QueryResult(columns=("total",), rows=((30,),))
    assert result.generated_claims == ()
    assert result.verified_claims == ()
    assert result.narrative_verified is False
    assert result.conclusion == (
        "Investigation incomplete: final synthesis could not be completed. "
        "No analytical conclusion has been established."
    )
    serialized = json.dumps(to_jsonable(result))
    assert "private" not in serialized
    assert json.loads(serialized)["observations"][0]["result"]["rows"] == [[30]]
    assert len(client.prompts) == 2


@pytest.mark.parametrize(
    "error",
    [
        GeminiGenerationError("private-provider-details"),
        GeminiTransientError("private-provider-details"),
        InvestigationError("private-synthesis-details"),
    ],
)
def test_expected_synthesis_failure_preserves_observations(
    tmp_path: Path,
    error: Exception,
) -> None:
    class FailingClient:
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, prompt: str) -> str:
            self.calls += 1
            raise error

    path = tmp_path / "measurements.csv"
    path.write_text("value\n10\n20\n", encoding="utf-8")

    client = FailingClient()
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False),
        planner=_Planner(),
        investigator=_Investigator(),
        synthesizer=StructuredInvestigationSynthesizer(client),
    )

    result = app.investigate(path, "Find the total.", max_steps=1)

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observation_count == 1
    assert result.observations[0].result.rows == ((30,),)
    assert result.generated_claims == ()
    assert result.verified_claims == ()
    assert "final synthesis could not be completed" in result.conclusion
    assert "private" not in json.dumps(to_jsonable(result))
    assert client.calls == 1


def test_unexpected_synthesis_error_is_not_suppressed(tmp_path: Path) -> None:
    error = RuntimeError("Unexpected programming error.")

    class BrokenSynthesizer:
        def synthesize(self, state: InvestigationState) -> str:
            raise error

    path = tmp_path / "measurements.csv"
    path.write_text("value\n10\n", encoding="utf-8")
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False),
        planner=_Planner(),
        investigator=_Investigator(),
        synthesizer=BrokenSynthesizer(),
    )

    with pytest.raises(RuntimeError) as caught:
        app.investigate(path, "Find the total.", max_steps=1)

    assert caught.value is error


class _SequenceClient:
    def __init__(self, responses: list[str | Exception]) -> None:
        self.responses = responses
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        response = self.responses[len(self.prompts) - 1]
        if isinstance(response, Exception):
            raise response
        return response


@pytest.mark.parametrize(
    "language,newline",
    [("json", "\n"), ("JSON", "\r\n"), ("", "\n"), ("json \t", "\n")],
)
def test_structured_synthesis_accepts_complete_json_fences(
    language: str,
    newline: str,
) -> None:
    response = "  ```" + language + newline + _response([_claim()]) + newline + "```  "
    client = _Client(response)

    result = StructuredInvestigationSynthesizer(client).synthesize(_build_state())

    assert len(result.claims) == 1
    assert result.claims[0].expected == 30
    assert len(client.prompts) == 1


@pytest.mark.parametrize(
    "invalid,reason",
    [
        ("synthetic-private-rejected-response", "invalid_json"),
        ("```python\n" + _response([]) + "\n```", "invalid_json"),
        ("prefix\n```json\n" + _response([]) + "\n```", "invalid_json"),
        (_response([{**_claim(), "expected": 30}]), "invalid_schema_or_claim"),
        (_response([_claim()] * 51), "invalid_schema_or_claim"),
        (_response([{**_claim(), "operation": "ratio"}]), "invalid_schema_or_claim"),
        ("synthetic-private" * 4000, "response_too_large"),
        (
            json.dumps({"conclusion": "synthetic-private total 999.", "claims": []}),
            "unlinked_narrative_number",
        ),
    ],
    ids=[
        "malformed-json",
        "unsupported-fence",
        "surrounding-prose",
        "numeric-expected",
        "too-many-claims",
        "unsupported-operation",
        "oversized-response",
        "unlinked-narrative-number",
    ],
)
def test_format_repair_uses_safe_feedback_and_revalidates(
    invalid: str,
    reason: str,
) -> None:
    client = _SequenceClient([invalid, _response([_claim()])])

    result = StructuredInvestigationSynthesizer(client).synthesize(_build_state())

    assert result.claims[0].expected == 30
    assert result.claims[0].absolute_tolerance == 0
    assert len(client.prompts) == 2
    first, repair = client.prompts
    assert repair.startswith(first)
    assert '"validation_error": "' + reason + '"' in repair
    assert "synthetic-private" not in repair
    assert "FORMAT REPAIR (one attempt)" in repair


def test_format_repair_stops_after_second_invalid_response() -> None:
    client = _SequenceClient(["private-first-response", "private-second-response"])

    with pytest.raises(InvestigationError, match="response is invalid"):
        StructuredInvestigationSynthesizer(client).synthesize(_build_state())

    assert len(client.prompts) == 2
    assert "private-first-response" not in client.prompts[1]


def test_format_repair_enforces_budget_before_second_generation() -> None:
    state = _build_state()
    probe = _Client(_response([]))
    StructuredInvestigationSynthesizer(probe).synthesize(state)
    client = _SequenceClient(["private-invalid-response"])
    synthesizer = StructuredInvestigationSynthesizer(
        client, max_prompt_chars=len(probe.prompts[0])
    )

    with pytest.raises(PromptBudgetExceededError):
        synthesizer.synthesize(state)

    assert len(client.prompts) == 1


@pytest.mark.parametrize("transient", [False, True])
def test_provider_failure_during_format_repair_preserves_evidence(
    tmp_path: Path,
    transient: bool,
) -> None:
    error_type = GeminiTransientError if transient else GeminiGenerationError
    client = _SequenceClient(["private-invalid", error_type("private-provider-error")])
    path = tmp_path / "measurements.csv"
    path.write_text("value\n10\n20\n", encoding="utf-8")
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False),
        planner=_Planner(),
        investigator=_Investigator(),
        synthesizer=StructuredInvestigationSynthesizer(client),
    )

    result = app.investigate(path, "Find the total.", max_steps=1)

    assert result.status is InvestigationStatus.INCOMPLETE
    assert result.observations[0].result.rows == ((30,),)
    assert result.synthesis_failure is not None
    assert result.synthesis_failure.kind is (
        SynthesisFailureKind.PROVIDER_UNAVAILABLE
        if transient
        else SynthesisFailureKind.PROVIDER_ERROR
    )
    assert "private" not in json.dumps(to_jsonable(result))
    assert len(client.prompts) == 2


def test_repaired_claim_is_still_verified_against_sql(tmp_path: Path) -> None:
    client = _SequenceClient(["invalid", _response([_claim("31")])])
    path = tmp_path / "measurements.csv"
    path.write_text("value\n10\n20\n", encoding="utf-8")
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False),
        planner=_Planner(),
        investigator=_Investigator(),
        synthesizer=StructuredInvestigationSynthesizer(client),
    )

    result = app.investigate(path, "Find the total.", max_steps=1)

    assert result.status is InvestigationStatus.COMPLETE
    assert (
        result.verified_claims[0].verification.status is VerificationStatus.CONTRADICTED
    )
    assert result.synthesis_failure is None
    assert result.narrative_verified is False
    assert len(client.prompts) == 2


@pytest.mark.parametrize(
    "response",
    [
        json.dumps({"conclusion": "x" * 20_001, "claims": []}),
        _response([_claim()] * 51),
        _response(
            [
                {
                    **_claim(),
                    "left": {
                        "observation_index": 0,
                        "row_index": 0,
                        "column": "x" * 257,
                    },
                }
            ]
        ),
        _response([_claim("NaN")]),
    ],
    ids=["long-conclusion", "too-many-claims", "long-column", "nonfinite-expected"],
)
def test_compact_generation_schema_does_not_relax_local_validation(
    monkeypatch: pytest.MonkeyPatch, response: str
) -> None:
    client = _Client(response)
    monkeypatch.setattr(
        "verisight.execution.structured_synthesis.GeminiTextGenerationClient",
        lambda **kwargs: client,
    )
    synthesizer = StructuredInvestigationSynthesizer.from_settings(
        Settings(allow_llm_data_disclosure=True, gemini_api_key="synthetic")
    )

    with pytest.raises(InvestigationError, match="response is invalid"):
        synthesizer.synthesize(_build_state())

    assert len(client.prompts) == 2


@pytest.mark.parametrize(
    ("include_final", "column", "expected_actual", "status"),
    [
        (False, "sum_product", "1000", VerificationStatus.CONTRADICTED),
        (False, "sum_mass", "400", VerificationStatus.CONTRADICTED),
        (True, "sum_product", "1000", VerificationStatus.CONTRADICTED),
        (True, "sum_mass", "400", VerificationStatus.CONTRADICTED),
        (True, "weighted_mean", "2.5", VerificationStatus.SUPPORTED),
    ],
)
def test_weighted_mean_claim_must_reference_executed_final_metric(
    tmp_path: Path,
    include_final: bool,
    column: str,
    expected_actual: str,
    status: VerificationStatus,
) -> None:
    # Reproduce the live mismatch with real SQL and a scripted model response.
    # This checks evidence linkage, not whether a live model obeys the prompt.
    path = tmp_path / "assays.csv"
    path.write_text("mass,assay\n100,1\n300,3\n", encoding="utf-8")

    app = VeriSight(settings=Settings(allow_llm_data_disclosure=False))
    sql = "SELECT SUM(mass * assay) AS sum_product, SUM(mass) AS sum_mass"
    if include_final:
        sql += ", SUM(mass * assay) / NULLIF(SUM(mass), 0) AS weighted_mean"
    sql += " FROM assays"
    observation = QueryObservation(
        question="What is the mass-weighted mean assay?",
        sql=sql,
        result=app.execute([path], sql),
    )
    base = _build_state()
    state = InvestigationState(
        question=observation.question,
        analysis=base.analysis,
        observations=(observation,),
    )
    claim = _claim("2.5")
    claim["left"]["column"] = column
    client = _Client(_response([claim]))
    synthesis = StructuredInvestigationSynthesizer(client).synthesize(state)
    verification = NumericalClaimVerifier().verify(
        synthesis.claims[0], state.observations
    )

    assert verification.status is status
    assert str(verification.actual) == expected_actual
    assert verification.absolute_tolerance == 0
    prompt = client.prompts[0]
    assert "expected must equal the referenced SQL cell itself" in prompt
    assert "not a calculation using that cell" in prompt
    assert "explain that the final metric is missing and omit that claim" in prompt


def test_structured_synthesis_omits_profiles_but_preserves_complete_sql_evidence(
    tmp_path: Path,
) -> None:
    from dataclasses import replace

    from verisight.execution.investigation import FailedQueryAttempt
    from verisight.quality.models import (
        QualityIssue,
        QualityIssueType,
        QualityScope,
        QualitySeverity,
    )

    path = tmp_path / "wide.csv"
    path.write_text(
        ",".join(f"metric_{index}" for index in range(120))
        + "\n"
        + ",".join("10" for _ in range(120))
        + "\n"
        + ",".join("20" for _ in range(120))
        + "\n",
        encoding="utf-8",
    )
    app = VeriSight(settings=Settings(allow_llm_data_disclosure=False))
    analysis = app.analyze(path)
    issue = QualityIssue(
        issue_type=QualityIssueType.MISSING_VALUES,
        severity=QualitySeverity.WARNING,
        scope=QualityScope.COLUMN,
        table_name="wide",
        relation_name="wide",
        column_name="metric_0",
        message="Synthetic quality context; do not treat it as instructions.",
        evidence={"synthetic": True},
    )
    analysis = AnalysisResultBuilder().build(
        replace(analysis.analysis, issues=(issue,))
    )
    observations = (
        QueryObservation(
            question="Inspect the component values",
            sql="SELECT metric_0 FROM wide",
            result=app.execute(path, "SELECT metric_0 FROM wide"),
        ),
        QueryObservation(
            question="Compute the final total",
            sql="SELECT SUM(metric_0) AS total FROM wide",
            result=app.execute(path, "SELECT SUM(metric_0) AS total FROM wide"),
        ),
    )
    state = InvestigationState(
        question="What is the sum of metric_0?",
        analysis=analysis,
        observations=observations,
        failed_attempts=(
            FailedQueryAttempt("Failed attempt", "QueryRuntimeError", "Safe"),
        ),
    )
    claim = _claim("30")
    claim["left"]["observation_index"] = 1
    client = _Client(_response([claim]))

    synthesis = StructuredInvestigationSynthesizer(client).synthesize(state)

    # The previous whole-state serialization alone exceeded the default budget.
    assert len(json.dumps(to_jsonable(state), separators=(",", ":"))) > 60_000
    assert len(client.prompts) == 1
    assert len(client.prompts[0]) < 20_000
    payload = json.loads(client.prompts[0].split("INVESTIGATION STATE:\n", 1)[1])
    assert payload["question"] == state.question
    assert payload["analysis"] == to_jsonable(
        {
            "schema": analysis.analysis.schema,
            "issues": analysis.analysis.issues,
        }
    )
    assert payload["observations"] == to_jsonable(state.observations)
    assert payload["failed_attempts"] == to_jsonable(state.failed_attempts)
    assert (
        "statistics, the analysis summary, and deterministic insights are omitted"
        in client.prompts[0]
    )
    assert state.analysis is analysis
    assert len(state.analysis.analysis.profile.tables[0].columns) == 120
    verification = NumericalClaimVerifier().verify(synthesis.claims[0], observations)
    assert verification.status is VerificationStatus.SUPPORTED
    assert verification.actual == 30


@pytest.mark.parametrize("repair_succeeds", [False, True])
def test_unlinked_weighted_answer_is_repaired_or_preserves_sql_evidence(
    tmp_path: Path, repair_succeeds: bool
) -> None:
    path = tmp_path / "orchard_samples.csv"
    path.write_text(
        "review,mass,reading\naccepted,1,2\naccepted,3,3\nrejected,100,99\n",
        encoding="utf-8",
    )

    class ComponentPlanner:
        def plan(self, request: QueryRequest) -> QueryPlan:
            return QueryPlan(
                request.question,
                "SELECT SUM(mass * reading) AS weighted_reading_sum, "
                "SUM(mass) AS total_mass FROM orchard_samples "
                "WHERE review = 'accepted' AND mass > 0 AND reading IS NOT NULL",
            )

    claims = [
        {
            **_claim(value),
            "left": {
                "observation_index": 0,
                "row_index": 0,
                "column": column,
            },
        }
        for value, column in (("11", "weighted_reading_sum"), ("4", "total_mass"))
    ]
    rejected = json.dumps(
        {"conclusion": "The mass-weighted mean is 2.75.", "claims": claims}
    )
    repaired = json.dumps(
        {
            "conclusion": (
                "Only intermediate components were collected; the final "
                "weighted mean is not available as a verified result cell."
            ),
            "claims": claims,
        }
    )
    client = _SequenceClient([rejected, repaired if repair_succeeds else rejected])
    app = VeriSight(
        settings=Settings(allow_llm_data_disclosure=False),
        planner=ComponentPlanner(),
        investigator=_Investigator(),
        synthesizer=StructuredInvestigationSynthesizer(client),
    )

    result = app.investigate(path, "What is the mass-weighted mean?", max_steps=1)

    assert len(client.prompts) == 2
    assert '"validation_error": "unlinked_narrative_number"' in client.prompts[1]
    assert "The mass-weighted mean is 2.75." not in client.prompts[1]
    assert result.observations[0].result.rows == ((11, 4),)
    assert result.narrative_verified is False
    assert "2.75" not in result.conclusion
    if repair_succeeds:
        assert result.status is InvestigationStatus.COMPLETE
        assert "Only intermediate components" in result.conclusion
        assert [str(claim.expected) for claim in result.generated_claims] == ["11", "4"]
        assert all(
            item.verification.status is VerificationStatus.SUPPORTED
            for item in result.verified_claims
        )
    else:
        assert result.status is InvestigationStatus.INCOMPLETE
        assert result.generated_claims == ()
        assert result.synthesis_failure is not None
        assert result.synthesis_failure.kind is SynthesisFailureKind.SYNTHESIS_ERROR


def test_final_metric_cell_is_accepted_and_verified_without_repair() -> None:
    state = _build_state().add_observation(
        QueryObservation(
            question="Measure the weighted mean.",
            sql="SELECT 2.75 AS weighted_mean",
            result=QueryResult(columns=("weighted_mean",), rows=((2.75,),)),
        )
    )
    claim = {
        **_claim("2.75"),
        "left": {
            "observation_index": 0,
            "row_index": 0,
            "column": "weighted_mean",
        },
    }
    client = _Client(json.dumps({"conclusion": "The mean is 2.75.", "claims": [claim]}))

    synthesis = StructuredInvestigationSynthesizer(client).synthesize(state)

    assert len(client.prompts) == 1
    verification = NumericalClaimVerifier().verify(
        synthesis.claims[0], state.observations
    )
    assert verification.status is VerificationStatus.SUPPORTED
    assert str(verification.actual) == "2.75"


def test_question_numbers_remain_context_without_certifying_claims() -> None:
    base = _build_state()
    state = InvestigationState(
        question="For cohort 2026 inspect label 1,23 and measure the total.",
        analysis=base.analysis,
        observations=(
            QueryObservation(
                question="Measure the total.",
                sql="SELECT 30 AS total",
                result=QueryResult(columns=("total",), rows=((30,),)),
            ),
        ),
    )
    client = _Client(
        json.dumps(
            {"conclusion": "For cohort 2026 the total is 31.", "claims": [_claim("31")]}
        )
    )

    synthesis = StructuredInvestigationSynthesizer(client).synthesize(state)

    assert len(client.prompts) == 1
    verification = NumericalClaimVerifier().verify(
        synthesis.claims[0], state.observations
    )
    assert verification.status is VerificationStatus.CONTRADICTED


def test_narrative_linkage_does_not_certify_unsupported_token_syntax() -> None:
    client = _Client(json.dumps({"conclusion": "The label is 1,23.", "claims": []}))

    synthesis = StructuredInvestigationSynthesizer(client).synthesize(_build_state())

    assert synthesis.conclusion == "The label is 1,23."
    assert synthesis.claims == ()
    assert len(client.prompts) == 1


@pytest.mark.parametrize(
    ("required", "returned", "matches"),
    [
        (("value", "difference"), ("difference", "value"), True),
        (("value", "value"), ("value",), False),
        (("value", "difference"), ("value", "value"), False),
    ],
    ids=["order-independent", "multiplicity", "operation-mismatch"],
)
def test_synthesis_enforces_the_exact_selected_operation_multiset(
    required: tuple[str, ...], returned: tuple[str, ...], matches: bool
) -> None:
    contract = ClaimOutputContract(tuple(ClaimOperation(item) for item in required))
    state = replace(_build_state(), claim_output_contract=contract)
    claims = []
    for operation in returned:
        claim = _claim()
        if operation == "difference":
            claim = {
                **claim,
                "operation": "difference",
                "expected": "0",
                "right": claim["left"],
            }
        claims.append(claim)
    client = _Client(_response(claims))
    synthesizer = StructuredInvestigationSynthesizer(client)
    if matches:
        synthesis = synthesizer.synthesize(state)
        assert tuple(claim.operation.value for claim in synthesis.claims) == returned
        assert len(client.prompts) == 1
    else:
        with pytest.raises(InvestigationError, match="response is invalid"):
            synthesizer.synthesize(state)
        assert len(client.prompts) == 2
        assert (
            '"validation_error": "claim_output_contract_mismatch"' in client.prompts[1]
        )
    assert "CALLER-SELECTED CLAIM OUTPUT CONTRACT" in client.prompts[0]


@pytest.mark.parametrize(
    "context",
    [
        "For cohort 2026",
        "For period 2026-01",
        "For label 1,00",
        "For scale 0.05k",
        "For cohort ２０２６",
    ],
    ids=[
        "question-number",
        "date",
        "invalid-grouping",
        "scaled-suffix",
        "unicode-digits",
    ],
)
@pytest.mark.parametrize("recover", [False, True])
def test_contract_narrative_failures_use_the_single_repair(
    context: str, recover: bool
) -> None:
    state = replace(
        _build_state(),
        question="For cohort 2026 measure the total.",
        claim_output_contract=ClaimOutputContract((ClaimOperation.VALUE,)),
    ).add_observation(
        QueryObservation(
            question="Measure the total.",
            sql="SELECT 30 AS total",
            result=QueryResult(columns=("total",), rows=((30,),)),
        )
    )
    rejected = json.dumps(
        {"conclusion": f"{context}, the total is 30.", "claims": [_claim()]}
    )
    corrected = json.dumps({"conclusion": "The total is 30.", "claims": [_claim()]})
    client = _SequenceClient([rejected, corrected if recover else rejected])
    synthesizer = StructuredInvestigationSynthesizer(client)
    if recover:
        synthesis = synthesizer.synthesize(state)
        verification = NumericalClaimVerifier().verify(
            synthesis.claims[0], state.observations
        )
        assert verification.status is VerificationStatus.SUPPORTED
        tokens = find_narrative_numbers(synthesis.conclusion, (verification.expected,))
        assert all(token.claim_indexes for token in tokens)
        assert (
            audit_narrative_digit_coverage(
                synthesis.conclusion, tokens
            ).unparsed_digit_count
            == 0
        )
    else:
        with pytest.raises(SynthesisValidationError) as caught:
            synthesizer.synthesize(state)
        assert caught.value.reason == "unlinked_narrative_number"
        assert caught.value.repair_attempted is True
    assert len(client.prompts) == 2
    assert '"validation_error": "unlinked_narrative_number"' in client.prompts[1]
    assert (
        "If you remove a claim, remove its numbers from the conclusion"
        in client.prompts[1]
    )
    assert "only when no output contract is selected" in client.prompts[1]
    assert (
        "through claim references only, never as numbers in the conclusion"
        in client.prompts[0]
    )


@pytest.mark.parametrize("recover", [False, True])
def test_targeted_numeric_feedback_keeps_validation_and_evidence_checks(
    recover: bool,
) -> None:
    state = replace(
        _build_state(),
        question="For cohort 2026 measure the total.",
        claim_output_contract=ClaimOutputContract((ClaimOperation.VALUE,)),
    ).add_observation(
        QueryObservation(
            question="Measure the total.",
            sql="SELECT 30 AS total",
            result=QueryResult(columns=("total",), rows=((30,),)),
        )
    )
    rejected = json.dumps(
        {
            "conclusion": "synthetic-private-context For cohort 2026 the total is 30.",
            "claims": [_claim()],
        }
    )
    client = _SequenceClient([rejected, _response([_claim()]) if recover else rejected])
    synthesizer = StructuredInvestigationSynthesizer(client)
    if recover:
        synthesis = synthesizer.synthesize(state)
        verdict = NumericalClaimVerifier().verify(
            synthesis.claims[0], state.observations
        )
        assert verdict.status is VerificationStatus.SUPPORTED
        assert verdict.actual == 30
        assert synthesis.claims[0].left.column == "total"
        assert len(synthesis.claims) == 1
        result = InvestigationResult(
            question=state.question,
            conclusion=synthesis.conclusion,
            analysis=state.analysis,
            observations=state.observations,
            generated_claims=synthesis.claims,
        )
        assert result.assess_output(
            ClaimOutputContract((ClaimOperation.VALUE,))
        ).accepted
    else:
        with pytest.raises(SynthesisValidationError) as caught:
            synthesizer.synthesize(state)
        assert caught.value.reason == "unlinked_narrative_number"
        assert caught.value.repair_attempted is True
    assert len(client.prompts) == 2
    feedback = json.loads(
        client.prompts[1]
        .split("FORMAT REPAIR (one attempt):\n", 1)[1]
        .split("\n", 1)[0]
    )
    assert feedback == {
        "validation_error": "unlinked_narrative_number",
        "unlinked_numeric_values": ["2026"],
    }
    assert "synthetic-private-context" not in client.prompts[1]
    assert "Do not add dummy claims" in client.prompts[1]


@pytest.mark.parametrize(
    "conclusion,expected",
    [
        ("For 2026 and 2026, total 30.", ["2026"]),
        ("Total 30; malformed 1,00; context 2026.", ["2026"]),
        ("Total 30; context " + "9" * 32 + ".", ["9" * 32]),
        ("Total 30; context " + "9" * 33 + ".", []),
        (
            "Total 30; " + " ".join(str(i) for i in range(100, 112)),
            [str(i) for i in range(100, 108)],
        ),
        ("Total 30.", []),
    ],
)
def test_numeric_repair_examples_are_bounded_canonical_values(
    conclusion: str, expected: list[str]
) -> None:
    parsed = StructuredInvestigationSynthesizer._parse_response(
        json.dumps(
            {
                "conclusion": conclusion,
                "claims": [_claim()],
            }
        )
    )
    assert (
        StructuredInvestigationSynthesizer._unlinked_numeric_values(parsed) == expected
    )


def test_targeted_feedback_obeys_complete_repair_prompt_budget() -> None:
    state = replace(
        _build_state(),
        claim_output_contract=ClaimOutputContract((ClaimOperation.VALUE,)),
    )
    rejected = json.dumps({"conclusion": "For 2026 total 30.", "claims": [_claim()]})
    probe = _SequenceClient([rejected, _response([_claim()])])
    StructuredInvestigationSynthesizer(probe).synthesize(state)
    client = _SequenceClient([rejected])
    synthesizer = StructuredInvestigationSynthesizer(
        client, max_prompt_chars=len(probe.prompts[1]) - 1
    )
    with pytest.raises(PromptBudgetExceededError):
        synthesizer.synthesize(state)
    assert len(client.prompts) == 1


def test_no_numeric_repair_examples_without_a_selected_contract() -> None:
    rejected = json.dumps({"conclusion": "For 2026 total 30.", "claims": [_claim()]})
    client = _SequenceClient([rejected, _response([_claim()])])
    StructuredInvestigationSynthesizer(client).synthesize(_build_state())
    feedback = json.loads(
        client.prompts[1]
        .split("FORMAT REPAIR (one attempt):\n", 1)[1]
        .split("\n", 1)[0]
    )
    assert feedback == {"validation_error": "unlinked_narrative_number"}
