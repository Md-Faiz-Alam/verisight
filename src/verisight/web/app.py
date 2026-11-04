"""VeriSight web application: upload data, review its quality, ask questions.

The REST API wraps the same public facade as the CLI. Uploaded files live in
a private temporary directory and are deleted after a time limit or on request.
Questions send the schema, profile, question and observed values to Gemini
only with explicit consent, using the server key or a key supplied with the
request; a supplied key is used for that request only and is never stored.
"""

import json
import re
import shutil
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from importlib.resources import files
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from verisight.analysis.result import DatasetAnalysisResult
from verisight.config import Settings
from verisight.error_reporting import ErrorCode
from verisight.execution.claim_verification import ClaimOperation, VerificationStatus
from verisight.execution.generation_telemetry import (
    GenerationCallReport,
    capture_generation_calls,
)
from verisight.execution.investigation_result import (
    ClaimOutputContract,
    InvestigationResult,
    InvestigationStatus,
)
from verisight.execution.metric_display import summarize_advisory_reviews
from verisight.public_api import run_public_operation
from verisight.serialization import to_jsonable
from verisight.service import VeriSight
from verisight.web.config import WebSettings
from verisight.web.store import (
    ALLOWED_SUFFIXES,
    DatasetStore,
    RateLimiter,
    StoredDataset,
    safe_file_name,
)

PACKAGE = Path(str(files("verisight.web")))
STATIC_DIR = PACKAGE / "static"
DEMO_DIR = PACKAGE / "demo"
DEMO_FILES = ("orders.csv", "customers.csv")
_CHUNK = 1 << 20
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; img-src 'self' data:; style-src 'self'; "
        "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
        "base-uri 'none'; form-action 'none'"
    ),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}
_CONTRACTS = {
    "number": ClaimOutputContract((ClaimOperation.VALUE,)),
    "difference": ClaimOutputContract((ClaimOperation.DIFFERENCE,)),
    "any": None,
}
_VERIFIED = (VerificationStatus.SUPPORTED, VerificationStatus.SUPPORTED_ROUNDED)
_ENGINE_STATUS = {
    ErrorCode.PROVIDER_UNAVAILABLE: 503,
    ErrorCode.INTERNAL_ERROR: 500,
    ErrorCode.CONFIGURATION_ERROR: 500,
}
_ENGINE_HINTS = {
    ErrorCode.PROVIDER_UNAVAILABLE: (
        "Gemini is busy or unavailable right now. Wait a minute and ask again."
    ),
    ErrorCode.UNSUPPORTED_FILE_TYPE: "Use a CSV, JSON, XLSX or XLS file.",
    ErrorCode.DATA_LOAD_ERROR: (
        "The file could not be read as a table. Check that it is a valid, "
        "non-empty CSV, JSON array of objects, or Excel workbook."
    ),
}

