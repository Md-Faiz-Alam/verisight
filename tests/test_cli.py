"""CLI boundary tests using real synthetic ingestion/SQL and offline providers."""

import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from typing import IO, Any, cast
from unittest.mock import patch

import pytest

from verisight import VeriSight
from verisight.cli import main
from verisight.config import Settings
from verisight.execution.claim_verification import (
    ClaimOperation,
    EvidenceReference,
    NumericalClaim,
)
from verisight.execution.gemini import GeminiTransientError
from verisight.execution.investigation_result import (
    ClaimOutputContract,
    InvestigationResult,
    InvestigationStatus,
)
from verisight.execution.models import QueryResult
from verisight.execution.observations import QueryObservation
from verisight.serialization import to_jsonable


@pytest.fixture(autouse=True)
def offline_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERISIGHT_GEMINI_API_KEY", "offline-secret-key")
    monkeypatch.setenv("VERISIGHT_ALLOW_LLM_DATA_DISCLOSURE", "true")
    monkeypatch.setenv("VERISIGHT_GEMINI_MODEL", "offline-model")


@pytest.fixture
def source(tmp_path: Path) -> Path:
    path = tmp_path / "orders.csv"
    path.write_text(
        "state,amount\nactive,10\nother,900\nactive,20\nother,\n", encoding="utf-8"
    )
    return path


@pytest.fixture
def population(tmp_path: Path) -> Path:
    path = tmp_path / "population.json"
    # Windows PowerShell commonly writes UTF-8 files with a BOM.
    path.write_text(
        json.dumps([{"relation": "orders", "column": "state", "values": ["active"]}]),
        encoding="utf-8-sig",
    )
    return path


def responses(mode: str = "supported") -> list[str | Exception]:
    return [
        json.dumps(
            {"action": "investigate", "reasoning": "Measure", "question": "Sum amounts"}
        ),
        "SELECT SUM(amount) AS total FROM orders",
        GeminiTransientError("provider-private-secret")
        if mode == "incomplete"
        else json.dumps({"action": "finish", "reasoning": "Done", "question": None}),
        json.dumps(
            {
                "conclusion": "The total is 31."
                if mode == "contradicted"
                else "The total is 30.",
                "claims": [
                    {
                        "operation": "value",
                        "expected": "31" if mode == "contradicted" else "30",
                        "left": {
                            "observation_index": 0,
                            "row_index": 0,
                            "column": "total",
                        },
                        "right": None,
                    }
                ],
            }
        ),
    ]


