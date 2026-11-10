"""The website under load, expiry, restarts and provider failures, with no model."""

import json
import os
import shutil
import tempfile
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from verisight import VeriSight
from verisight.config import Settings
from verisight.execution.deadline import InvestigationDeadlineExceeded
from verisight.execution.gemini import GeminiGenerationError, GeminiTransientError
from verisight.execution.generative import GenerativeQueryPlanner
from verisight.execution.generative_investigator import GenerativeInvestigator
from verisight.execution.structured_synthesis import StructuredInvestigationSynthesizer
from verisight.web import create_app
from verisight.web.config import WebSettings
from verisight.web.store import DatasetStore, remove_leftover_directories

CSV = b"region,amount\nEast,100\nEast,200\nWest,50\n"
QUESTION = "How much came in altogether?"
FIRST = "SELECT SUM(amount) AS total FROM data"
SECOND = (
    "SELECT SUM(CASE WHEN amount > 0 THEN amount ELSE 0 END) "
    "AS cross_check_answer FROM data"
)
SECRET = "provider-secret-text"
GOOD_SYNTHESIS = json.dumps(
    {
        "conclusion": "The total is 350.",
        "claims": [
            {
                "operation": "value",
                "expected": "350",
                "left": {"observation_index": 0, "row_index": 0, "column": "total"},
                "right": None,
            }
        ],
    }
)
Reply = str | Exception


def _decision(question: str | None) -> str:
    action = "finish" if question is None else "investigate"
    return json.dumps({"action": action, "reasoning": "r", "question": question})


DECISIONS: list[Reply] = [_decision("Add up the amounts"), _decision(None)]


class _Script:
    def __init__(
        self, items: list[Reply], before: Callable[[], None] = lambda: None
    ) -> None:
        self.items = list(items)
        self.before = before

    def generate(self, prompt: str) -> str:
        self.before()
        item = self.items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _engine(
    settings: Settings,
    *,
    decide: list[Reply] | None = None,
    plan: list[Reply] | None = None,
    write: list[Reply] | None = None,
    before: Callable[[], None] = lambda: None,
) -> VeriSight:
    return VeriSight(
        settings=settings.model_copy(update={"gemini_cross_check_model": None}),
        planner=GenerativeQueryPlanner(_Script(plan or [FIRST, SECOND])),
        investigator=GenerativeInvestigator(
            _Script(DECISIONS if decide is None else decide, before)
        ),
        synthesizer=StructuredInvestigationSynthesizer(
            _Script(write or [GOOD_SYNTHESIS] * 2)
        ),
    )


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _settings() -> Settings:
    return Settings(gemini_api_key=None, allow_llm_data_disclosure=False)


def _upload(client: TestClient, name: str = "data.csv", body: bytes = CSV) -> str:
    response = client.post("/api/datasets", files=[("files", (name, body))])
    assert response.status_code == 201
    return str(response.json()["dataset_id"])


def _ask(client: TestClient, dataset_id: str) -> tuple[int, dict[str, Any]]:
    response = client.post(
        f"/api/datasets/{dataset_id}/ask",
        json={"question": QUESTION, "consent": True, "api_key": "k"},
    )
    return response.status_code, response.json()


@pytest.fixture
def temporary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep every upload folder of a test inside the test's own directory."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    return tmp_path


def _folders(root: Path) -> list[Path]:
    return sorted(root.glob("verisight-*"))


class _Gate:
    """Hold model calls until released, and count how many are waiting."""

    def __init__(self) -> None:
        self.waiting = threading.Semaphore(0)
        self.opened = threading.Event()

    def __call__(self) -> None:
        self.waiting.release()
        assert self.opened.wait(timeout=30)


def _held_client(
    gate: _Gate,
    store: DatasetStore | None = None,
    clock: Callable[[], float] | None = None,
    **web: Any,
) -> TestClient:
    released = gate.opened.is_set

    def factory(settings: Settings) -> VeriSight:
        hold = settings.gemini_api_key is not None and not released()
        return _engine(settings, before=gate if hold else lambda: None)

    options: dict[str, Any] = {} if clock is None else {"clock": clock}
    app = create_app(
        settings=_settings(),
        web=WebSettings(**web),
        factory=factory,
        store=store,
        **options,
    )
    return TestClient(app)