# Specific advice for known load failures. Engine messages are matched by
# their fixed leading text and never shown: some include paths or values.
_ENCODING_HINT = (
    "The file is not saved as UTF-8 text. Save it with UTF-8 encoding (in "
    "Excel: Save As, CSV UTF-8) and upload again."
)
_LOAD_HINTS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, re.DOTALL), hint)
    for pattern, hint in (
        (
            r"(CSV|Excel) column headers must not be blank",
            "Some columns have no header. Make sure the first row holds the "
            "headers, with no title rows above it, and every used column has "
            "a name.",
        ),
        (
            r"Excel data contains fields without source headers",
            "Some cells sit in columns without a header. Make sure the first "
            "row holds the headers, with no title rows above it.",
        ),
        (
            r"(CSV|Excel) contains duplicate source column headers"
            r"|Table '.*' contains duplicate column names",
            "Two or more columns have the same header. Rename them so every "
            "header is different and upload again.",
        ),
        (
            r"Table '.*' contains ambiguous SQL column names",
            "Two headers differ only by letter case, such as Amount and "
            "amount. Rename one of them and upload again.",
        ),
        (
            r"CSV encoding could not be established|CSV file uses UTF-32",
            _ENCODING_HINT,
        ),
        (
            r"CSV file contains NUL",
            "The file contains binary data. Upload a plain-text CSV saved as "
            "UTF-8, or the original Excel workbook.",
        ),
        (
            r"CSV delimiter detection was inconclusive",
            "The column separator could not be worked out. Use commas between "
            "columns and the same number of columns on every row.",
        ),
        (
            r"CSV rows contain more fields than the header",
            "Some rows have more values than there are headers. Check for "
            "extra commas or unquoted text that contains commas.",
        ),
        (
            r"Excel formula has no saved result",
            "The workbook has formulas without saved values. Open it in "
            "Excel, save it, and upload again, or export it as CSV.",
        ),
        (
            r"Excel worksheet contains error cells",
            "The worksheet has error cells such as #DIV/0! or #N/A. Fix or "
            "clear them and upload again.",
        ),
        (
            r"Duplicate JSON object key",
            "A JSON object repeats the same key. Each key may appear once per object.",
        ),
        (
            r"Nonstandard JSON numeric constant",
            "The JSON contains NaN or Infinity, which JSON does not allow. "
            "Use null instead.",
        ),
        (
            r"JSON column arrays must all have",
            "The JSON has one array per column, but the arrays have different "
            "lengths. Give every column the same number of values.",
        ),
        (
            r"JSON array must contain objects",
            'A JSON array must hold one object per row, like [{"name": "A", '
            '"value": 1}].',
        ),
        (
            r"JSON root must be",
            "Use a JSON array of row objects, or an object with one "
            "equal-length array per column.",
        ),
    )
)
_JSON_LINES_HINT = (
    "This looks like JSON Lines (one object per line). Put the objects in a "
    "JSON array, like [{...}, {...}], and upload again."
)
_INVALID_JSON_HINT = (
    "The file is not valid JSON. Check it with a JSON validator and upload again."
)

AppFactory = Callable[[Settings], VeriSight]


def _load_hint(error: BaseException) -> str | None:
    """Return fixed advice for the first known failure in an exception chain."""
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, json.JSONDecodeError):
            if current.msg.startswith("Extra data"):
                return _JSON_LINES_HINT
            return _INVALID_JSON_HINT
        if isinstance(current, UnicodeError):
            return _ENCODING_HINT
        text = str(current)
        for pattern, hint in _LOAD_HINTS:
            if pattern.match(text):
                return hint
        current = current.__cause__ or current.__context__
    return None


