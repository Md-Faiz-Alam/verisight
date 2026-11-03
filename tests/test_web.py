"""Website and REST API: uploads, profiles, verified answers, limits and safety."""

import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from verisight.config import Settings
from verisight.exceptions import ConfigurationError
from verisight.execution.context import PopulationFilter
from verisight.execution.gemini import (
    GeminiTransientError,
    ProviderFailureDiagnostics,
)
from verisight.execution.investigation_result import (
    ClaimOutputContract,
    InvestigationResult,
)
from verisight.service import VeriSight
from verisight.web import create_app
from verisight.web.__main__ import main as serve
from verisight.web.config import WebSettings
from verisight.web.store import DatasetStore, RateLimiter, safe_file_name

GENERATE = "verisight.execution.gemini.GeminiTextGenerationClient.generate"
CSV = b"state,amount\nactive,10\nother,900\nactive,20\n"


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _settings(key: str | None = None) -> Settings:
    return Settings(gemini_api_key=key, allow_llm_data_disclosure=False)


def _client(**web: Any) -> TestClient:
    return TestClient(create_app(settings=_settings(), web=WebSettings(**web)))


@pytest.fixture
def client() -> Iterator[TestClient]:
    with _client() as test_client:
        yield test_client


def _upload(client: TestClient, *files: tuple[str, bytes], status: int = 201) -> Any:
    response = client.post(
        "/api/datasets", files=[("files", (name, data)) for name, data in files]
    )
    assert response.status_code == status, response.text
    return response.json()


def _script(conclusion: str, expected: str, column: str = "total") -> list[str]:
    return [
        json.dumps({"action": "investigate", "reasoning": "m", "question": "Sum"}),
        f"SELECT SUM(amount) AS {column} FROM data",
        json.dumps({"action": "finish", "reasoning": "d", "question": None}),
        json.dumps(
            {
                "conclusion": conclusion,
                "claims": [
                    {
                        "operation": "value",
                        "expected": expected,
                        "left": {
                            "observation_index": 0,
                            "row_index": 0,
                            "column": column,
                        },
                        "right": None,
                    }
                ],
            }
        ),
    ]


def _ask(client: TestClient, dataset_id: object, **body: object) -> tuple[int, Any]:
    payload = {"question": "What is the total amount?", "consent": True, **body}
    response = client.post(f"/api/datasets/{dataset_id}/ask", json=payload)
    return response.status_code, response.json()


def test_page_config_and_security_headers(client: TestClient) -> None:
    page = client.get("/")
    docs = client.get("/docs")

    assert page.status_code == 200
    assert "Get answers you can verify" in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" not in docs.headers
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/config").json() == {
        "server_key": False,
        "model": "gemini-3.1-flash-lite",
        "max_upload_mb": 20,
        "max_files": 5,
        "dataset_ttl_minutes": 60,
        "allowed_extensions": [".csv", ".json", ".xlsx", ".xls"],
    }


def test_demo_dataset_is_profiled_without_server_paths(client: TestClient) -> None:
    body = client.post("/api/datasets/demo").json()

    assert [item["name"] for item in body["files"]] == ["orders.csv", "customers.csv"]
    profile = body["profile"]
    assert [t["relation_name"] for t in profile["schema"]["tables"]] == [
        "orders",
        "customers",
    ]
    assert all("path" not in source for source in profile["sources"])
    rules = {finding["issue_type"] for finding in profile["quality_findings"]}
    assert {"label_variants", "formatted_numbers", "missing_value_markers"} <= rules
    assert body["expires_in_seconds"] == 3600


def test_uploads_are_validated_with_clear_messages() -> None:
    with _client(max_upload_mb=1, max_files=2) as client:
        assert _upload(client, ("a.parquet", b"x"), status=415) == {
            "code": "unsupported_file_type",
            "message": "a.parquet: use a CSV, JSON, XLSX or XLS file.",
        }
        assert _upload(client, ("a.csv", b""), status=400)["code"] == "empty_file"
        big = b"a\n" + b"1\n" * (1024 * 1024)
        assert _upload(client, ("big.csv", big), status=413) == {
            "code": "file_too_large",
            "message": "big.csv is larger than 1 MB.",
        }
        too_many = [("a.csv", CSV), ("b.csv", CSV), ("c.csv", CSV)]
        assert _upload(client, *too_many, status=400)["code"] == "too_many_files"
        broken = _upload(client, ("bad.json", b"{not json"), status=422)
        assert broken["code"] == "data_load_error"
        assert "valid, non-empty CSV" in str(broken["message"])


