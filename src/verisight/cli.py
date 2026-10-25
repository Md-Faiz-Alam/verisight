"""Local command-line workflow over the public VeriSight facade."""

import argparse
import json
import math
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from verisight.analysis.result import DatasetAnalysisResult
from verisight.config import Settings
from verisight.exceptions import ConfigurationError
from verisight.execution.claim_verification import ClaimOperation
from verisight.execution.context import PopulationFilter, QueryContextBuilder
from verisight.execution.exceptions import QueryValidationError
from verisight.execution.investigation_result import (
    ClaimOutputContract,
    InvestigationResult,
    InvestigationStatus,
)
from verisight.public_api import run_public_operation
from verisight.serialization import to_jsonable
from verisight.service import VeriSight


def _positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("Value must be a positive integer.")
    return number


def _positive_seconds(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Seconds must be finite and positive.")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verisight",
        description="Inspect tabular data and evidence-backed investigations locally.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("profile", "Inspect schema, profiles, and quality findings without AI."),
        ("investigate", "Preview or run an investigation with inspectable evidence."),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("paths", nargs="+", type=Path)
        command.add_argument("--output", type=Path, help="Export JSON to a NEW file.")
        if name == "investigate":
            command.add_argument("--question", required=True)
            command.add_argument(
                "--require-claim",
                action="append",
                choices=[operation.value for operation in ClaimOperation],
                help=(
                    "Require exactly these claim operations; repeat for each claim. "
                    "Checks output and numeric support, not task semantics."
                ),
            )
            command.add_argument(
                "--population", type=Path, help="JSON population array."
            )
            command.add_argument(
                "--preview",
                action="store_true",
                help="Inspect inputs without model calls.",
            )
            command.add_argument(
                "--allow-llm-data-disclosure",
                action="store_true",
                help="Permit analytical context to be sent to the configured model.",
            )
            command.add_argument("--max-steps", type=_positive_int, default=3)
            command.add_argument("--max-seconds", type=_positive_seconds, default=120.0)
            command.add_argument(
                "--request-timeout-seconds", type=_positive_seconds, default=60.0
            )
    return parser


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate field.")
        result[key] = value
    return result


def _population(path: Path | None) -> tuple[PopulationFilter, ...]:
    """Read a bounded JSON contract, never an executable SQL predicate."""
    if path is None:
        return ()
    try:
        with path.open("rb") as source:
            content = source.read(65_537)
        if len(content) > 65_536:
            raise ValueError("Population input too large.")
        payload: object = json.loads(
            content.decode("utf-8-sig"), object_pairs_hook=_unique_object
        )
        if not isinstance(payload, list) or len(payload) > 32:
            raise ValueError("Population input must be an array of at most 32 filters.")
        filters = []
        for item in payload:
            if not isinstance(item, dict) or set(item) != {
                "relation",
                "column",
                "values",
            }:
                raise ValueError("Invalid population fields.")
            values = item["values"]
            if not isinstance(values, list) or len(values) > 128:
                raise ValueError(
                    "Population values must be an array of at most 128 values."
                )
            filters.append(
                PopulationFilter(item["relation"], item["column"], tuple(values))
            )
        return tuple(filters)
    except (
        OSError,
        UnicodeError,
        ValueError,
        TypeError,
        RecursionError,
        QueryValidationError,
    ):
        raise argparse.ArgumentTypeError(
            "Population must be valid UTF-8 JSON: an array of relation, column, "
            "and values objects, using supported homogeneous scalar values. "
            "Limits: 64 KiB, 32 filters, 128 values per filter."
        ) from None


def _profile_view(analysis: DatasetAnalysisResult) -> dict[str, object]:
    return {
        "information_scope": "original_loaded_dataset",
        "summary": analysis.summary,
        "schema": analysis.analysis.schema,
        "profiles": analysis.analysis.profile,
        "quality_findings": analysis.analysis.issues,
        "insights": analysis.insights,
    }


def _run(
    args: argparse.Namespace, population: tuple[PopulationFilter, ...]
) -> tuple[dict[str, object], int]:
    try:
        settings = (
            Settings(allow_llm_data_disclosure=False, gemini_api_key=None)
            if args.command == "profile"
            else Settings(
                allow_llm_data_disclosure=not args.preview,
                max_investigation_seconds=args.max_seconds,
                gemini_request_timeout_seconds=args.request_timeout_seconds,
                gemini_max_retries=1,
                max_query_result_rows=20,
            )
        )
    except ValueError:
        raise ConfigurationError("Invalid command configuration.") from None
    app = VeriSight(settings=settings)
    print("Inspecting original dataset...", file=sys.stderr)
    analysis = app.analyze(args.paths)
    profile = _profile_view(analysis)
    if args.command == "profile":
        return {"kind": "profile", "profile": profile}, 0

    QueryContextBuilder().build(analysis.analysis.schema, population=population)
    contract = (
        ClaimOutputContract(
            tuple(ClaimOperation(value) for value in args.require_claim)
        )
        if args.require_claim
        else None
    )
    request: dict[str, object] = {
        "paths": [str(path) for path in args.paths],
        "question": args.question,
        "claim_output_contract": contract,
        "population": population,
        "population_mode": "caller_selected" if population else "unscoped",
        "model": settings.gemini_model,
        "max_steps": args.max_steps,
        "max_investigation_seconds": settings.max_investigation_seconds,
        "request_timeout_seconds": settings.gemini_request_timeout_seconds,
        "provider_retries": settings.gemini_max_retries,
        "max_query_result_rows": settings.max_query_result_rows,
        "max_query_result_bytes": settings.max_query_result_bytes,
        "max_query_execution_seconds": settings.max_query_execution_seconds,
        "max_query_memory_mb": settings.max_query_memory_mb,
        "max_query_temp_storage_mb": settings.max_query_temp_storage_mb,
    }
    preview: dict[str, object] = {
        "kind": "investigation_preview",
        "request": request,
        "profile": profile,
    }
    if args.preview:
        return preview, 0
    if settings.gemini_api_key is None or not settings.gemini_api_key.strip():
        raise ConfigurationError("Investigation requires a configured model key.")
    # This is a preliminary inspection: the facade reloads paths for investigation.
    # The final report uses the analysis attached to the executed investigation.
    print("Request and preliminary profile (original data):", file=sys.stderr)
    print(json.dumps(to_jsonable(preview), indent=2, allow_nan=False), file=sys.stderr)
    print(
        "Running bounded investigation; numerical support "
        "does not certify analytical meaning...",
        file=sys.stderr,
    )
    result: InvestigationResult = app.investigate(
        args.paths, args.question, max_steps=args.max_steps, population=population
    )
    assessment = None if contract is None else result.assess_output(contract)
    report: dict[str, object] = {
        "kind": "investigation",
        "request": request,
        "workflow_status": result.status.value,
        "claim_output_assessment": assessment,
        "population": result.population,
        "profile": _profile_view(result.analysis),
        "numerical_statements": result.quantitative_statements,
        "unverified_model_interpretation": result.conclusion,
        "investigation": result,
    }
    succeeded = result.status is InvestigationStatus.COMPLETE and (
        assessment is None or assessment.accepted
    )
    return report, 0 if succeeded else 1


def main(argv: list[str] | None = None) -> int:
    """Return workflow and optional output-contract status, not semantic truth."""
    parser = _parser()
    args = parser.parse_args(argv)
    if args.command == "investigate":
        if not args.question.strip():
            parser.error("Question must not be blank.")
        if not args.preview and not args.allow_llm_data_disclosure:
            parser.error(
                "Use --preview for offline inspection, or explicitly pass "
                "--allow-llm-data-disclosure to run generation."
            )
    if args.output is not None and (
        args.output.exists()
        or args.output.is_symlink()
        or not args.output.parent.is_dir()
    ):
        parser.error("Output must be a new file in an existing directory.")
    try:
        population = (
            _population(args.population) if args.command == "investigate" else ()
        )
    except argparse.ArgumentTypeError as error:
        parser.error(str(error))
    try:
        operation = run_public_operation(lambda: _run(args, population))
    except KeyboardInterrupt:
        print(
            "Operation interrupted; no completed report was produced.", file=sys.stderr
        )
        return 130
    if operation.error is not None:
        payload: dict[str, object] = {
            "kind": "operation_error",
            "error": operation.error,
        }
        exit_code = 1
    else:
        assert operation.value is not None
        payload, exit_code = operation.value
    report: dict[str, object] = {
        "schema_version": 1,
        "report_type": "local_cli",
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "limitations": (
            "Workflow completion is not analytical correctness. Numerical support "
            "checks referenced values only. Population filters do not verify business "
            "meaning or provide privacy isolation. Narrative meaning is unverified. "
            "Inspect population, grain, denominator, time period, units, and SQL."
        ),
        **payload,
    }
    serialized = json.dumps(to_jsonable(report), indent=2, allow_nan=False)
    print(serialized)
    if args.output is not None:
        try:
            with args.output.open("x", encoding="utf-8") as destination:
                destination.write(serialized + "\n")
        except OSError:
            print(
                "Could not export report to a new file. Console output is retained.",
                file=sys.stderr,
            )
            return 2
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
