"""Website and REST API: uploads, profiles, verified answers, limits and safety."""

import json
import re
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from verisight.analytics.dashboard import DashboardBuilder
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
from verisight.web.app import _browser_safe
from verisight.web.config import WebSettings
from verisight.web.store import (
    DatasetStore,
    RateLimiter,
    StoredDataset,
    safe_file_name,
)

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
        "SELECT SUM(a) AS cross_check_answer FROM (SELECT amount AS a FROM data) AS d",
    ]


def _ask(client: TestClient, dataset_id: object, **body: object) -> tuple[int, Any]:
    payload = {"question": "How much came in altogether?", "consent": True, **body}
    response = client.post(f"/api/datasets/{dataset_id}/ask", json=payload)
    return response.status_code, response.json()


def test_page_config_and_security_headers(client: TestClient) -> None:
    page = client.get("/")
    docs = client.get("/docs")

    assert page.status_code == 200
    assert '<div id="root">' in page.text
    assets = re.findall(r'(?:src|href)="(/static/[^"]+)"', page.text)
    assert len(assets) >= 3
    assert all(client.get(asset).status_code == 200 for asset in assets)
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["x-frame-options"] == "DENY"
    assert "content-security-policy" not in docs.headers
    assert client.get("/api/health").json() == {"status": "ok"}
    assert client.get("/api/config").json() == {
        "server_key": False,
        "model": "gemini-3.1-flash-lite",
        "max_upload_mb": 20,
        "max_files": 5,
        "dataset_ttl_minutes": 60,
        "allowed_extensions": [
            ".csv",
            ".tsv",
            ".json",
            ".jsonl",
            ".ndjson",
            ".xlsx",
            ".xls",
        ],
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
            "message": "a.parquet: use a CSV, TSV, JSON, JSONL, XLSX or XLS file.",
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
        assert broken == {
            "code": "data_load_error",
            "message": "The file is not valid JSON. Check it with a JSON "
            "validator and upload again.",
        }


def _workbook(rows: list[list[object]]) -> bytes:
    from io import BytesIO

    buffer = BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False, header=False)
    return buffer.getvalue()


def test_repairable_files_load_and_say_what_changed(client: TestClient) -> None:
    uploads = [
        ("lines.json", b'{"a": 1}\n{"a": 2}\n'),
        ("latin.csv", "city,n\nMalmö,1\n".encode("latin-1")),
        ("dupes.csv", b"amount,amount\n1,2\n"),
        ("titled.xlsx", _workbook([["Report", None], ["amount", "region"], [10, "n"]])),
        ("wide.xlsx", _workbook([["amount", None], [10, "stray"]])),
    ]
    for name, data in uploads:
        body = _upload(client, (name, data))
        assert body["profile"]["quality_findings"], name


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("encoding.json", b"{broken", "is not valid JSON"),
        ("nan.json", b'[{"a": NaN}]', "NaN or Infinity"),
        ("dup.json", b'[{"a": 1, "a": 2}]', "repeats the same key"),
        ("scalars.json", b"[1, 2]", "one object per row"),
        ("scalar.json", b"42", "equal-length array per column"),
        ("ragged.json", b'{"a": [1, 2], "b": [3]}', "different lengths"),
        ("latin.json", '[{"city": "Malmö"}]'.encode("latin-1"), "UTF-8"),
        ("nul.csv", b"a,b\n1,\x002\n", "binary data"),
        ("case.json", b'[{"Amount": 1, "amount": 2}]', "differ only by letter case"),
        ("wide.csv", b"a,b\n1,2\n3,4,5\n", "same number of columns"),
        (
            "formula.xlsx",
            _workbook([["amount", "double"], [10, "=A2*2"]]),
            "formulas without saved",
        ),
        (
            "errors.xlsx",
            _workbook([["amount", "ratio"], [10, "#DIV/0!"]]),
            "error cells",
        ),
    ],
)
def test_load_failures_explain_what_to_fix(
    client: TestClient, name: str, data: bytes, message: str
) -> None:
    failure = _upload(client, (name, data), status=422)

    assert failure["code"] in {"data_load_error", "table_validation_error"}
    assert message in failure["message"]
    assert "verisight-" not in failure["message"]
    assert name not in failure["message"]


