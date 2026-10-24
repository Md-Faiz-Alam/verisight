"""CLI boundary tests using real synthetic ingestion/SQL and offline providers."""

import json
from pathlib import Path
from typing import IO, Any
from unittest.mock import patch

import pytest

from verisight.cli import main
from verisight.execution.gemini import GeminiTransientError


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