def test_profile_is_offline_and_export_is_explicit(
    source: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "profile.json"
    with patch(
        "verisight.execution.gemini.GeminiTextGenerationClient.generate",
        side_effect=AssertionError("Network forbidden"),
    ) as generate:
        assert main(["profile", str(source), "--output", str(output)]) == 0
    generate.assert_not_called()
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert report["kind"] == "profile"
    assert report["profile"]["summary"]["total_row_count"] == 4
    assert report["profile"]["information_scope"] == "original_loaded_dataset"
    assert report["profile"]["schema"]["tables"][0]["relation_name"] == "orders"
    assert report["profile"]["quality_findings"]
    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert "offline-secret-key" not in captured.out + captured.err
    assert source.read_text(encoding="utf-8").startswith("state,amount")


def test_preview_exposes_scope_and_budgets_without_generation(
    source: Path, population: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with patch(
        "verisight.execution.gemini.GeminiTextGenerationClient.generate",
        side_effect=AssertionError("Network forbidden"),
    ) as generate:
        assert (
            main(
                [
                    "investigate",
                    str(source),
                    "--question",
                    "Sum active amounts",
                    "--population",
                    str(population),
                    "--preview",
                    "--max-steps",
                    "2",
                    "--max-seconds",
                    "15",
                    "--request-timeout-seconds",
                    "5",
                ]
            )
            == 0
        )
    generate.assert_not_called()
    report = json.loads(capsys.readouterr().out)
    assert report["kind"] == "investigation_preview"
    request = report["request"]
    assert request["population"][0]["values"] == ["active"]
    assert request["max_steps"] == 2
    assert request["max_investigation_seconds"] == 15
    assert request["request_timeout_seconds"] == 5
    assert report["profile"]["summary"]["total_row_count"] == 4


@pytest.mark.parametrize("mode", ["supported", "contradicted", "incomplete"])
def test_investigation_keeps_scope_evidence_and_verdicts_separate(
    source: Path,
    population: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mode: str,
) -> None:
    output = tmp_path / "investigation.json"
    with patch(
        "verisight.execution.gemini.GeminiTextGenerationClient.generate",
        side_effect=responses(mode),
    ):
        code = main(
            [
                "investigate",
                str(source),
                "--question",
                "Sum active amounts",
                "--population",
                str(population),
                "--allow-llm-data-disclosure",
                "--output",
                str(output),
            ]
        )
    report = json.loads(capsys.readouterr().out)
    assert code == (1 if mode == "incomplete" else 0)
    assert report["workflow_status"] == (
        "incomplete" if mode == "incomplete" else "complete"
    )
    assert report["profile"]["information_scope"] == "original_loaded_dataset"
    assert report["population"][0]["values"] == ["active"]
    investigation = report["investigation"]
    assert investigation["observations"][0]["result"]["rows"] == [[30]]
    assert investigation["narrative_verified"] is False
    if mode == "incomplete":
        assert investigation["investigation_failure"]["kind"] == "provider_unavailable"
    else:
        assert investigation["verified_claims"][0]["verification"]["status"] == mode
        assert report["numerical_statements"][0]["text"]
    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert "offline-secret-key" not in output.read_text(encoding="utf-8")
    assert "provider-private-secret" not in output.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["profile"],
        ["investigate", "x.csv", "--question", " ", "--preview"],
        ["investigate", "x.csv", "--question", "Sum"],
        ["investigate", "x.csv", "--question", "Sum", "--preview", "--max-steps", "0"],
        [
            "investigate",
            "x.csv",
            "--question",
            "Sum",
            "--preview",
            "--max-steps",
            "bad",
        ],
        [
            "investigate",
            "x.csv",
            "--question",
            "Sum",
            "--preview",
            "--max-seconds",
            "nan",
        ],
        [
            "investigate",
            "x.csv",
            "--question",
            "Sum",
            "--preview",
            "--max-seconds",
            "0",
        ],
        [
            "investigate",
            "x.csv",
            "--question",
            "Sum",
            "--preview",
            "--request-timeout-seconds",
            "inf",
        ],
        [
            "investigate",
            "x.csv",
            "--question",
            "Sum",
            "--preview",
            "--max-seconds",
            "bad",
        ],
    ],
)
def test_invalid_commands_stop_before_dataset_or_provider_access(
    arguments: list[str],
) -> None:
    with patch("verisight.cli.VeriSight") as app, pytest.raises(SystemExit) as caught:
        main(arguments)
    assert caught.value.code == 2
    app.assert_not_called()