def test_unknown_load_failures_keep_the_generic_message() -> None:
    from verisight.ingestion.exceptions import DataLoadError

    class _Unreadable(VeriSight):
        def analyze(self, paths: object) -> Any:
            raise DataLoadError("Excel workbook contains a non-string sheet name.")

    class _Broken(VeriSight):
        def analyze(self, paths: object) -> Any:
            raise RuntimeError("Excel worksheet contains error cells.")

    for engine, status, code, text in (
        (_Unreadable, 422, "data_load_error", "could not be read as a table"),
        (_Broken, 500, "internal_error", "unexpected"),
    ):

        def factory(settings: Settings, engine: type[VeriSight] = engine) -> VeriSight:
            return engine(settings=settings)

        app = create_app(settings=_settings(), web=WebSettings(), factory=factory)
        with TestClient(app) as test_client:
            failure = _upload(test_client, ("data.csv", CSV), status=status)
        assert failure["code"] == code
        assert text in failure["message"].lower()
        assert "error cells" not in failure["message"]


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


def test_integers_beyond_browser_precision_are_sent_as_text() -> None:
    big = 9007199254740993  # 2**53 + 1: a browser would show ...992
    data = json.dumps([{"state": "a", "amount": big}, {"state": "b", "amount": 0}])
    app = create_app(settings=_settings("server-key"), web=WebSettings())
    with TestClient(app) as client:
        dataset = _upload(client, ("data.json", data.encode()))
        with patch(GENERATE, side_effect=_script(f"The total is {big}.", str(big))):
            status, answer = _ask(client, dataset["dataset_id"])

    amount = dataset["profile"]["profiles"]["tables"][0]["columns"][1]
    assert amount["maximum"] == str(big)
    assert amount["numeric_statistics"]["maximum"] == str(big)
    assert amount["minimum"] == 0
    assert status == 200
    assert answer["outcome"] == "verified"
    assert answer["steps"][0]["rows"] == [[str(big)]]
    assert answer["claims"][0]["verification"]["actual"] == str(big)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (2**53 - 1, 2**53 - 1),
        (-(2**53) + 1, -(2**53) + 1),
        (2**53, str(2**53)),
        (-(2**53), str(-(2**53))),
        (True, True),
        (0.1, 0.1),
        ({"a": [(2**60, "x")]}, {"a": [[str(2**60), "x"]]}),
    ],
)
def test_browser_safe_values(value: object, expected: object) -> None:
    assert _browser_safe(value) == expected


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


def test_answer_is_verified_only_when_the_second_query_agrees() -> None:
    app = create_app(settings=_settings("server-key"), web=WebSettings())
    with TestClient(app) as client:
        dataset = _upload(client, ("data.csv", CSV))
        with patch(GENERATE, side_effect=_script("The total is 930.", "930")):
            _, agreed = _ask(client, dataset["dataset_id"])
        script = _script("The total is 930.", "930")
        script[-1] = (
            "SELECT SUM(amount) AS cross_check_answer FROM data WHERE state = 'active'"
        )
        with patch(GENERATE, side_effect=script):
            status, disagreed = _ask(client, dataset["dataset_id"])

    assert agreed["outcome"] == "verified"
    assert agreed["cross_check"]["status"] == "agreed"
    assert agreed["cross_check"]["identical_sql"] is False
    assert status == 200
    assert disagreed["outcome"] == "unverified"
    assert disagreed["assessment"]["accepted"] is True
    assert disagreed["cross_check"]["status"] == "disagreed"
    assert disagreed["cross_check"]["primary_value"] == "930"
    assert disagreed["cross_check"]["independent_value"] == "30"
    assert disagreed["cross_check"]["identical_sql"] is False
    assert "WHERE state" in disagreed["cross_check"]["sql"]


def test_second_query_that_repeats_the_first_is_not_shown_as_verified() -> None:
    app = create_app(settings=_settings("server-key"), web=WebSettings())
    script = _script("The total is 930.", "930")
    script[-1] = "SELECT SUM(amount) AS cross_check_answer FROM data"
    with TestClient(app) as client:
        dataset = _upload(client, ("data.csv", CSV))
        with patch(GENERATE, side_effect=script):
            status, answer = _ask(client, dataset["dataset_id"])

    assert status == 200
    assert answer["assessment"]["accepted"] is True
    assert answer["cross_check"]["status"] == "agreed"
    assert answer["cross_check"]["identical_sql"] is True
    assert answer["outcome"] == "unverified"
    assert answer["trust"]["level"] == "number_matched"


