"""Compare plain Gemini SQL with VeriSight on the same frozen questions.

Three setups answer each question once, with the same files, wording and model:

    plain     Gemini writes one SQL query and DuckDB runs it. It uses VeriSight's
              cleaned data and SQL prompt, so it is a strong baseline.
    numbers   VeriSight's investigation with numbers matched to SQL results.
    full      The website's path, with the SQL audit and the second query.

Questions live outside the repository, in <root>/questions.csv, with the files in
<root>/data. Columns: id, files, type, question, expected, tolerance. ``files``
separates several names with a semicolon, ``type`` is number or difference, and
``expected`` is a number, AMBIGUOUS or UNANSWERABLE.

Nothing here prints a question. --freeze records hashes of this file, the questions
and the data, and a run refuses to start if any of them changed. Every attempt is
kept. A run stops after three provider errors in a row and later continues with the
questions it has not answered, so quota problems never cost an attempt.

Usage (PowerShell, from the repository root, venv active):
    python evaluation\\baseline\\run_baseline_eval.py --root <dir> --freeze
    python evaluation\\baseline\\run_baseline_eval.py --root <dir> --run plain numbers
    python evaluation\\baseline\\run_baseline_eval.py --root <dir> --run full
    python evaluation\\baseline\\run_baseline_eval.py --root <dir> --report
"""

import argparse
import csv
import hashlib
import json
import statistics
import subprocess
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from functools import partial
from pathlib import Path
from typing import Any

SETUPS = ("plain", "numbers", "full")
NO_ANSWER_LABELS = ("AMBIGUOUS", "UNANSWERABLE")
COLUMNS = ["id", "files", "type", "question", "expected", "tolerance"]
MAX_PROVIDER_ERRORS_IN_A_ROW = 3
PROMINENT = "prominent"
WARNED = "warned"
NONE = "none"


@dataclass(frozen=True)
class Question:
    question_id: str
    files: tuple[str, ...]
    kind: str
    text: str
    expected: Decimal | None
    label: str
    tolerance: Decimal


@dataclass
class Answer:
    number: Decimal | None = None
    visibility: str = NONE
    provider_error: bool = False
    calls: int = 0
    seconds: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)


Ask = Callable[[Question], Answer]


def _problem(number: int, message: str) -> SystemExit:
    return SystemExit(f"questions.csv row {number}: {message}")


def _parse_row(number: int, row: dict[str, str], data_dir: Path) -> Question:
    files = tuple(name.strip() for name in row["files"].split(";") if name.strip())
    if not row["id"].strip() or not row["question"].strip() or not files:
        raise _problem(number, "id, files and question are all required.")
    missing = [name for name in files if not (data_dir / name).is_file()]
    if missing:
        raise _problem(number, f"file not found in data folder: {missing[0]}")
    kind = row["type"].strip().casefold()
    if kind not in ("number", "difference"):
        raise _problem(number, "type must be number or difference.")
    written = row["expected"].strip()
    if written.upper() in NO_ANSWER_LABELS:
        return Question(
            row["id"].strip(),
            files,
            kind,
            row["question"].strip(),
            None,
            written.upper(),
            Decimal(0),
        )
    try:
        expected = Decimal(written.replace(",", ""))
        tolerance = Decimal(row["tolerance"].strip() or "0")
    except InvalidOperation:
        raise _problem(number, "expected or tolerance is not a number.") from None
    if not expected.is_finite() or not tolerance.is_finite() or tolerance < 0:
        raise _problem(number, "expected or tolerance is not a valid number.")
    return Question(
        row["id"].strip(),
        files,
        kind,
        row["question"].strip(),
        expected,
        "number",
        tolerance,
    )


def load_questions(root: Path) -> list[Question]:
    """Read and check the questions, naming only row numbers in any error."""
    with (root / "questions.csv").open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        absent = [name for name in COLUMNS if name not in (reader.fieldnames or ())]
        if absent:
            raise SystemExit(f"questions.csv is missing columns: {', '.join(absent)}")
        questions = [
            _parse_row(number, row, root / "data")
            for number, row in enumerate(reader, start=2)
        ]
    if len({question.question_id for question in questions}) != len(questions):
        raise SystemExit("questions.csv has a repeated id.")
    return questions