def test_simultaneous_uploads_keep_to_the_capacity(temporary: Path) -> None:
    app = create_app(settings=_settings(), web=WebSettings(max_datasets=5))

    with TestClient(app) as client, ThreadPoolExecutor(4) as pool:
        ids = list(pool.map(lambda _: _upload(client), range(12)))

        assert len(set(ids)) == 12
        assert len(_folders(temporary)) == 5

    assert _folders(temporary) == []


def test_only_two_questions_run_at_once_and_slots_come_back(temporary: Path) -> None:
    gate = _Gate()

    with _held_client(gate) as client, ThreadPoolExecutor(2) as pool:
        dataset_id = _upload(client)
        running = [pool.submit(_ask, client, dataset_id) for _ in range(2)]
        for _ in range(2):
            assert gate.waiting.acquire(timeout=30)

        status, error = _ask(client, dataset_id)
        gate.opened.set()
        finished = [item.result(timeout=30) for item in running]
        again, _ = _ask(client, dataset_id)

    assert (status, error["code"]) == (503, "busy")
    assert [item[0] for item in finished] == [200, 200]
    assert again == 200


def test_a_failed_question_gives_its_slot_back(temporary: Path) -> None:
    failing = GeminiTransientError(SECRET)
    app = create_app(
        settings=_settings(),
        web=WebSettings(max_concurrent_questions=1),
        factory=lambda settings: _engine(settings, decide=[failing]),
    )

    with TestClient(app) as client:
        dataset_id = _upload(client)
        first, _ = _ask(client, dataset_id)
        second, _ = _ask(client, dataset_id)

    assert (first, second) == (503, 503)


def test_expiry_during_a_question_lets_it_finish_then_removes_it(
    temporary: Path,
) -> None:
    gate = _Gate()
    clock = Clock()
    store = DatasetStore(ttl_seconds=60, max_datasets=10, clock=clock)

    with _held_client(gate, store=store, clock=clock) as client:
        with ThreadPoolExecutor(1) as pool:
            dataset_id = _upload(client)
            running = pool.submit(_ask, client, dataset_id)
            assert gate.waiting.acquire(timeout=30)

            clock.now += 120
            store.purge_expired()
            removed = _folders(temporary)
            gate.opened.set()
            status, body = running.result(timeout=30)
        later, error = _ask(client, dataset_id)

    assert removed == []
    assert status == 200
    assert body["claims"][0]["verification"]["actual"] in (350, "350")
    assert (later, error["code"]) == (404, "dataset_not_found")


def test_eviction_removes_only_the_oldest_upload(temporary: Path) -> None:
    clock = Clock()
    store = DatasetStore(ttl_seconds=3600, max_datasets=2, clock=clock)
    app = create_app(settings=_settings(), web=WebSettings(), store=store, clock=clock)

    with TestClient(app) as client:
        oldest = _upload(client)
        clock.now += 1
        kept = _upload(client)
        clock.now += 1
        newest = _upload(client)

        assert client.get(f"/api/datasets/{oldest}/nothing").status_code in (404, 405)
        assert store.get(oldest) is None
        assert store.get(kept) is not None
        assert store.get(newest) is not None
        assert len(_folders(temporary)) == 2


def test_a_missing_upload_folder_is_a_clear_error_without_a_number(
    temporary: Path,
) -> None:
    app = create_app(
        settings=_settings(),
        web=WebSettings(),
        factory=_engine,
    )

    with TestClient(app) as client:
        dataset_id = _upload(client)
        folder = _folders(temporary)[0]
        shutil.rmtree(folder)
        status, body = _ask(client, dataset_id)

    assert 400 <= status < 500
    assert "claims" not in body
    assert str(folder) not in json.dumps(body)


def test_a_normal_shutdown_removes_every_upload(temporary: Path) -> None:
    app = create_app(settings=_settings(), web=WebSettings())

    with TestClient(app) as client:
        _upload(client)
        assert len(_folders(temporary)) == 1

    assert _folders(temporary) == []


def _old_folder(root: Path, name: str, age: float) -> Path:
    folder = root / name
    folder.mkdir()
    (folder / "data.csv").write_bytes(CSV)
    stamp = 2_000_000_000 - age
    os.utime(folder, (stamp, stamp))
    return folder