@pytest.mark.parametrize(
    "content",
    [
        b"{broken",
        b"\xff",
        b"{}",
        b"[null]",
        b"[{}]",
        b'[{"relation":"orders","column":"state","values":"active"}]',
        b'[{"relation":"orders","column":"state","values":[]}]',
        b'[{"relation":"orders","column":"state","values":["active",1]}]',
        b'[{"relation":"orders","relation":"secret","column":"state","values":["active"]}]',
        b" " * 65_537,
        json.dumps([{}] * 33).encode(),
        json.dumps(
            [{"relation": "orders", "column": "state", "values": ["active"] * 129}]
        ).encode(),
        b"[" * 2000 + b"]" * 2000,
    ],
    ids=[
        "malformed-json",
        "invalid-utf8",
        "not-an-array",
        "null-filter",
        "missing-fields",
        "values-not-an-array",
        "empty-values",
        "mixed-value-types",
        "duplicate-key",
        "oversized-file",
        "too-many-filters",
        "too-many-values",
        "excessive-nesting",
    ],
)
def test_invalid_population_never_reaches_generation(
    source: Path, tmp_path: Path, content: bytes, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "population.json"
    path.write_bytes(content)
    with patch("verisight.cli.VeriSight") as app, pytest.raises(SystemExit) as caught:
        main(
            [
                "investigate",
                str(source),
                "--question",
                "Sum",
                "--population",
                str(path),
                "--preview",
            ]
        )
    assert caught.value.code == 2
    app.assert_not_called()
    assert "secret" not in capsys.readouterr().err


def test_missing_population_file_has_a_safe_input_error(
    source: Path, tmp_path: Path
) -> None:
    with pytest.raises(SystemExit) as caught:
        main(
            [
                "investigate",
                str(source),
                "--question",
                "Sum",
                "--population",
                str(tmp_path / "missing.json"),
                "--preview",
            ]
        )
    assert caught.value.code == 2


def test_unknown_scope_and_dataset_failures_are_classified(
    source: Path, population: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    population.write_text(
        '[{"relation":"missing","column":"state","values":["active"]}]',
        encoding="utf-8",
    )
    assert (
        main(
            [
                "investigate",
                str(source),
                "--question",
                "Sum",
                "--population",
                str(population),
                "--preview",
            ]
        )
        == 1
    )
    assert (
        json.loads(capsys.readouterr().out)["error"]["code"] == "query_validation_error"
    )
    assert main(["profile", str(source.with_name("missing.csv"))]) == 1
    assert (
        json.loads(capsys.readouterr().out)["error"]["code"] == "file_validation_error"
    )


@pytest.mark.parametrize("mode", ["missing-key", "invalid-settings"])
def test_configuration_failures_hide_secrets(
    source: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
) -> None:
    if mode == "missing-key":
        monkeypatch.setenv("VERISIGHT_GEMINI_API_KEY", "")
    else:
        monkeypatch.setenv("VERISIGHT_MAX_UPLOAD_SIZE_MB", "secret-invalid-value")
    assert (
        main(
            [
                "investigate",
                str(source),
                "--question",
                "Sum",
                "--allow-llm-data-disclosure",
            ]
        )
        == 1
    )
    output = capsys.readouterr()
    assert json.loads(output.out)["error"]["code"] == "configuration_error"
    assert "secret-invalid-value" not in output.out + output.err
    assert "offline-secret-key" not in output.out + output.err


@pytest.mark.parametrize("mode", ["existing", "missing-parent", "symlink"])
def test_export_preflight_stops_before_work(
    source: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    output = tmp_path / "report.json"
    if mode == "existing":
        output.write_text("retain", encoding="utf-8")
    elif mode == "missing-parent":
        output = tmp_path / "missing" / "report.json"
    else:
        monkeypatch.setattr(Path, "is_symlink", lambda self: self == output)
    with patch("verisight.cli.VeriSight") as app, pytest.raises(SystemExit):
        main(["profile", str(source), "--output", str(output)])
    app.assert_not_called()
    if mode == "existing":
        assert output.read_text(encoding="utf-8") == "retain"


def test_export_race_preserves_existing_file_and_stdout(
    source: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "report.json"
    original_open = Path.open

    def race(self: Path, mode: str = "r", *args: Any, **kwargs: Any) -> IO[Any]:
        if self == output and mode == "x":
            with original_open(self, "w", encoding="utf-8") as target:
                target.write("retain")
        return original_open(self, mode, *args, **kwargs)

    with patch.object(Path, "open", race):
        assert main(["profile", str(source), "--output", str(output)]) == 2
    assert output.read_text(encoding="utf-8") == "retain"
    captured = capsys.readouterr()
    assert json.loads(captured.out)["kind"] == "profile"
    assert "Could not export" in captured.err


def test_keyboard_interrupt_has_no_completed_report(
    source: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with patch("verisight.cli.VeriSight", side_effect=KeyboardInterrupt):
        assert main(["profile", str(source)]) == 130
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "interrupted" in captured.err


@pytest.mark.parametrize(
    "operations",
    [[], (), ("value",), (ClaimOperation.VALUE, "difference")],
    ids=["mutable-list", "empty", "raw-string", "mixed-types"],
)
def test_output_contract_requires_immutable_typed_operations(
    operations: object,
) -> None:
    with pytest.raises(ValueError, match="nonempty tuple of ClaimOperation"):
        ClaimOutputContract(cast(tuple[ClaimOperation, ...], operations))


@pytest.mark.parametrize(
    ("mode", "violations"),
    [
        ("met", set()),
        ("extra-claims", {"claim_count_mismatch", "claim_operations_mismatch"}),
        ("wrong-operation", {"claim_operations_mismatch"}),
        ("contradicted", {"claims_not_supported"}),
        ("unsupported-reference", {"claims_not_supported"}),
        ("unlinked-number", {"unlinked_numeric_tokens"}),
        ("unparsed-digits", {"unparsed_digits"}),
        ("incomplete", {"incomplete_workflow"}),
        ("no-claims", {"claim_count_mismatch", "claim_operations_mismatch"}),
    ],
    ids=[
        "met",
        "extra-claims",
        "wrong-operation",
        "contradicted",
        "unsupported-reference",
        "unlinked-number",
        "unparsed-digits",
        "incomplete",
        "no-claims",
    ],
)
def test_output_assessment_preserves_results_and_limits_its_verdict(
    source: Path, mode: str, violations: set[str]
) -> None:
    app = VeriSight(
        settings=Settings(gemini_api_key=None, allow_llm_data_disclosure=False)
    )
    before = EvidenceReference(observation_index=0, row_index=0, column="before")
    after = EvidenceReference(observation_index=0, row_index=0, column="after")
    difference = NumericalClaim(
        operation=ClaimOperation.DIFFERENCE,
        expected=20,
        left=after,
        right=before,
    )
    components = (
        NumericalClaim(operation=ClaimOperation.VALUE, expected=10, left=before),
        NumericalClaim(operation=ClaimOperation.VALUE, expected=30, left=after),
    )
    claims: tuple[NumericalClaim, ...] = (difference,)
    conclusion = "The difference is 20."
    if mode == "extra-claims":
        claims = (*components, difference)
        conclusion = "Before 10; after 30; difference 20."
    elif mode == "wrong-operation":
        claims = (components[1],)
        conclusion = "The value is 30."
    elif mode == "contradicted":
        claims = (replace(difference, expected=21),)
        conclusion = "The difference is 21."
    elif mode == "unsupported-reference":
        claims = (replace(difference, left=replace(after, row_index=99)),)
    elif mode == "unlinked-number":
        conclusion = "The difference is 20, with an extra assertion of 99."
    elif mode == "unparsed-digits":
        conclusion = "The difference is 20 for cohort ２０２６."
    elif mode == "no-claims":
        claims = ()
        conclusion = "No final answer."
    result = InvestigationResult(
        question="Return only the difference as one DIFFERENCE claim.",
        conclusion=conclusion,
        analysis=app.analyze(source),
        observations=(
            QueryObservation(
                question="Measure components",
                sql="SELECT 10 AS before, 30 AS after",
                result=QueryResult(columns=("before", "after"), rows=((10, 30),)),
            ),
        ),
        generated_claims=claims,
        status=(
            InvestigationStatus.INCOMPLETE
            if mode == "incomplete"
            else InvestigationStatus.COMPLETE
        ),
    )
    contract = ClaimOutputContract((ClaimOperation.DIFFERENCE,))
    original = to_jsonable(result)
    assessment = result.assess_output(contract)
    assert set(assessment.violations) == violations
    assert assessment.accepted is (not violations)
    assert not assessment.task_semantics_verified
    assert assessment.actual_operations == tuple(item.operation for item in claims)
    assert to_jsonable(result) == original
    assert result.generated_claims is claims
    exported = json.loads(json.dumps(to_jsonable(assessment), allow_nan=False))
    assert exported["accepted"] is (not violations)
    assert exported["scope"] == "claim_shape_and_numeric_evidence_only"
    assert exported["task_semantics_verified"] is False
    with pytest.raises(FrozenInstanceError):
        contract.operations = (ClaimOperation.VALUE,)  # type: ignore[misc]
    if mode == "extra-claims":
        # A different exact contract can accept the unchanged three claims.
        reordered = ClaimOutputContract(
            (ClaimOperation.DIFFERENCE, ClaimOperation.VALUE, ClaimOperation.VALUE)
        )
        assert result.assess_output(reordered).accepted


def test_cli_previews_output_contract_without_generation(
    source: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with patch(
        "verisight.execution.gemini.GeminiTextGenerationClient.generate",
        side_effect=AssertionError("Network forbidden"),
    ) as generate:
        assert (
            main(
                [
                    "investigate",
                    str(source),
                    "--question",
                    "Compare",
                    "--preview",
                    "--require-claim",
                    "difference",
                    "--require-claim",
                    "value",
                ]
            )
            == 0
        )
    generate.assert_not_called()
    report = json.loads(capsys.readouterr().out)
    assert report["request"]["claim_output_contract"] == {
        "operations": ["difference", "value"]
    }


@pytest.mark.parametrize(
    ("mode", "required", "expected_code"),
    [
        ("supported", ["value"], 0),
        ("supported", ["difference"], 1),
        ("supported", ["value", "value"], 1),
        ("contradicted", ["value"], 1),
        ("incomplete", ["value"], 1),
        ("empty", ["value"], 1),
    ],
    ids=[
        "accepted",
        "wrong-operation",
        "wrong-count",
        "contradicted",
        "incomplete",
        "empty",
    ],
)
def test_cli_enforces_selected_output_contract_with_bounded_shape_repair(
    source: Path,
    population: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    mode: str,
    required: list[str],
    expected_code: int,
) -> None:
    output = tmp_path / "contract.json"
    arguments = [
        "investigate",
        str(source),
        "--question",
        "Sum active amounts",
        "--population",
        str(population),
        "--allow-llm-data-disclosure",
        "--output",
        str(output),
    ]
    for operation in required:
        arguments.extend(["--require-claim", operation])
    generation_responses = responses(mode)
    shape_mismatch = required != ["value"]
    if shape_mismatch:
        generation_responses.append(generation_responses[-1])
    if mode == "empty":
        generation_responses[-1] = json.dumps(
            {
                "conclusion": "Insufficient evidence for the requested metric.",
                "claims": [],
            }
        )
    with patch(
        "verisight.execution.gemini.GeminiTextGenerationClient.generate",
        side_effect=generation_responses,
    ) as generate:
        assert main(arguments) == expected_code
    assert generate.call_count == (
        3 if mode == "incomplete" else 4 + int(shape_mismatch)
    )
    if mode != "incomplete":
        assert (
            "CALLER-SELECTED CLAIM OUTPUT CONTRACT"
            in generate.call_args_list[3].args[0]
        )
    if shape_mismatch:
        assert (
            '"validation_error": "claim_output_contract_mismatch"'
            in generate.call_args.args[0]
        )
    report = json.loads(capsys.readouterr().out)
    assert report["request"]["claim_output_contract"]["operations"] == required
    assert report["claim_output_assessment"]["accepted"] is (expected_code == 0)
    assert report["claim_output_assessment"]["task_semantics_verified"] is False
    assert report["workflow_status"] == (
        "incomplete" if mode == "incomplete" or shape_mismatch else "complete"
    )
    assert report["investigation"]["observations"][0]["result"]["rows"] == [[30]]
    assert json.loads(output.read_text(encoding="utf-8")) == report


def test_cli_rejects_unknown_claim_operations_before_work(source: Path) -> None:
    with patch("verisight.cli.VeriSight") as app, pytest.raises(SystemExit) as caught:
        main(
            [
                "investigate",
                str(source),
                "--question",
                "Sum",
                "--preview",
                "--require-claim",
                "ratio",
            ]
        )
    assert caught.value.code == 2
    app.assert_not_called()


@pytest.mark.parametrize("recover", [False, True])
def test_cli_repairs_extra_claims_using_the_selected_difference_contract(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], recover: bool
) -> None:
    source = tmp_path / "measurements.csv"
    source.write_text(
        "period,state,amount\nbefore,accepted,40\nbefore,accepted,60\n"
        "after,accepted,90\nafter,accepted,60\nafter,rejected,999\n"
        "other,accepted,700\n",
        encoding="utf-8",
    )
    before = {"observation_index": 0, "row_index": 0, "column": "total"}
    after = {"observation_index": 1, "row_index": 0, "column": "total"}
    difference = {
        "operation": "difference",
        "expected": "50",
        "left": after,
        "right": before,
    }
    rejected = json.dumps(
        {
            "conclusion": (
                "Private rejected output: before 100, after 150, difference 50."
            ),
            "claims": [
                {
                    "operation": "value",
                    "expected": "100",
                    "left": before,
                    "right": None,
                },
                {"operation": "value", "expected": "150", "left": after, "right": None},
                difference,
            ],
        }
    )
    repaired = json.dumps(
        {"conclusion": "The difference is 50.", "claims": [difference]}
    )
    generation_responses = [
        json.dumps(
            {
                "action": "investigate",
                "reasoning": "Measure",
                "question": "Measure before",
            }
        ),
        (
            "SELECT SUM(amount) AS total FROM measurements "
            "WHERE state = 'accepted' AND period = 'before'"
        ),
        json.dumps(
            {
                "action": "investigate",
                "reasoning": "Compare",
                "question": "Measure after",
            }
        ),
        (
            "SELECT SUM(amount) AS total FROM measurements "
            "WHERE state = 'accepted' AND period = 'after'"
        ),
        json.dumps({"action": "finish", "reasoning": "Done", "question": None}),
        rejected,
        repaired if recover else rejected,
    ]
    question = (
        "Measure before then after in separate queries; report only their difference."
    )
    with patch(
        "verisight.execution.gemini.GeminiTextGenerationClient.generate",
        side_effect=generation_responses,
    ) as generate:
        code = main(
            [
                "investigate",
                str(source),
                "--question",
                question,
                "--max-steps",
                "2",
                "--require-claim",
                "difference",
                "--allow-llm-data-disclosure",
            ]
        )
    report = json.loads(capsys.readouterr().out)
    investigation = report["investigation"]
    assert generate.call_count == 7
    assert [item["result"]["rows"] for item in investigation["observations"]] == [
        [[100]],
        [[150]],
    ]
    assert [item["question"] for item in investigation["observations"]] == [
        "Measure before",
        "Measure after",
    ]
    assert report["request"]["question"] == question
    assert report["claim_output_assessment"]["accepted"] is recover
    assert report["claim_output_assessment"]["task_semantics_verified"] is False
    assert code == (0 if recover else 1)
    repair_prompt = generate.call_args.args[0]
    assert '"validation_error": "claim_output_contract_mismatch"' in repair_prompt
    assert "Private rejected output" not in repair_prompt
    assert "CALLER-SELECTED CLAIM OUTPUT CONTRACT" in repair_prompt
    if recover:
        assert report["workflow_status"] == "complete"
        claims = investigation["verified_claims"]
        assert len(claims) == 1
        assert claims[0]["claim"]["operation"] == "difference"
        assert claims[0]["claim"]["left"] == after
        assert claims[0]["claim"]["right"] == before
        assert claims[0]["verification"]["actual"] == "50"
        assert claims[0]["verification"]["status"] == "supported"
        assert investigation["synthesis_failure"] is None
    else:
        assert report["workflow_status"] == "incomplete"
        assert investigation["verified_claims"] == []
        assert investigation["synthesis_failure"]["kind"] == "synthesis_error"
        assert investigation["investigation_failure"] is None