def score(question: Question, answer: Answer) -> str:
    """Name the result of one attempt."""
    if answer.provider_error:
        return "provider_error"
    if question.expected is None:
        if answer.number is None:
            return "correct_refusal"
        return f"unsafe_{answer.visibility}"
    if answer.number is None:
        return "missed"
    right = abs(answer.number - question.expected) <= question.tolerance
    return f"{'correct' if right else 'wrong'}_{answer.visibility}"


def final_cell(rows: Iterable[tuple[Any, ...]]) -> Decimal | None:
    """The last number of a one-row result; several rows hold no single answer."""
    listed = list(rows)
    if len(listed) != 1:
        return None
    for cell in reversed(listed[0]):
        if type(cell) in (int, float, Decimal):
            value = Decimal(str(cell))
            return value if value.is_finite() else None
    return None


def _expected_errors() -> tuple[type[Exception], ...]:
    """Failures of one attempt; anything else is a bug and should stop the run."""
    from verisight.exceptions import VeriSightError
    from verisight.execution.exceptions import (
        InvestigationError,
        QueryExecutionError,
        QueryPlanningError,
    )

    return (
        VeriSightError,
        InvestigationError,
        QueryExecutionError,
        QueryPlanningError,
    )


def is_provider_failure(error: Exception) -> bool:
    from verisight.execution.gemini import GeminiGenerationError
    from verisight.execution.investigation_result import InvestigationFailure

    if isinstance(error, GeminiGenerationError):
        return True
    kind = InvestigationFailure.from_exception("query_execution", error).kind
    return str(kind).startswith("provider")


def _measured(ask: Callable[[], Answer]) -> Answer:
    from verisight.execution.generation_telemetry import capture_generation_calls

    started = time.perf_counter()
    with capture_generation_calls() as calls:
        answer = ask()
    answer.calls = len(calls)
    answer.seconds = round(time.perf_counter() - started, 3)
    return answer


def answer_plain(app: Any, question: Question, data_dir: Path) -> Answer:
    """One Gemini query, run once, with no checks and no second attempt."""
    paths = [data_dir / name for name in question.files]

    def ask() -> Answer:
        try:
            plan = app.plan(paths, question.text)
            result = app.execute(paths, plan.sql)
        except _expected_errors() as error:
            if is_provider_failure(error):
                return Answer(provider_error=True)
            return Answer(details={"error": type(error).__name__})
        number = final_cell(result.rows)
        visibility = PROMINENT if number is not None else NONE
        return Answer(number, visibility, details={"sql": [plan.sql]})

    return _measured(ask)


def answer_numbers(app: Any, question: Question, data_dir: Path) -> Answer:
    """VeriSight's investigation, with numbers matched to SQL cells."""
    from verisight.execution.claim_verification import (
        ClaimOperation,
        VerificationStatus,
    )
    from verisight.execution.investigation_result import (
        ClaimOutputContract,
        InvestigationStatus,
    )

    operation = (
        ClaimOperation.VALUE if question.kind == "number" else ClaimOperation.DIFFERENCE
    )
    contract = ClaimOutputContract((operation,))

    def ask() -> Answer:
        try:
            result = app.investigate(
                [data_dir / name for name in question.files],
                question.text,
                max_steps=3,
                claim_output_contract=contract,
            )
        except _expected_errors() as error:
            if is_provider_failure(error):
                return Answer(provider_error=True)
            return Answer(details={"error": type(error).__name__})
        details = {"sql": [item.sql for item in result.observations]}
        for failure in (result.investigation_failure, result.synthesis_failure):
            if failure is not None and str(failure.kind.value).startswith("provider"):
                return Answer(provider_error=True, details=details)
        accepted = result.assess_output(contract).accepted
        if result.status is not InvestigationStatus.COMPLETE or not accepted:
            return Answer(details=details)
        check = result.verified_claims[0].verification
        if check.status is not VerificationStatus.SUPPORTED or check.actual is None:
            return Answer(details=details)
        return Answer(Decimal(str(check.actual)), PROMINENT, details=details)

    return _measured(ask)


