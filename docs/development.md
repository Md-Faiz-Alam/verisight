# VeriSight development guide

## Setup and repository layout

Use Python 3.11 or newer. CI currently tests Python 3.11 on Windows and Linux.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Dependencies and tool configuration live in `pyproject.toml`. The development
scripts run from the repository root and are not included by the current
`src` package discovery configuration.

| Location | Responsibility |
| --- | --- |
| `src/verisight/ingestion/` | Validation, loaders, and schema inference |
| `src/verisight/execution/` | SQL, generation, investigation, and verification |
| `src/verisight/service.py` | Public Python facade |
| `src/verisight/cli.py` | Local profile, preview, investigation, and export workflow |
| `src/verisight/error_reporting.py` | Fixed public error classification |
| `src/verisight/public_api.py` | Operation boundary |
| `tests/` | Offline regression and development benchmark tests |
| `scripts/` | Development evaluation utilities |
| `reports/evaluations/` | Reviewed evaluation evidence |
| `.github/workflows/ci.yml` | Automated quality gates |

## Required gates and CI

Run from the repository root:

```powershell
python -m ruff format .
python -m ruff format --check .
python -m ruff check .
python -m mypy --strict src tests scripts
python -m pytest --cov=verisight --cov=scripts --cov-report=term-missing --cov-fail-under=100
git diff --check
```

Include `scripts` explicitly in mypy and coverage commands. The project enables
branch coverage. Full coverage is an engineering gate, not proof of analytical
correctness.

CI runs formatting, lint, strict mypy, full offline coverage, and whitespace
checks on Python 3.11 with `ubuntu-latest` and `windows-latest`. It triggers on
pushes to `main`, pull requests, and manual dispatch. Jobs have a 15-minute
limit and fail independently. CI uses read-only repository permissions, pinned
action commits, and no provider credentials or live evaluations.

Dependencies are resolved within the ranges in `pyproject.toml`; the project
does not yet have a committed dependency lock. Record installed versions when
investigating differences between local and hosted runs.

Use focused tests while changing behavior, then run the full gate for runtime
changes. Documentation-only changes require checking accuracy, examples, links,
and diffs. Do not invent runtime tests solely for documentation edits.

## Test contracts

Use synthetic data and deterministic generation substitutes. Test meaningful
behavior: source-value preservation, SQL guards, independent analytical answers,
partial evidence, safe metadata, serialization, and numerical boundaries.
Use short explicit parameter IDs for large or unusual fixtures.

Keep these distinctions visible:

- Evidence support versus analytical correctness.
- Workflow completion versus verified correctness.
- Optional claim output acceptance versus full task acceptance.
- Missing claims versus justified abstention.
- Unverifiable versus contradicted values.
- Token linkage versus digit coverage versus narrative meaning.

Structured generated claims use decimal strings and zero tolerance. The model
cannot choose a tolerance. Keep `narrative_verified=False` and
`verification_scope="referenced_numeric_values_only"` unless a separately
specified, implemented, and evaluated contract replaces them.

Recovery tests should cover failures after real successful SQL execution,
serialization of retained evidence, and failure redaction. Unexpected programming
errors must remain distinguishable. Results retain recorded failed attempts and
available query repair history; they are not a complete provider-call trace.
Reuse relevant existing test modules when adding regressions for concrete bugs.

`ClaimOutputContract` is a caller-selected postcondition, not a semantic verifier.
Test exact operation multiplicities, support, incomplete status, numeric audit
failures, unchanged evidence, and CLI exit behavior. Without `--require-claim`,
the CLI retains workflow-based exit status. Contract rejection must not silently
drop claims or add provider calls. See [Output contracts](output-contracts.md).

## Deterministic and live evaluation

Run the offline development benchmark:

```powershell
python -m pytest tests/test_verification_benchmark.py -q
```

Expected answers must be independent of generated SQL and claims. Adversarial
cases demonstrate that an analytically wrong query can produce a supported
claim.

The live runner has five default fixtures: finance, retail, manufacturing,
healthcare, and logistics. `--case challenge` selects three additional development
fixtures: `energy_grain`, `research_weighted`, and `education_entities`.
`--case all` selects only the five default cases. The runner creates temporary
synthetic files, enables disclosure for those fixtures, and calls the real
configured provider path.
A key is required; calls may incur charges.