def test_dashboard_is_computed_without_a_key_and_filters(client: TestClient) -> None:
    dataset = _upload(client, ("data.csv", CSV))
    url = f"/api/datasets/{dataset['dataset_id']}/dashboard"

    with patch(GENERATE, side_effect=AssertionError("no model call")):
        whole = client.post(url, json={})
        narrowed = client.post(
            url,
            json={
                "relation": "data",
                "filters": [{"column": "state", "value": "active"}],
            },
        )

    assert whole.status_code == 200
    assert whole.json()["relation"] == "data"
    assert whole.json()["computed_by"] == "sql_without_model"
    total = {tile["label"]: tile["value"] for tile in whole.json()["kpis"]}
    assert total == {"Rows": 3, "Total amount": 930}
    kept = {tile["label"]: tile["value"] for tile in narrowed.json()["kpis"]}
    assert kept == {"Rows": 2, "Total amount": 30}
    assert narrowed.json()["filters"] == [{"column": "state", "value": "active"}]


def test_dashboard_accepts_a_date_range(client: TestClient) -> None:
    data = b"day,amount\n2024-01-01,1\n2024-02-01,2\n2024-03-01,4\n"
    dataset = _upload(client, ("data.csv", data))

    response = client.post(
        f"/api/datasets/{dataset['dataset_id']}/dashboard",
        json={"start": "2024-02-01", "end": "2024-02-29"},
    )

    assert {k["label"]: k["value"] for k in response.json()["kpis"]} == {
        "Rows": 1,
        "Total amount": 2,
    }
    assert response.json()["time"]["column"] == "day"


def test_rows_endpoint(client: TestClient) -> None:
    dataset = _upload(client, ("data.csv", CSV))
    url = f"/api/datasets/{dataset['dataset_id']}/rows"

    page = client.post(
        url,
        json={"relation": "data", "sort": "amount", "descending": True, "limit": 1},
    ).json()
    refused = client.post(url, json={"relation": "data", "sort": "nope"})
    missing = client.post("/api/datasets/nope/rows", json={"relation": "data"})

    assert page["rows"] == [["other", 900]]
    assert page["total"] == 3
    assert (refused.status_code, refused.json()["code"]) == (400, "invalid_rows")
    assert missing.status_code == 404


def test_rows_endpoint_rate_limit() -> None:
    with _client(dashboards_per_hour=1) as client:
        dataset = _upload(client, ("data.csv", CSV))
        url = f"/api/datasets/{dataset['dataset_id']}/rows"
        assert client.post(url, json={"relation": "data"}).status_code == 200
        limited = client.post(url, json={"relation": "data"})

    assert (limited.status_code, limited.json()["code"]) == (429, "rate_limited")


def test_rows_endpoint_reports_a_failed_load() -> None:
    class _NoRows(VeriSight):
        def dashboard_builder(self, paths: object) -> DashboardBuilder:
            raise ConfigurationError("secret detail")

    app = create_app(
        settings=_settings(),
        web=WebSettings(),
        factory=lambda settings: _NoRows(settings=settings),
    )
    with TestClient(app) as client:
        dataset = _upload(client, ("data.csv", CSV))
        response = client.post(
            f"/api/datasets/{dataset['dataset_id']}/rows", json={"relation": "data"}
        )

    assert response.status_code == 500
    assert "secret" not in response.text


def test_dashboard_loads_a_dataset_once() -> None:
    made: list[VeriSight] = []

    def factory(settings: Settings) -> VeriSight:
        assert settings.gemini_api_key is None
        made.append(VeriSight(settings=settings))
        return made[-1]

    app = create_app(settings=_settings(), web=WebSettings(), factory=factory)
    with TestClient(app) as client:
        dataset = _upload(client, ("data.csv", CSV))
        before = len(made)
        url = f"/api/datasets/{dataset['dataset_id']}/dashboard"
        assert client.post(url, json={}).status_code == 200
        assert client.post(url, json={}).status_code == 200

    # The upload already loaded the files, so the charts read nothing again.
    assert len(made) == before


