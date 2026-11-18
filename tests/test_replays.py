"""Replay recorded model responses through the real pipeline, offline."""

import json
import warnings
from dataclasses import replace
from pathlib import Path

import pytest
from scripts import replay

from verisight.execution.gemini import GeminiTextGenerationClient

REPLAYS = Path(__file__).resolve().parent / "replays"
FILES = sorted(REPLAYS.glob("*.json"))


@pytest.mark.parametrize("path", FILES, ids=[path.stem for path in FILES])
def test_each_recording_still_reaches_its_outcome(path: Path) -> None:
    report = replay.replay(path)

    if report.stale:
        # The answer still holds, but it answered a prompt that changed since.
        warnings.warn(
            f"{path.name}: prompts {list(report.stale)} changed; record it again.",
            stacklevel=1,
        )
    assert report.outcome == report.expected


def test_the_recordings_cover_each_path() -> None:
    levels = {replay.load(path).expected["trust_level"] for path in FILES}

    assert {"verified", "number_matched", "not_verified"} <= levels


def _copy(tmp_path: Path, name: str) -> Path:
    target = tmp_path / name
    target.write_text((REPLAYS / name).read_text(encoding="utf-8"), encoding="utf-8")
    return target


def _edit(path: Path, change: object) -> None:
    raw = json.loads(path.read_text(encoding="utf-8"))
    change(raw)  # type: ignore[operator]
    path.write_text(json.dumps(raw), encoding="utf-8")


def test_a_changed_prompt_is_reported_as_stale(tmp_path: Path) -> None:
    path = _copy(tmp_path, "cardiology_reworded_repeat.json")
    _edit(path, lambda raw: raw["calls"][1].update(prompt_sha256="0" * 64))

    report = replay.replay(path)

    assert report.stale == (1,)
    assert report.matches


def test_a_recording_with_too_few_calls_fails_clearly(tmp_path: Path) -> None:
    path = _copy(tmp_path, "cardiology_reworded_repeat.json")
    _edit(path, lambda raw: raw["calls"].pop())

    with pytest.raises(replay.ReplayError, match="more model calls"):
        replay.replay(path)


def test_calls_in_another_order_fail_clearly(tmp_path: Path) -> None:
    path = _copy(tmp_path, "cardiology_reworded_repeat.json")
    _edit(path, lambda raw: raw["calls"][0].update(stage="structured_synthesis"))

    with pytest.raises(replay.ReplayError, match="call 0 was structured_synthesis"):
        replay.replay(path)


def test_an_outcome_without_a_trust_level_is_recorded_as_none(tmp_path: Path) -> None:
    case = replay.load(REPLAYS / "cardiology_reworded_repeat.json")
    responses = iter(call.response for call in case.calls)
    result, calls = replay.investigate(
        case, lambda client, prompt: next(responses), replay._replay_settings()
    )

    assert len(calls) == len(case.calls)
    assert replay.outcome(replace(result, trust=None))["trust_level"] is None


def test_check_reports_each_file_and_fails_on_a_change(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _copy(tmp_path, "patient_age_not_in_data.json")
    assert replay.main(["check", str(tmp_path)]) == 0
    assert "patient_age_not_in_data.json: ok (hand-written)" in capsys.readouterr().out

    changed = _copy(tmp_path, "cardiology_reworded_repeat.json")
    _edit(
        changed,
        lambda raw: (
            raw["expected"].update(trust_level="verified"),
            raw["calls"][0].update(prompt_sha256="0" * 64),
        ),
    )
    assert replay.main(["check", str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "cardiology_reworded_repeat.json: CHANGED, stale prompts [0]" in out


def _record_args(out: Path, *extra: str) -> list[str]:
    return [
        "record",
        "--data-dir",
        "evaluation/benchmark/data",
        "--file",
        "visits.json",
        "--question",
        "What is the average age of the patients?",
        "--out",
        str(out),
        *extra,
    ]


@pytest.fixture
def no_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Away from the project's .env, so no real key is ever read.
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VERISIGHT_GEMINI_API_KEY", raising=False)


@pytest.mark.usefixtures("no_key")
def test_recording_needs_consent_and_a_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "new.json"

    assert replay.main(_record_args(out)) == 2
    assert "--allow-llm-data-disclosure" in capsys.readouterr().out
    assert replay.main(_record_args(out, "--allow-llm-data-disclosure")) == 2
    assert "VERISIGHT_GEMINI_API_KEY" in capsys.readouterr().out
    assert not out.exists()


@pytest.mark.usefixtures("no_key")
def test_recording_saves_every_call_and_the_outcome(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("VERISIGHT_GEMINI_API_KEY", "test-key")
    declined = json.dumps(
        {"action": "not_in_data", "reasoning": "No age column.", "question": None}
    )
    # Stands in for Gemini, so the recording is made without a network call.
    monkeypatch.setattr(
        GeminiTextGenerationClient, "generate", lambda client, prompt: declined
    )
    out = tmp_path / "new.json"

    code = replay.main(
        _record_args(out, "--allow-llm-data-disclosure", "--answer-type", "any")
    )

    assert code == 0
    assert "Recorded 1 calls" in capsys.readouterr().out
    case = replay.load(out)
    assert case.source == "recorded"
    assert [call.stage for call in case.calls] == ["investigator"]
    assert case.expected["declined"] == "not_in_data"