```powershell
python -m scripts.live_evaluation --live --case finance
New-Item -ItemType Directory -Force reports/evaluations | Out-Null
$evaluationStamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
python -m scripts.live_evaluation --live --case all --request-timeout-seconds 60 --provider-retries 1 --output "reports/evaluations/live-$evaluationStamp.json"
```

| Control | Default |
| --- | --- |
| Case | `finance` |
| Analytical attempts per case | 1 |
| Provider request timeout | 20 seconds |
| Additional provider retries per generation call | 0 |
| SQL execution timeout | 5 seconds |
| Maximum query result rows | 20 |
| Shared investigation budget | Settings/environment value; 300 seconds by default |

`--request-timeout-seconds` accepts a finite positive value.
`--provider-retries` accepts integers from 0 through 5. These overrides apply
only to that evaluation invocation; they do not change application defaults.
One analytical attempt can require several generation calls and retries.

JSON is printed. `--output` additionally saves to a new file whose parent must
exist. Existing files are not overwritten.

| Exit code | Meaning |
| --- | --- |
| `0` | Every selected case received `correct_numeric` |
| `1` | At least one selected case had another outcome |
| `2` | Argument, configuration, or report-save failure |

Reports retain revision, tracked-file change status, model, settings, timings,
all case outcomes, token counts, digit coverage, and available failure metadata.
Observed client calls include attempts, duration, and whether text returned.
`score_result()` returns a summary, but `run_case()` adds content-bearing
`synthetic_evidence`: questions, conclusions, SQL, result cells, and claim details.
The CLI exports broader investigation content, including available repair history.
Neither format is content-free telemetry. Review reports before committing.

`tracked_changes` excludes untracked files and is not a full dependency or
fixture fingerprint. Older reports lack newer fields; absence is not zero.
`number_audit_summary` summarizes token diagnostics, not semantic verification
or complete digit coverage. Inspect each case's `narrative_digit_coverage`.

Retain failed runs. Separate completion, availability, numerical correctness,
and latency metrics. Report denominators and group comparable revisions and
settings. Known fixtures are not held-out generalization evidence. A successful
run with retries configured does not establish that a retry actually occurred;
use generation telemetry when available.

For a reproducible run, record the revision, fixture content or hashes, selected
population and output contract, model, budgets, retry settings, Python version,
OS, and relevant installed package versions. `python --version` and
`python -m pip freeze` help capture the environment; review that output for
machine-specific paths before publishing. The default live report records some
of these fields, not a complete environment or fixture fingerprint.

Loading, profiling, and preliminary CLI inspection are outside the shared
orchestration deadline. Runner case wall time includes setup and any supplied
SQL control. Per-attempt provider timeouts, retry delays, cleanup, and total
wall time are separate
measurements; a 60-second request limit is not a 60-second whole-case promise.

## Diagnostics and disclosure

Use safe diagnostics instead of raw provider exception text. Keep connectivity,
format validity, SQL execution, numerical support, and analytical correctness
separate. Do not infer a failure's cause from an SDK warning alone.

Token audits may miss unsupported number formats. Digit coverage flags unparsed
digit characters but does not interpret them. Number words remain outside the
coverage check, and `all_digits_parsed` does not certify a narrative.

Built-in generation requires disclosure permission and can send schema,
profiles, questions, and query results. Never send local datasets merely because
they exist in the working directory. Keep credentials, private datasets, raw
provider messages, and rejected responses out of diagnostic artifacts.
Full investigation results contain evidence and may be sensitive. In particular,
repair history can serialize failed and replacement SQL containing dataset values.
Do not treat query provenance as content-free telemetry or publish it without
review.

## Review and commit workflow

1. Inspect implementation and tests; define an observable change.
2. Implement and add regressions for concrete failure cases.
3. Run appropriate checks and update affected documentation.
4. Review the diff and explicitly stage intended files.
5. Inspect staged contents, commit, and check CI.

```powershell
git status --short
git diff --check
git diff --cached --check
git diff --cached --stat
git diff --cached --name-only
```

Do not use `git add .` when unrelated files or local datasets are present.
Do not stage `datasets/`. Avoid undated test-count badges and unsupported
completion percentages. See [Architecture](architecture.md) for current
contracts and [Roadmap](roadmap.md) for remaining acceptance work.