@pytest.mark.parametrize(
    "body",
    [
        {"relation": "missing"},
        {"filters": [{"column": "amount", "value": "1"}]},
    ],
)
def test_dashboard_refuses_unknown_tables_and_columns(
    client: TestClient, body: dict[str, object]
) -> None:
    dataset = _upload(client, ("data.csv", CSV))

    response = client.post(
        f"/api/datasets/{dataset['dataset_id']}/dashboard", json=body
    )

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_dashboard"


def test_dashboard_for_unknown_dataset(client: TestClient) -> None:
    response = client.post("/api/datasets/nope/dashboard", json={})

    assert response.status_code == 404
    assert response.json()["code"] == "dataset_not_found"


def test_dashboard_rate_limit() -> None:
    with _client(dashboards_per_hour=1) as client:
        dataset = _upload(client, ("data.csv", CSV))
        url = f"/api/datasets/{dataset['dataset_id']}/dashboard"
        assert client.post(url, json={}).status_code == 200
        limited = client.post(url, json={})

    assert (limited.status_code, limited.json()["code"]) == (429, "rate_limited")


def test_dashboard_reports_a_failed_load() -> None:
    class _NoDashboard(VeriSight):
        def dashboard_builder(self, paths: object) -> DashboardBuilder:
            raise ConfigurationError("secret detail")

    app = create_app(
        settings=_settings(),
        web=WebSettings(),
        factory=lambda settings: _NoDashboard(settings=settings),
    )
    with TestClient(app) as client:
        dataset = _upload(client, ("data.csv", CSV))
        response = client.post(
            f"/api/datasets/{dataset['dataset_id']}/dashboard", json={}
        )

    assert response.status_code == 500
    assert response.json()["code"] == "configuration_error"
    assert "secret" not in response.text


def _stored(store: DatasetStore) -> StoredDataset:
    dataset_id, directory = store.create_directory()
    item = StoredDataset(dataset_id, directory, (), created=time.monotonic())
    store.add(item)
    return item


def test_prepared_datasets_are_reused_limited_and_dropped() -> None:
    store = DatasetStore(ttl_seconds=60, max_datasets=5, max_prepared=2)
    first, second, third = _stored(store), _stored(store), _stored(store)

    assert store.prepared(first, lambda: "one") == "one"
    assert store.prepared(second, lambda: "two") == "two"
    assert store.prepared(first, lambda: "again") == "one"
    assert store.prepared(third, lambda: "three") == "three"

    # The least recently used dataset gives up its memory first.
    assert second.prepared is None
    assert first.prepared == "one"
    store.delete(first.dataset_id)
    assert store.prepared(second, lambda: "rebuilt") == "rebuilt"
    assert third.prepared == "three"
    store.clear()


def test_dataset_removed_while_preparing_keeps_nothing() -> None:
    store = DatasetStore(ttl_seconds=60, max_datasets=5)
    item = _stored(store)

    def removed_meanwhile() -> str:
        store.delete(item.dataset_id)
        return "value"

    assert store.prepared(item, removed_meanwhile) == "value"
    assert item.prepared is None


def test_plain_questions_need_no_key_or_consent(client: TestClient) -> None:
    dataset = _upload(client, ("data.csv", CSV))

    with patch(GENERATE, side_effect=AssertionError("no model call")):
        status, answer = _ask(
            client,
            dataset["dataset_id"],
            question="What is the total amount?",
            consent=False,
        )

    assert status == 200
    assert answer["outcome"] == "verified"
    assert answer["trust"]["level"] == "computed"
    assert answer["model_calls"] == []
    assert answer["steps"][0]["rows"] == [[930]]
    assert answer["claims"][0]["verification"]["status"] == "supported"


def test_unclear_values_get_a_question_back(client: TestClient) -> None:
    data = b"origin,dest,fare\nParis,Rome,10\nRome,Oslo,20\n"
    dataset = _upload(client, ("trips.csv", data))

    status, answer = _ask(
        client,
        dataset["dataset_id"],
        question="What is the total fare for Rome?",
        consent=False,
    )

    assert status == 200
    assert answer["outcome"] == "clarify"
    assert len(answer["options"]) == 2


def test_difference_questions_skip_the_direct_path(client: TestClient) -> None:
    dataset = _upload(client, ("data.csv", CSV))

    status, error = _ask(
        client,
        dataset["dataset_id"],
        question="What is the total amount?",
        consent=False,
        answer_type="difference",
    )

    assert (status, error["code"]) == (400, "consent_required")