def read_website_answer(
    status: int, body: dict[str, Any], question: Question
) -> Answer:
    """Turn a website reply into what a visitor would actually see."""
    calls = len(body.get("model_calls") or [])
    if status != 200:
        busy = body.get("code") in ("provider_unavailable", "busy", "rate_limited")
        return Answer(provider_error=busy, calls=calls, details={"status": status})
    cross = body.get("cross_check") or {}
    trust = body.get("trust") or {}
    details = {
        "sql": [step.get("sql") for step in body.get("steps", [])],
        "trust_level": trust.get("level"),
        "second_query": cross.get("status"),
        "second_value": cross.get("independent_value"),
        "repeated_query": cross.get("identical_sql"),
        "failed_checks": [
            check["name"]
            for check in trust.get("checks", [])
            if check["status"] == "failed"
        ],
        "web_outcome": body.get("outcome"),
    }
    failure = body.get("failure") or {}
    if str(failure.get("kind", "")).startswith("provider"):
        return Answer(provider_error=True, calls=calls, details=details)
    operation = "value" if question.kind == "number" else "difference"
    claims = [
        item
        for item in body.get("claims", [])
        if item["claim"]["operation"] == operation
    ]
    assessment = body.get("assessment")
    verified = body.get("outcome") == "verified"
    accepted = verified or (isinstance(assessment, dict) and assessment.get("accepted"))
    if body.get("status") != "complete" or len(claims) != 1 or not accepted:
        return Answer(calls=calls, details=details)
    check = claims[0]["verification"]
    if check["status"] != "supported" or check["actual"] is None:
        return Answer(calls=calls, details=details)
    visibility = PROMINENT if verified else WARNED
    return Answer(
        Decimal(str(check["actual"])), visibility, calls=calls, details=details
    )


def answer_on_website(
    client: Any, question: Question, data_dir: Path, key: str
) -> Answer:
    """Upload, ask and delete, exactly as a visitor does."""
    files = [
        ("files", (name, (data_dir / name).read_bytes())) for name in question.files
    ]
    upload = client.post("/api/datasets", files=files)
    if upload.status_code != 201:
        return Answer(details={"upload_status": upload.status_code})
    dataset_id = upload.json()["dataset_id"]
    started = time.perf_counter()
    try:
        reply = client.post(
            f"/api/datasets/{dataset_id}/ask",
            json={
                "question": question.text,
                "answer_type": question.kind,
                "consent": True,
                "api_key": key,
            },
        )
    finally:
        client.delete(f"/api/datasets/{dataset_id}")
    answer = read_website_answer(reply.status_code, reply.json(), question)
    answer.seconds = round(time.perf_counter() - started, 3)
    return answer


