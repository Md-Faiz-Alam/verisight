"""Record model responses once, then replay them offline in CI.

A replay file holds a question, its data files, every model response in call
order with a SHA-256 hash of the prompt it answered, and the outcome. Replaying
runs the real pipeline (planning, SQL, verification, the audit, the second
query and the trust level) with the recorded responses in place of Gemini, so a
change anywhere after the model shows up as a different outcome. A prompt whose
hash no longer matches is reported as stale: the recording answered a prompt
that has changed since, and should be recorded again.

Usage, from the repository root:

    python -m scripts.replay check tests/replays
    python -m scripts.replay record --data-dir evaluation/benchmark/data \\
        --file visits.json --question "How many visits were to Cardiology?" \\
        --out tests/replays/cardiology.json --allow-llm-data-disclosure

Recording calls Gemini with the key in VERISIGHT_GEMINI_API_KEY and sends the
schema, profile, question and query results to it.
"""

import argparse
import hashlib
import json
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch

from pydantic import SecretStr

from verisight import VeriSight
from verisight.config import Settings
from verisight.execution.claim_verification import ClaimOperation
from verisight.execution.gemini import GeminiTextGenerationClient
from verisight.execution.investigation_result import (
    ClaimOutputContract,
    InvestigationResult,
)

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = {
    "number": ClaimOutputContract((ClaimOperation.VALUE,)),
    "difference": ClaimOutputContract((ClaimOperation.DIFFERENCE,)),
}
# Answers one model call: given the client and its prompt, return the text.
Responder = Callable[[GeminiTextGenerationClient, str], str]


class ReplayError(RuntimeError):
    """The pipeline asked for a response the recording does not hold."""


@dataclass(frozen=True)
class Call:
    stage: str
    prompt_sha256: str
    response: str


@dataclass(frozen=True)
class ReplayReport:
    outcome: dict[str, Any]
    expected: dict[str, Any]
    # Calls whose prompt changed since the recording.
    stale: tuple[int, ...] = ()
    source: str = "recorded"

    @property
    def matches(self) -> bool:
        return self.outcome == self.expected


@dataclass
class Case:
    question: str
    data_dir: str
    files: list[str]
    answer_type: str = "number"
    source: str = "recorded"
    model: str = ""
    calls: list[Call] = field(default_factory=list)
    expected: dict[str, Any] = field(default_factory=dict)


def prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


@contextmanager
def _intercepted(responder: Responder, calls: list[Call]) -> Iterator[None]:
    """Route every Gemini call through ``responder`` and keep a record of it."""

    def generate(client: GeminiTextGenerationClient, prompt: str) -> str:
        response = responder(client, prompt)
        calls.append(Call(client._stage, prompt_hash(prompt), response))
        return response

    with patch.object(GeminiTextGenerationClient, "generate", generate):
        yield


def outcome(result: InvestigationResult) -> dict[str, Any]:
    """The parts of a result a replay compares; prose and timings vary."""
    return {
        "status": result.status.value,
        "trust_level": None if result.trust is None else result.trust.level.value,
        "claims": [
            {
                "operation": item.claim.operation.value,
                "expected": str(item.claim.expected),
                "verification": item.verification.status.value,
            }
            for item in result.verified_claims
        ],
        "declined": None if result.declined is None else result.declined.action.value,
        "cross_check": None
        if result.cross_check is None
        else result.cross_check.status.value,
    }


def investigate(
    case: Case, responder: Responder, settings: Settings
) -> tuple[InvestigationResult, list[Call]]:
    """Answer the case's question the way the website does."""
    calls: list[Call] = []
    paths = [ROOT / case.data_dir / name for name in case.files]
    with _intercepted(responder, calls):
        result = VeriSight(settings=settings).investigate(
            paths,
            case.question,
            max_steps=3,
            claim_output_contract=CONTRACTS.get(case.answer_type),
            cross_check=True,
        )
    return result, calls


def _replay_settings() -> Settings:
    # No request leaves the process: every call is answered from the file.
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        gemini_api_key=SecretStr("replay"),
        allow_llm_data_disclosure=True,
    )


def load(path: Path) -> Case:
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["calls"] = [Call(**call) for call in raw["calls"]]
    return Case(**raw)


def save(case: Case, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(case), indent=2) + "\n", encoding="utf-8")


def replay(path: Path) -> ReplayReport:
    """Run the pipeline on the recorded responses and compare the outcome."""
    case = load(path)
    pending = iter(enumerate(case.calls))
    stale: list[int] = []

    def answer(client: GeminiTextGenerationClient, prompt: str) -> str:
        index, call = next(pending, (-1, None))
        if call is None:
            raise ReplayError(f"{path.name}: the pipeline made more model calls.")
        if call.stage != client._stage:
            raise ReplayError(
                f"{path.name}: call {index} was {call.stage}, now {client._stage}."
            )
        if call.prompt_sha256 != prompt_hash(prompt):
            stale.append(index)
        return call.response

    result, _ = investigate(case, answer, _replay_settings())
    return ReplayReport(outcome(result), case.expected, tuple(stale), case.source)


def record(
    case: Case,
    responder: Responder,
    settings: Settings,
    out: Path,
) -> Case:
    """Answer the case with ``responder`` and save every call and the outcome."""
    result, calls = investigate(case, responder, settings)
    recorded = Case(
        question=case.question,
        data_dir=case.data_dir,
        files=case.files,
        answer_type=case.answer_type,
        source=case.source,
        model=settings.gemini_model,
        calls=calls,
        expected=outcome(result),
    )
    save(recorded, out)
    return recorded


def _check(folder: Path) -> int:
    failures = 0
    for path in sorted(folder.glob("*.json")):
        report = replay(path)
        state = "ok" if report.matches else "CHANGED"
        if report.stale:
            state += f", stale prompts {list(report.stale)}"
        print(f"{path.name}: {state} ({report.source})")
        failures += not report.matches
    return 1 if failures else 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.replay")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="Replay every file in a folder.")
    check.add_argument("folder", type=Path)
    make = commands.add_parser("record", help="Record a live run (calls Gemini).")
    make.add_argument("--data-dir", required=True)
    make.add_argument("--file", action="append", required=True)
    make.add_argument("--question", required=True)
    make.add_argument("--answer-type", choices=["number", "difference", "any"])
    make.add_argument("--out", type=Path, required=True)
    make.add_argument("--allow-llm-data-disclosure", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "check":
        return _check(args.folder)
    if not args.allow_llm_data_disclosure:
        print("Recording sends data to Gemini; add --allow-llm-data-disclosure.")
        return 2
    settings = Settings().model_copy(update={"allow_llm_data_disclosure": True})
    if settings.gemini_key() is None:
        print("Set VERISIGHT_GEMINI_API_KEY to record.")
        return 2
    case = Case(
        question=args.question,
        data_dir=args.data_dir,
        files=args.file,
        answer_type=args.answer_type or "number",
    )
    live = GeminiTextGenerationClient.generate
    recorded = record(case, live, settings, args.out)
    print(f"Recorded {len(recorded.calls)} calls to {args.out}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