def test_direct_answers_count_against_the_rate_limit() -> None:
    with _client(questions_per_hour=1) as client:
        dataset = _upload(client, ("data.csv", CSV))
        question = "What is the total amount?"
        assert _ask(client, dataset["dataset_id"], question=question)[0] == 200
        status, error = _ask(client, dataset["dataset_id"], question=question)

    assert (status, error["code"]) == (429, "rate_limited")


def test_broken_direct_path_falls_back_to_the_model_workflow() -> None:
    class _NoDirect(VeriSight):
        def dashboard_builder(self, paths: object) -> DashboardBuilder:
            raise ConfigurationError("secret detail")

    app = create_app(
        settings=_settings(),
        web=WebSettings(),
        factory=lambda settings: _NoDirect(settings=settings),
    )
    with TestClient(app) as client:
        dataset = _upload(client, ("data.csv", CSV))
        status, error = _ask(
            client,
            dataset["dataset_id"],
            question="What is the total amount?",
            consent=False,
        )

    assert (status, error["code"]) == (400, "consent_required")


def test_audit_failure_withholds_verified() -> None:
    app = create_app(settings=_settings("server-key"), web=WebSettings())
    script = _script("The total is 930.", "930")
    flawed = "SELECT SUM(amount) AS total FROM data WHERE state = 'nope' OR 1 = 1"
    script[1] = flawed
    with TestClient(app) as client:
        dataset = _upload(client, ("data.csv", CSV))
        with patch(GENERATE, side_effect=script):
            status, answer = _ask(client, dataset["dataset_id"])

    assert status == 200
    assert answer["outcome"] == "unverified"
    assert answer["trust"]["level"] == "needs_review"


def test_unavailable_second_check_withholds_verified() -> None:
    app = create_app(settings=_settings("server-key"), web=WebSettings())
    script: list[object] = list(_script("The total is 930.", "930"))
    script[-1] = GeminiTransientError("secret")
    with TestClient(app) as client:
        dataset = _upload(client, ("data.csv", CSV))
        with patch(GENERATE, side_effect=script):
            status, answer = _ask(client, dataset["dataset_id"])

    assert status == 200
    assert answer["outcome"] == "unverified"
    assert answer["cross_check"]["status"] == "not_assessed"
    assert answer["cross_check"]["reason"] == "provider_failed"
    assert "secret" not in json.dumps(answer)


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
        cross_check: bool = False,
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


def test_capacity_is_enforced_when_uploads_finish_not_when_they_start() -> None:
    from verisight.web.store import StoredDataset, StoreFullError

    clock = Clock()
    store = DatasetStore(ttl_seconds=60, max_datasets=2, clock=clock)
    first, first_dir = store.create_directory()
    second, second_dir = store.create_directory()
    # Slots are reserved atomically: a third concurrent upload must wait.
    with pytest.raises(StoreFullError):
        store.create_directory()

    store.add(StoredDataset(first, first_dir, (), clock()))
    clock.now += 1
    store.add(StoredDataset(second, second_dir, (), clock()))
    clock.now += 1
    # Starting an upload at capacity evicts nothing.
    third, third_dir = store.create_directory()
    assert store.get(first) is not None

    # A failed upload releases its slot and never evicts stored data.
    store.release(third)
    store.release(third)
    assert not third_dir.exists()
    assert store.get(first) is not None

    # A finished upload evicts the oldest stored dataset beyond capacity.
    fourth, fourth_dir = store.create_directory()
    store.add(StoredDataset(fourth, fourth_dir, (), clock()))
    assert store.get(first) is None
    assert not first_dir.exists()
    assert store.get(second) is not None
    assert store.get(fourth) is not None

    _, pending_dir = store.create_directory()
    store.clear()
    assert not pending_dir.exists()
    assert not second_dir.exists()


def test_invalid_upload_at_capacity_keeps_the_stored_dataset() -> None:
    store = DatasetStore(ttl_seconds=60, max_datasets=1)
    app = create_app(settings=_settings(), web=WebSettings(), store=store)
    with TestClient(app) as client:
        kept = _upload(client, ("data.csv", CSV))["dataset_id"]
        _upload(client, ("bad.json", b"{broken"), status=422)
        _upload(client, ("a.parquet", b"x"), status=415)

        assert store.get(str(kept)) is not None