class WebError(HTTPException):
    """An HTTP error with a stable code and a message written for people."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(status_code=status, detail={"code": code, "message": message})


class AskRequest(BaseModel):
    """A question about an uploaded dataset."""

    question: str = Field(min_length=1)
    answer_type: Literal["number", "difference", "any"] = "number"
    consent: bool = False
    api_key: str | None = Field(default=None, max_length=200, repr=False)


def _default_factory(settings: Settings) -> VeriSight:
    return VeriSight(settings=settings)


def _profile_view(analysis: DatasetAnalysisResult) -> dict[str, object]:
    """Profile for display, without server-side file paths."""
    sources = []
    for source in analysis.analysis.sources:
        fields = cast(dict[str, object], to_jsonable(source))
        fields.pop("path", None)
        sources.append(fields)
    return {
        "summary": to_jsonable(analysis.summary),
        "sources": sources,
        "schema": to_jsonable(analysis.analysis.schema),
        "profiles": to_jsonable(analysis.analysis.profile),
        "quality_findings": to_jsonable(analysis.analysis.issues),
    }


def _answer_view(
    result: InvestigationResult,
    contract: ClaimOutputContract | None,
    calls: list[GenerationCallReport],
    elapsed: float,
) -> dict[str, object]:
    """Summarize an investigation for display; nothing is recomputed here."""
    assessment = None if contract is None else result.assess_output(contract)
    accepted = result.status is InvestigationStatus.COMPLETE and (
        assessment is None or assessment.accepted
    )
    claims = result.verified_claims
    verified = (
        accepted
        and bool(claims)
        and all(claim.verification.status in _VERIFIED for claim in claims)
    )
    return {
        "outcome": "verified" if verified else "unverified",
        "status": result.status.value,
        "answer": result.conclusion,
        "claims": to_jsonable(claims),
        "statements": to_jsonable(result.quantitative_statements),
        "steps": [
            {
                "question": observation.question,
                "sql": observation.sql,
                "columns": to_jsonable(observation.result.columns),
                "rows": to_jsonable(observation.result.rows),
            }
            for observation in result.observations
        ],
        "assessment": to_jsonable(assessment),
        "review_required": summarize_advisory_reviews(result).review_required,
        "failure": to_jsonable(
            result.synthesis_failure or result.investigation_failure
        ),
        "recovery": to_jsonable(result.synthesis_recovery),
        "model_calls": to_jsonable(tuple(calls)),
        "elapsed_seconds": round(elapsed, 2),
    }


def create_app(
    *,
    settings: Settings | None = None,
    web: WebSettings | None = None,
    store: DatasetStore | None = None,
    factory: AppFactory = _default_factory,
    clock: Callable[[], float] = time.monotonic,
    question_slots: threading.Semaphore | None = None,
) -> FastAPI:
    """Build the web application. Arguments exist for tests and embedding."""
    core = settings if settings is not None else Settings()
    limits = web if web is not None else WebSettings()
    datasets = store or DatasetStore(
        ttl_seconds=limits.dataset_ttl_seconds,
        max_datasets=limits.max_datasets,
        clock=clock,
    )
    upload_limiter = RateLimiter(limits.uploads_per_hour, clock=clock)
    question_limiter = RateLimiter(limits.questions_per_hour, clock=clock)
    slots = question_slots or threading.BoundedSemaphore(
        limits.max_concurrent_questions
    )
    server_key = (core.gemini_api_key or "").strip()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        datasets.clear()

    app = FastAPI(
        title="VeriSight",
        summary="Ask questions about tabular data and get SQL-verified answers.",
        version="0.2.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if not request.url.path.startswith(("/docs", "/redoc", "/openapi")):
            response.headers.update(_SECURITY_HEADERS)
        return response

    def client_of(request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for", "")
        if limits.trust_forwarded_for and forwarded.strip():
            # The proxy appends the address it saw; earlier entries come from
            # the client and could be forged to dodge rate limits.
            return forwarded.split(",")[-1].strip()
        return str(getattr(request.client, "host", "unknown"))

    def analyze(paths: tuple[Path, ...]) -> dict[str, object]:
        engine = factory(
            core.model_copy(
                update={"allow_llm_data_disclosure": False, "gemini_api_key": None}
            )
        )
        hints: list[str] = []

        def load() -> DatasetAnalysisResult:
            try:
                return engine.analyze(paths)
            except Exception as exc:
                hint = _load_hint(exc)
                if hint is not None:
                    hints.append(hint)
                raise

        operation = run_public_operation(load)
        if operation.error is not None:
            report = operation.error
            message = _ENGINE_HINTS.get(report.code, report.message)
            if hints and report.code is not ErrorCode.INTERNAL_ERROR:
                message = hints[0]
            raise WebError(
                _ENGINE_STATUS.get(report.code, 422), report.code.value, message
            )
        assert operation.value is not None
        return _profile_view(operation.value)

    async def register(
        dataset_id: str, directory: Path, paths: list[Path]
    ) -> dict[str, object]:
        try:
            profile = await run_in_threadpool(analyze, tuple(paths))
        except WebError:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        datasets.add(
            StoredDataset(
                dataset_id=dataset_id,
                directory=directory,
                paths=tuple(paths),
                created=clock(),
                profile=profile,
            )
        )
        return {
            "dataset_id": dataset_id,
            "files": [
                {"name": path.name, "size_bytes": path.stat().st_size} for path in paths
            ],
            "expires_in_seconds": limits.dataset_ttl_seconds,
            "profile": profile,
        }

    @app.exception_handler(WebError)
    async def web_error(_: Request, error: WebError) -> JSONResponse:
        return JSONResponse(status_code=error.status_code, content=error.detail)

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/config")
    async def config() -> dict[str, object]:
        return {
            "server_key": bool(server_key),
            "model": core.gemini_model,
            "max_upload_mb": limits.max_upload_mb,
            "max_files": limits.max_files,
            "dataset_ttl_minutes": limits.dataset_ttl_seconds // 60,
            "allowed_extensions": list(ALLOWED_SUFFIXES),
        }

    @app.post("/api/datasets", status_code=201)
    async def upload(
        request: Request, uploads: Annotated[list[UploadFile], File(alias="files")]
    ) -> dict[str, object]:
        if not upload_limiter.allow(client_of(request)):
            raise WebError(
                429, "rate_limited", "Too many uploads. Try again in an hour."
            )
        if len(uploads) > limits.max_files:
            raise WebError(
                400,
                "too_many_files",
                f"Upload at most {limits.max_files} files at a time.",
            )
        limit = limits.max_upload_mb * 1024 * 1024
        dataset_id, directory = datasets.create_directory()
        taken: set[str] = set()
        paths: list[Path] = []
        try:
            for item in uploads:
                original = item.filename or "file"
                if Path(original).suffix.lower() not in ALLOWED_SUFFIXES:
                    raise WebError(
                        415,
                        "unsupported_file_type",
                        f"{original}: use a CSV, JSON, XLSX or XLS file.",
                    )
                target = directory / safe_file_name(original, taken)
                size = 0
                with target.open("wb") as handle:
                    while chunk := await item.read(_CHUNK):
                        size += len(chunk)
                        if size > limit:
                            raise WebError(
                                413,
                                "file_too_large",
                                f"{original} is larger than {limits.max_upload_mb} MB.",
                            )
                        handle.write(chunk)
                if size == 0:
                    raise WebError(400, "empty_file", f"{original} is empty.")
                paths.append(target)
        except WebError:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        return await register(dataset_id, directory, paths)

    @app.post("/api/datasets/demo", status_code=201)
    async def demo(request: Request) -> dict[str, object]:
        if not upload_limiter.allow(client_of(request)):
            raise WebError(
                429, "rate_limited", "Too many uploads. Try again in an hour."
            )
        dataset_id, directory = datasets.create_directory()
        paths = [
            Path(shutil.copyfile(DEMO_DIR / name, directory / name))
            for name in DEMO_FILES
        ]
        return await register(dataset_id, directory, paths)

    @app.delete("/api/datasets/{dataset_id}", status_code=204)
    async def remove(dataset_id: str) -> Response:
        if not datasets.delete(dataset_id):
            raise WebError(404, "dataset_not_found", "This dataset no longer exists.")
        return Response(status_code=204)

    @app.post("/api/datasets/{dataset_id}/ask")
    async def ask(
        dataset_id: str, body: AskRequest, request: Request
    ) -> dict[str, object]:
        stored = datasets.get(dataset_id)
        if stored is None:
            raise WebError(
                404,
                "dataset_not_found",
                "This dataset has expired or was removed. Upload it again.",
            )
        question = body.question.strip()
        if not question or len(question) > limits.max_question_chars:
            raise WebError(
                400,
                "invalid_question",
                f"Ask a question of 1 to {limits.max_question_chars} characters.",
            )
        if not body.consent:
            raise WebError(
                400,
                "consent_required",
                "Confirm that the schema, profile, question and sample values "
                "may be sent to Gemini.",
            )
        key = (body.api_key or "").strip() or server_key
        if not key:
            raise WebError(
                400,
                "missing_api_key",
                "Add a Gemini API key. It is used for this question only and is "
                "never stored.",
            )
        if not question_limiter.allow(client_of(request)):
            raise WebError(
                429, "rate_limited", "Too many questions. Try again in an hour."
            )
        if not slots.acquire(blocking=False):
            raise WebError(
                503, "busy", "VeriSight is answering other questions. Try again soon."
            )
        try:
            return await run_in_threadpool(
                investigate, stored.paths, question, body.answer_type, key
            )
        finally:
            slots.release()

    def investigate(
        paths: tuple[Path, ...], question: str, answer_type: str, key: str
    ) -> dict[str, object]:
        contract = _CONTRACTS[answer_type]
        engine = factory(
            core.model_copy(
                update={
                    "gemini_api_key": key,
                    "allow_llm_data_disclosure": True,
                    "max_investigation_seconds": limits.max_investigation_seconds,
                    "gemini_max_retries": limits.provider_retries,
                    "gemini_retry_base_delay_seconds": (
                        limits.provider_retry_delay_seconds
                    ),
                    "max_query_result_rows": limits.max_result_rows,
                }
            )
        )
        started = time.perf_counter()
        with capture_generation_calls() as calls:
            operation = run_public_operation(
                lambda: engine.investigate(
                    paths, question, max_steps=3, claim_output_contract=contract
                )
            )
        if operation.error is not None:
            report = operation.error
            raise WebError(
                _ENGINE_STATUS.get(report.code, 422),
                report.code.value,
                _ENGINE_HINTS.get(report.code, report.message),
            )
        assert operation.value is not None
        return _answer_view(
            operation.value, contract, list(calls), time.perf_counter() - started
        )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app