def test_upload_names_are_cleaned_and_unique(client: TestClient) -> None:
    body = _upload(client, ("../x/my data.csv", CSV), ("my data.csv", CSV))

    assert [item["name"] for item in body["files"]] == [
        "my_data.csv",
        "my_data_2.csv",
    ]


def test_verified_answer_shows_sql_cells_and_claims() -> None:
    app = create_app(settings=_settings("server-key"), web=WebSettings())
    with TestClient(app) as client:
        dataset = _upload(client, ("data.csv", CSV))
        with patch(GENERATE, side_effect=_script("The total is 930.", "930")):
            status, answer = _ask(client, dataset["dataset_id"])

    assert client.get("/api/config").json()["server_key"] is True
    assert status == 200
    assert answer["outcome"] == "verified"
    assert answer["answer"] == "The total is 930."
    assert answer["steps"] == [
        {
            "question": "Sum",
            "sql": "SELECT SUM(amount) AS total FROM data",
            "columns": ["total"],
            "rows": [[930]],
        }
    ]
    claim = answer["claims"][0]
    assert claim["verification"]["status"] == "supported"
    assert answer["failure"] is None
    assert answer["assessment"]["accepted"] is True
    # The patched generate() bypasses per-call telemetry, so no calls are listed.
    assert answer["model_calls"] == []
    assert answer["recovery"] is None


def test_contradicted_number_is_not_verified(client: TestClient) -> None:
    dataset = _upload(client, ("data.csv", CSV))
    script = (
        _script("The total is 931.", "931")
        + [json.dumps({"conclusion": "The total is 931.", "claims": []})] * 4
    )
    with patch(GENERATE, side_effect=script):
        status, answer = _ask(client, dataset["dataset_id"], api_key=" visitor-key ")

    assert status == 200
    assert answer["outcome"] == "unverified"


def test_free_answers_need_no_contract(client: TestClient) -> None:
    dataset = _upload(client, ("data.csv", CSV))
    with patch(GENERATE, side_effect=_script("The total is 930.", "930")):
        status, answer = _ask(
            client, dataset["dataset_id"], api_key="k", answer_type="any"
        )

    assert status == 200
    assert answer["outcome"] == "verified"
    assert answer["assessment"] is None


@pytest.mark.parametrize(
    ("body", "code"),
    [
        ({"api_key": "k", "consent": False}, "consent_required"),
        ({}, "missing_api_key"),
        ({"api_key": "  "}, "missing_api_key"),
        ({"api_key": "k", "question": "   "}, "invalid_question"),
        ({"api_key": "k", "question": "x" * 1001}, "invalid_question"),
    ],
)
def test_questions_are_checked_before_any_model_call(
    client: TestClient, body: dict[str, object], code: str
) -> None:
    dataset = _upload(client, ("data.csv", CSV))
    with patch(GENERATE, side_effect=AssertionError("no model call")):
        status, error = _ask(client, dataset["dataset_id"], **body)

    assert status == 400
    assert error["code"] == code


def test_unknown_and_removed_datasets(client: TestClient) -> None:
    dataset = _upload(client, ("data.csv", CSV))
    dataset_id = dataset["dataset_id"]

    assert client.delete(f"/api/datasets/{dataset_id}").status_code == 204
    assert client.delete(f"/api/datasets/{dataset_id}").json() == {
        "code": "dataset_not_found",
        "message": "This dataset no longer exists.",
    }
    status, error = _ask(client, dataset_id, api_key="k")
    assert status == 404
    assert error["code"] == "dataset_not_found"


def test_rate_limits_and_forwarded_clients() -> None:
    with _client(
        uploads_per_hour=1, questions_per_hour=1, trust_forwarded_for=True
    ) as client:
        first = client.post(
            "/api/datasets/demo", headers={"x-forwarded-for": "1.1.1.1"}
        )
        assert first.status_code == 201
        # A forged left-most entry does not change the proxy-appended client.
        blocked = client.post(
            "/api/datasets/demo", headers={"x-forwarded-for": "9.9.9.9, 1.1.1.1"}
        )
        assert blocked.json()["code"] == "rate_limited"
        upload = client.post(
            "/api/datasets",
            files=[("files", ("data.csv", CSV))],
            headers={"x-forwarded-for": "1.1.1.1"},
        )
        assert upload.status_code == 429
        other = client.post(
            "/api/datasets/demo", headers={"x-forwarded-for": "2.2.2.2"}
        )
        assert other.status_code == 201
        dataset_id = first.json()["dataset_id"]
        with patch(GENERATE, side_effect=_script("The total is 1.", "1")):
            _ask(client, dataset_id, api_key="k")
        status, error = _ask(client, dataset_id, api_key="k")
        assert (status, error["code"]) == (429, "rate_limited")