def test_uploads_are_refused_while_every_slot_is_being_checked() -> None:
    store = DatasetStore(ttl_seconds=60, max_datasets=1)
    store.create_directory()
    app = create_app(settings=_settings(), web=WebSettings(), store=store)
    with TestClient(app) as client:
        assert _upload(client, ("data.csv", CSV), status=503)["code"] == "busy"
        assert client.post("/api/datasets/demo").status_code == 503


def test_oversized_request_is_refused_before_it_is_parsed() -> None:
    with _client(max_upload_mb=1, max_files=1) as client:
        body = b"a\n" + b"1\n" * (1024 * 1024 + 300_000)
        response = client.post("/api/datasets", files=[("files", ("big.csv", body))])

    assert response.status_code == 413
    assert response.json()["code"] == "file_too_large"
    assert response.headers["x-content-type-options"] == "nosniff"


def _limited(
    downstream: Any, chunks: list[bytes], path: str = "/api/datasets"
) -> list[Any]:
    import asyncio

    from verisight.web.app import UploadBodyLimit

    messages: list[dict[str, Any]] = [
        {"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
        for i, chunk in enumerate(chunks)
    ] or [{"type": "http.disconnect"}]
    sent: list[Any] = []

    async def receive() -> Any:
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message: Any) -> None:
        sent.append(message)

    middleware = UploadBodyLimit(downstream, limit_bytes=10, max_upload_mb=1)
    scope = {"type": "http", "method": "POST", "path": path, "headers": []}
    asyncio.run(middleware(scope, receive, send))
    return sent


async def _read_all_then_reply(scope: Any, receive: Any, send: Any) -> None:
    while True:
        message = await receive()
        if not message.get("more_body"):
            break
    # A parser may read again after a disconnect; it must not get more data.
    assert (await receive())["type"] in {"http.disconnect", "http.request"}
    await send({"type": "http.response.start", "status": 201, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def _read_then_fail(scope: Any, receive: Any, send: Any) -> None:
    while (await receive()).get("more_body"):
        pass
    raise ValueError("body could not be parsed")


def test_body_limit_counts_bodies_without_a_declared_length() -> None:
    refused = _limited(_read_all_then_reply, [b"123456", b"789012", b"3"])
    allowed = _limited(_read_all_then_reply, [b"12345", b"67890"])
    other = _limited(_read_all_then_reply, [b"x" * 50], path="/api/other")
    disconnected = _limited(_read_all_then_reply, [])
    failed = _limited(_read_then_fail, [b"123456", b"789012"])

    assert [m["status"] for m in refused if "status" in m] == [413]
    assert len(refused) == 2
    assert allowed[0]["status"] == 201
    assert other[0]["status"] == 201
    assert disconnected[0]["status"] == 201
    assert failed[0]["status"] == 413
    with pytest.raises(ValueError, match="parsed"):
        _limited(_read_then_fail, [b"12345"])


def test_expired_uploads_are_deleted_while_the_server_is_idle() -> None:
    import time

    clock = Clock()
    store = DatasetStore(ttl_seconds=60, max_datasets=5, clock=clock)
    app = create_app(
        settings=_settings(),
        web=WebSettings(cleanup_interval_seconds=0.02),
        store=store,
        clock=clock,
    )
    with TestClient(app) as client:
        dataset_id = _upload(client, ("data.csv", CSV))["dataset_id"]
        stored = store.get(str(dataset_id))
        assert stored is not None
        clock.now += 61
        deadline = time.monotonic() + 5
        while stored.directory.exists() and time.monotonic() < deadline:
            time.sleep(0.02)

        assert not stored.directory.exists()


def test_excel_unpacked_size_is_limited(tmp_path: Path) -> None:
    rows: list[list[object]] = [["note"]]
    rows.extend(["x" * 200] for _ in range(6000))
    workbook = _workbook(rows)
    with TestClient(
        create_app(
            settings=Settings(max_excel_uncompressed_mb=1),
            web=WebSettings(),
        )
    ) as client:
        failure = _upload(client, ("wide.xlsx", workbook), status=422)

    assert len(workbook) < 1024 * 1024
    assert failure["code"] == "data_load_error"
    assert "too large once unpacked" in failure["message"]