def run_setup(
    questions: list[Question],
    ask: Ask,
    results: Path,
    *,
    pause: float = 0.0,
) -> dict[str, int]:
    """Ask each question not yet answered, keeping every attempt already made."""
    finished: set[str] = set()
    if results.exists():
        for line in results.read_text("utf-8").splitlines():
            record = json.loads(line)
            if record["outcome"] != "provider_error":
                finished.add(record["id"])
    results.parent.mkdir(parents=True, exist_ok=True)
    errors_in_a_row = 0
    counts: Counter[str] = Counter()
    with results.open("a", encoding="utf-8", newline="\n") as log:
        for question in questions:
            if question.question_id in finished:
                continue
            answer = ask(question)
            outcome = score(question, answer)
            log.write(
                json.dumps(
                    {
                        "id": question.question_id,
                        "outcome": outcome,
                        "time_utc": datetime.now(UTC).isoformat(),
                        **asdict(answer),
                    },
                    default=str,
                )
                + "\n"
            )
            log.flush()
            counts[outcome] += 1
            print(f"{question.question_id}: {outcome}", flush=True)
            errors_in_a_row = errors_in_a_row + 1 if answer.provider_error else 0
            if errors_in_a_row >= MAX_PROVIDER_ERRORS_IN_A_ROW:
                print("Stopped after repeated provider errors. Run again later.")
                break
            time.sleep(pause)
    return dict(counts)


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def summarize(
    questions: list[Question], records: list[dict[str, Any]]
) -> dict[str, Any]:
    """Report one setup: every number the targets in the specification need."""
    latest = {record["id"]: record for record in records}
    answerable = {q.question_id for q in questions if q.expected is not None}
    counts = Counter(record["outcome"] for record in latest.values())
    prominent_right = counts["correct_prominent"]
    warned_right = counts["correct_warned"]
    right = prominent_right + warned_right
    wrong = counts["wrong_prominent"] + counts["wrong_warned"]
    errors = {i for i, r in latest.items() if r["outcome"] == "provider_error"}
    delivered_over = len(answerable - errors)
    shown = right + wrong + counts["unsafe_prominent"] + counts["unsafe_warned"]
    seconds = [r["seconds"] for r in latest.values() if r["seconds"]]
    return {
        "attempted": len(latest),
        "not_attempted": len(questions) - len(latest),
        "outcomes": dict(sorted(counts.items())),
        "correct_delivered_share": _share(right, delivered_over),
        "correct_among_shown_share": _share(right, shown),
        "wrong_shown_prominently": counts["wrong_prominent"]
        + counts["unsafe_prominent"],
        "wrong_visible_anywhere": wrong
        + counts["unsafe_prominent"]
        + counts["unsafe_warned"],
        "false_warning_share": _share(warned_right, right),
        "model_calls": sum(r["calls"] for r in latest.values()),
        "median_seconds": statistics.median(seconds) if seconds else None,
    }


def second_query_value(
    questions: list[Question], records: list[dict[str, Any]]
) -> dict[str, int]:
    """What the second query added, against the independently written answers."""
    expected = {q.question_id: q.expected for q in questions}
    tally: Counter[str] = Counter()
    for record in records:
        details = record.get("details") or {}
        status = details.get("second_query")
        if status is None or record["number"] is None:
            continue
        target = expected.get(record["id"])
        if target is None:
            continue
        right = record["outcome"].startswith("correct")
        if status == "disagreed":
            tally[
                "caught_a_wrong_answer" if not right else "doubted_a_right_answer"
            ] += 1
        elif status == "agreed" and details.get("repeated_query") is not True:
            tally["confirmed_right" if right else "shared_the_mistake"] += 1
        else:
            tally["added_no_evidence"] += 1
    return dict(tally)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(*args: str) -> str:
    done = subprocess.run(["git", *args], capture_output=True, text=True, check=False)
    return done.stdout.strip()


def snapshot(root: Path) -> dict[str, Any]:
    data = root / "data"
    return {
        "runner_sha256": _sha256(Path(__file__).resolve()),
        "revision": _git("rev-parse", "HEAD"),
        "questions_sha256": _sha256(root / "questions.csv"),
        "data_sha256": {
            item.name: _sha256(item)
            for item in sorted(data.iterdir())
            if item.is_file()
        },
    }


def freeze(root: Path) -> None:
    if _git("status", "--porcelain", "--untracked-files=no"):
        raise SystemExit("Commit every tracked change before freezing.")
    questions = load_questions(root)
    target = root / "freeze.json"
    with target.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(
            {
                "frozen_utc": datetime.now(UTC).isoformat(),
                **snapshot(root),
                "questions": len(questions),
                "kinds": dict(Counter(q.label for q in questions)),
            },
            handle,
            indent=2,
        )
    print(f"Frozen {len(questions)} questions. No model calls were made.")