def test_busy_server_refuses_extra_questions() -> None:
    slots = threading.Semaphore(1)
    slots.acquire()
    app = create_app(settings=_settings(), web=WebSettings(), question_slots=slots)
    with TestClient(app) as client:
        dataset = _upload(client, ("data.csv", CSV))
        status, error = _ask(client, dataset["dataset_id"], api_key="k")

    assert (status, error["code"]) == (503, "busy")


class _Failing(VeriSight):
    def __init__(self, settings: Settings, error: Exception) -> None:
        super().__init__(settings=settings)
        self.error = error

    def investigate(
        self,
        paths: object,
        question: str,
        *,
        max_steps: int = 5,
        population: tuple[PopulationFilter, ...] = (),
        claim_output_contract: ClaimOutputContract | None = None,
    ) -> InvestigationResult:
        raise self.error


@pytest.mark.parametrize(
    ("error", "status", "code", "message"),
    [
        (
            GeminiTransientError(
                "secret",
                diagnostics=ProviderFailureDiagnostics(
                    http_status=503,
                    retryable=True,
                    attempts=4,
                    stage="investigator",
                    call_number=1,
                ),
            ),
            503,
            "provider_unavailable",
            "Gemini is busy or unavailable right now. Wait a minute and ask again.",
        ),
        (
            ConfigurationError("secret"),
            500,
            "configuration_error",
            "Application configuration is unavailable or invalid.",
        ),
    ],
)
def test_engine_failures_become_safe_errors(
    error: Exception, status: int, code: str, message: str
) -> None:
    app = create_app(
        settings=_settings(),
        web=WebSettings(),
        factory=lambda settings: _Failing(settings, error),
    )
    with TestClient(app) as client:
        dataset = _upload(client, ("data.csv", CSV))
        result = _ask(client, dataset["dataset_id"], api_key="k")

    assert result == (status, {"code": code, "message": message})
    assert "secret" not in json.dumps(result)


def test_store_expires_evicts_and_clears(tmp_path: Path) -> None:
    from verisight.web.store import StoredDataset

    clock = Clock()
    store = DatasetStore(ttl_seconds=10, max_datasets=2, clock=clock)
    ids = []
    for _ in range(3):
        dataset_id, directory = store.create_directory()
        store.add(StoredDataset(dataset_id, directory, (), clock()))
        ids.append((dataset_id, directory))
        clock.now += 1

    assert store.get(ids[0][0]) is None
    assert not ids[0][1].exists()
    assert store.get(ids[1][0]) is not None
    clock.now += 11
    assert store.get(ids[2][0]) is None
    dataset_id, directory = store.create_directory()
    store.add(StoredDataset(dataset_id, directory, (), clock()))
    store.clear()
    assert not directory.exists()
    assert store.delete(dataset_id) is False


def test_shutdown_removes_uploaded_files() -> None:
    store = DatasetStore(ttl_seconds=60, max_datasets=5)
    app = create_app(settings=_settings(), web=WebSettings(), store=store)
    with TestClient(app) as client:
        dataset_id = _upload(client, ("data.csv", CSV))["dataset_id"]
        stored = store.get(str(dataset_id))
        assert stored is not None
        assert stored.directory.exists()

    assert not stored.directory.exists()


def test_rate_limiter_window() -> None:
    clock = Clock()
    limiter = RateLimiter(1, clock=clock)

    assert limiter.allow("a") is True
    assert limiter.allow("a") is False
    assert limiter.allow("b") is True
    clock.now += 3600
    assert limiter.allow("a") is True


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (["../../etc/passwd.csv"], ["passwd.csv"]),
        (["C:\\Users\\x\\My Data (1).XLSX"], ["My_Data_1.xlsx"]),
        (["ünïcode.json"], ["ünïcode.json"]),
        (["a.csv", "A.csv", "a.csv"], ["a.csv", "A_2.csv", "a_3.csv"]),
        (["...csv"], ["data.csv"]),
    ],
)
def test_safe_file_names(names: list[str], expected: list[str]) -> None:
    taken: set[str] = set()

    assert [safe_file_name(name, taken) for name in names] == expected


def test_server_entry_point() -> None:
    with patch("uvicorn.run") as run:
        serve(["--host", "0.0.0.0", "--port", "9000"])

    run.assert_called_once_with(
        "verisight.web.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=9000,
        proxy_headers=True,
    )


def test_server_explains_missing_web_extras() -> None:
    with (
        patch.dict("sys.modules", {"uvicorn": None}),
        pytest.raises(SystemExit) as caught,
    ):
        serve([])

    assert "pip install" in str(caught.value)