def test_a_restart_removes_only_folders_left_by_a_crash(temporary: Path) -> None:
    left_behind = _old_folder(temporary, "verisight-crashed", 7200)
    recent = _old_folder(temporary, "verisight-recent", 10)
    unrelated = _old_folder(temporary, "another-program", 7200)
    file_with_the_name = temporary / "verisight-file"
    file_with_the_name.write_bytes(b"x")
    os.utime(file_with_the_name, (1, 1))

    removed = remove_leftover_directories(3600, clock=lambda: 2_000_000_000)

    assert removed == 1
    assert not left_behind.exists()
    assert recent.exists()
    assert unrelated.exists()
    assert file_with_the_name.exists()


def test_a_folder_that_vanishes_during_cleanup_is_ignored(
    temporary: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _old_folder(temporary, "verisight-gone", 7200)
    real = Path.stat

    def vanishing(self: Path, **options: Any) -> os.stat_result:
        if self.name == "verisight-gone":
            raise FileNotFoundError
        return real(self, **options)

    monkeypatch.setattr(Path, "stat", vanishing)

    assert remove_leftover_directories(3600, clock=lambda: 2_000_000_000) == 0


def test_the_website_cleans_up_when_it_starts(temporary: Path) -> None:
    stale = _old_folder(temporary, "verisight-crashed", 10**10)
    app = create_app(settings=_settings(), web=WebSettings())

    with TestClient(app):
        assert not stale.exists()


Failure = dict[str, Any]
FAILURES: dict[str, Failure] = {
    "provider-down-when-deciding": {"decide": [GeminiTransientError(SECRET)]},
    "provider-error-when-planning": {"plan": [GeminiGenerationError(SECRET)]},
    "provider-down-when-writing": {"write": [GeminiTransientError(SECRET)] * 2},
    "provider-error-when-writing": {"write": [GeminiGenerationError(SECRET)] * 2},
    "bad-decision": {"decide": ["this is not json", "still not json"]},
    "bad-sql": {
        "plan": ["DROP TABLE data", "DROP TABLE data", "DROP TABLE data"],
    },
    "bad-answer": {"write": ["not json", "still not json"]},
    "invented-number": {
        "write": [
            json.dumps({"conclusion": "The total is 999.", "claims": []}),
            json.dumps({"conclusion": "The total is 999.", "claims": []}),
            json.dumps({"conclusion": "The total is 999.", "claims": []}),
        ],
    },
}


@pytest.mark.parametrize("name", FAILURES)
def test_a_provider_failure_never_produces_a_number(temporary: Path, name: str) -> None:
    app = create_app(
        settings=_settings(),
        web=WebSettings(),
        factory=lambda settings: _engine(settings, **FAILURES[name]),
    )

    with TestClient(app) as client:
        status, body = _ask(client, _upload(client))

    assert status in (200, 422, 503)
    assert SECRET not in json.dumps(body)
    assert not body.get("claims")
    assert body.get("outcome") != "verified"


@pytest.mark.parametrize(
    "failure",
    [
        GeminiTransientError(SECRET),
        GeminiGenerationError(SECRET),
        InvestigationDeadlineExceeded("late"),
        "this is not sql",
    ],
    ids=["provider-down", "provider-error", "out-of-time", "bad-reply"],
)
def test_a_second_query_that_cannot_finish_blocks_the_verified_label(
    temporary: Path, failure: Reply
) -> None:
    app = create_app(
        settings=_settings(),
        web=WebSettings(),
        factory=lambda settings: _engine(settings, plan=[FIRST, failure, failure]),
    )

    with TestClient(app) as client:
        status, body = _ask(client, _upload(client))

    assert status == 200
    assert body["trust"]["level"] != "verified"
    assert body["outcome"] != "verified"
    checks = {check["name"]: check["status"] for check in body["trust"]["checks"]}
    assert checks["second_query"] != "passed"
    # The evidence already computed stays visible.
    assert body["claims"][0]["verification"]["status"] == "supported"
    assert body["steps"][0]["sql"] == FIRST


def test_more_uploads_than_capacity_are_refused_cleanly(temporary: Path) -> None:
    store = DatasetStore(ttl_seconds=60, max_datasets=1)
    held = store.create_directory()
    app = create_app(settings=_settings(), web=WebSettings(), store=store)

    with TestClient(app) as client:
        response = client.post("/api/datasets", files=[("files", ("data.csv", CSV))])

    assert (response.status_code, response.json()["code"]) == (503, "busy")
    assert not held[1].exists()