def check_frozen(root: Path) -> None:
    frozen = json.loads((root / "freeze.json").read_text("utf-8"))
    current = snapshot(root)
    changed = [name for name, value in current.items() if frozen[name] != value]
    if changed or _git("status", "--porcelain", "--untracked-files=no"):
        raise SystemExit(f"Something changed since the freeze: {changed or 'code'}.")


def _web_settings() -> dict[str, Any]:
    """The limits the website applies, so every setup gets the same budget."""
    from verisight.web.config import WebSettings

    web = WebSettings()
    return {
        "allow_llm_data_disclosure": True,
        "max_investigation_seconds": web.max_investigation_seconds,
        "gemini_max_retries": web.provider_retries,
        "gemini_retry_base_delay_seconds": web.provider_retry_delay_seconds,
        "max_query_result_rows": web.max_result_rows,
    }


def _model_answer(setup: str, engine: Any, data: Path, question: Question) -> Answer:
    answer = answer_plain if setup == "plain" else answer_numbers
    return answer(engine, question, data)


def run(root: Path, setups: list[str], pause: float) -> None:
    from fastapi.testclient import TestClient

    from verisight import VeriSight
    from verisight.config import Settings
    from verisight.web import create_app
    from verisight.web.config import WebSettings

    check_frozen(root)
    questions = load_questions(root)
    data = root / "data"
    settings = Settings(**_web_settings())
    key = (settings.gemini_api_key or "").strip()
    if not key:
        raise SystemExit("No Gemini key configured.")
    for setup in setups:
        results = root / "runs" / f"{setup}.jsonl"
        if setup == "full":
            app = create_app(
                settings=Settings(gemini_api_key=None),
                web=WebSettings(questions_per_hour=10_000, uploads_per_hour=10_000),
            )
            with TestClient(app) as client:
                counts = run_setup(
                    questions,
                    lambda q: answer_on_website(client, q, data, key),
                    results,
                    pause=pause,
                )
        else:
            counts = run_setup(
                questions,
                partial(_model_answer, setup, VeriSight(settings=settings), data),
                results,
                pause=pause,
            )
        print(setup, json.dumps(counts))


def report(root: Path) -> None:
    questions = load_questions(root)
    by_id = {question.question_id: question for question in questions}
    summary: dict[str, Any] = {}
    review: list[dict[str, Any]] = []
    for setup in SETUPS:
        path = root / "runs" / f"{setup}.jsonl"
        if not path.exists():
            continue
        records = [json.loads(line) for line in path.read_text("utf-8").splitlines()]
        summary[setup] = summarize(questions, records)
        if setup == "full":
            summary[setup]["second_query"] = second_query_value(questions, records)
        review.extend(
            {
                "setup": setup,
                "id": record["id"],
                "outcome": record["outcome"],
                "number": record["number"],
                "expected": by_id[record["id"]].expected or by_id[record["id"]].label,
                "question": by_id[record["id"]].text,
                "sql": " | ".join(record["details"].get("sql") or []),
            }
            for record in records
            if not record["outcome"].startswith(("correct", "provider"))
        )
    (root / "report.json").write_text(json.dumps(summary, indent=2), "utf-8")
    with (root / "review.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "setup",
                "id",
                "outcome",
                "number",
                "expected",
                "question",
                "sql",
            ],
        )
        writer.writeheader()
        writer.writerows(review)
    print(json.dumps(summary, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--freeze", action="store_true")
    parser.add_argument("--check", action="store_true", help="Validate the questions.")
    parser.add_argument("--run", nargs="+", choices=SETUPS)
    parser.add_argument("--report", action="store_true")
    parser.add_argument("--pause-seconds", type=float, default=20.0)
    args = parser.parse_args()
    if args.check:
        counts = Counter(q.label for q in load_questions(args.root))
        print(f"{sum(counts.values())} questions look valid: {dict(counts)}")
    if args.freeze:
        freeze(args.root)
    if args.run:
        run(args.root, args.run, args.pause_seconds)
    if args.report:
        report(args.root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
