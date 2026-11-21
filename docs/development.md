# VeriSight development guide

## Setup and repository layout

Use Python 3.11 or newer; development uses 3.13. CI tests Python 3.11 and 3.13 on
Windows and Linux.

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
| `src/verisight/ingestion/` | File validation, loaders, cleaning and schema inference |
| `src/verisight/profiling/` | Column, table and dataset statistics |
| `src/verisight/quality/` | Data-quality findings, including total rows |
| `src/verisight/analysis/` | The combined profile result: schema, statistics, findings, summary |
| `src/verisight/dashboards/` | Charts, row pages and subject detection, computed without a model |
| `src/verisight/execution/` | SQL safety and execution, generation, investigation, verification and trust |
| `src/verisight/web/` | The website: FastAPI app, upload store and the built frontend |
| `src/verisight/facade.py` | Public Python facade |
| `src/verisight/cli.py` | Local profile, preview, investigation, and export workflow |
| `src/verisight/error_reporting.py` | Fixed public error classification |
| `src/verisight/safe_operation.py` | Runs an operation and turns any failure into a safe public report |
| `tests/` | Offline regression and development benchmark tests |
| `scripts/` | Live evaluation on synthetic data, and recording or replaying model responses |
| `evaluation/` | Evaluation runners, the public benchmark and held-out sets |
| `evaluation/compare/` | The runner that compares plain Gemini, number checks and full VeriSight |
| `.github/workflows/ci.yml` | Automated quality gates |
| `.github/workflows/codeql.yml` | CodeQL security scanning of Python, TypeScript and the workflows |
| `.github/dependabot.yml` | Weekly dependency update pull requests |
| `.github/workflows/image.yml` | After CI passes on `main`, publishes the website image to `ghcr.io` and deploys it to Azure, rolling back if it is unhealthy |

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

The website's tests run in `frontend/`. The browser tests start a Vite server and
stub every API call, so they need no Python server and no Gemini key. After
changing the interface, rebuild it and commit `src/verisight/web/static`:

```powershell
npm test
npm run test:e2e
npm run build
```

Peak memory under a full local workload, with scripted replies and generated data,
is measured with `python evaluation\measure_memory.py --out <new file>.json`.

Include `scripts` explicitly in mypy and coverage commands. The project enables
branch coverage. Full coverage is an engineering gate, not proof of analytical
correctness.

The quality matrix runs formatting, lint, strict mypy, full offline coverage,
and whitespace checks on Python 3.11 and 3.13 with `ubuntu-latest` and
`windows-latest`.
These jobs install the editable project and resolve dependencies within the
ranges in `pyproject.toml`. Each has a 15-minute limit.

A separate Windows AMD64 job uses CPython 3.13.17 and the committed
`requirements-dev-windows-py313.txt` snapshot. It has a 20-minute limit and:

1. Creates a separate virtual environment and installs the snapshot.
2. Installs the editable project without resolving dependencies or isolating the
   build, then checks dependency compatibility.
3. Runs formatting, lint, strict mypy, and the full offline coverage gate using
   the snapshot tools.
4. Builds the project wheel using the snapshot build tools, without dependency
   resolution or an isolated build environment.
5. Creates another virtual environment and installs that wheel with its runtime
   dependencies constrained by the snapshot. It does not install the full
   development snapshot into this runtime environment.
6. From outside the checkout, checks that the package imports from the runtime
   environment and includes `py.typed`, executes synthetic SQL, and invokes the
   installed `verisight` launcher for offline profiling.

The wheel check uses Python isolated mode for its test driver and removes
`PYTHONPATH` and `PYTHONHOME` from the launcher's environment. It is a packaging
smoke test, not the full test suite against the installed wheel. The full suite
continues to run against editable installs. No generation or live evaluation is
requested by these checks.

CI triggers on pushes to `main`, pull requests, and manual dispatch. Jobs fail
independently and use read-only repository permissions, pinned action commits,
and no provider credentials. The snapshot job supplements the dependency-range
matrix; it does not replace it.

The snapshot records versions for one platform and interpreter. It is not a
cross-platform dependency lock or a hash-verified package archive. Record installed
versions when investigating differences between local and hosted runs.

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

### Public benchmark

`evaluation/benchmark/` holds a benchmark anyone can rerun: 30 questions over
five generated domains (hospital visits, retail orders joined to customers,
factory runs, school scores and weather readings) in JSON, CSV, Excel, TSV and
JSONL, with 20 answerable, 5 ambiguous and 5 unanswerable questions. The files
keep real flaws: currency text, thousands separators, mixed-case labels and
missing values. `make_benchmark.py` writes everything from a fixed seed and
works out each expected answer in plain Python from the generated records, not
from the files. `tests/test_benchmark.py` checks that the committed files are
exactly what the generator writes and that hand-written SQL, run through
VeriSight's loader, reaches every expected answer.

```powershell
python evaluation\benchmark\make_benchmark.py
python evaluation\compare\run_comparison.py --root evaluation\benchmark --freeze
```

Then run each setup with `--run` and summarize with `--report`, as for the other
comparisons. Live runs call Gemini. Because these questions are public, never
change prompts, rules or code to pass one of them; report every run as it came,
and treat this set as a regression check rather than an unseen held-out test.
The runner keeps any answer that failed the claim checks in `rejected/<setup>/`
inside the run folder, so a miss can be explained afterwards; like the run folder,
it can hold data values and stays out of Git. Each attempt's record also has a
`call_log`: the stage, attempts, seconds, whether text came back and the tokens of
every model call, with no prompt or response, so a run that hits its time limit
shows which call stalled.

### Held-out set v4

`evaluation/heldout_v4/` holds 30 new questions written after the public
benchmark's first live run, to measure the changes that run led to on questions
nothing was tuned against. Its five domains (shipments with carriers and item
lines, football matches, energy meter readings, library loans and insurance claims)
in CSV, JSON, Excel, TSV and JSONL share no file or question with the public
benchmark. It has 20 answerable, 5 ambiguous and 5 unanswerable questions, and the
answerable ones carry the usual traps: a join whose item lines repeat shipments,
label spellings, values missing as N/A or null, month windows, a median, distinct
counts, percentages and signed differences. Each trap was checked to change the
number when the query falls for it.

`make_heldout_v4.py` writes everything from a fixed seed and works out each answer
in plain Python from the generated records; `tests/test_heldout_v4.py` checks that
hand-written SQL reaches every answer through VeriSight's loader. Of the five
undefined words in the ambiguous questions, two (heavy, frequent) are on the SQL
audit's list of vague words and three (exciting, a lot, unusually costly) are not.

The rules for this set: VeriSight is not run on these questions before the first
live run, which is frozen and reported in full, failures included; no prompt, rule
or code is changed to pass them; and once that run is published, the set becomes a
regression check like the public benchmark. Run it the same way, with
`--root evaluation\heldout_v4` copied to a folder Git ignores, as with the
benchmark.

### Replayed model responses

`tests/replays/` holds model responses replayed through the real pipeline in CI:
planning, SQL, claim checks, the audit, the second query and the trust level, with
no network call. A change after the model that alters an answer's outcome fails
`tests/test_replays.py`. Each file stores a SHA-256 hash of every prompt; when a
prompt changes, the replay still runs but warns that it is stale, and it should be
recorded again.

The first four files are hand-written, marked `"source": "hand-written"`, and use
the public benchmark data: a verified join, a reworded repeat that stays a number
match, a percentage claimed from two cells, and a question the data cannot answer.
Four more, named `recorded_*`, are real Gemini responses to the same benchmark
questions, recorded with `gemini-3.1-flash-lite` and `gemini-3.5-flash-lite` for
the second query. Each file names both models, because a separate model for the
second query changes the trust level, and a replay uses the same pair. Record
more when a live run is acceptable:

```powershell
python -m scripts.replay check tests/replays
python -m scripts.replay record --data-dir evaluation/benchmark/data --file visits.json --question "How many visits were to the Cardiology department?" --out tests/replays/cardiology.json --allow-llm-data-disclosure
```

Recording calls Gemini with `VERISIGHT_GEMINI_API_KEY`. A replay shows that the
pipeline still handles these responses the same way; it does not measure how good
new prompts are, which needs live runs.

### Offline development benchmark

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

### Retained evaluation batches

Use the existing runner as the maintained entry point for its five default and
three challenge cases. To retain artifacts, replace `--output` with
`--artifacts` pointing to a new directory whose parent already exists:

```powershell
New-Item -ItemType Directory -Force reports/evaluations | Out-Null
$evaluationStamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
python -m scripts.live_evaluation --live --case all --request-timeout-seconds 30 --provider-retries 1 --artifacts "reports/evaluations/batch-$evaluationStamp"
```

Run only after committing the runner and intended implementation changes.
Artifact mode requires a known Git revision with no tracked changes. Untracked
files are not part of that check and are never selected as fixtures.
`--case challenge` selects the three challenge cases instead of the five
defaults. Existing commands without `--artifacts` retain temporary-input behavior.

Before generation, the batch writes `manifest.json` with ordered cases,
questions, fixture content and UTF-8 LF hashes, independent answers, supplied
control SQL, settings, repository revision, runner hash, and allowlisted
dependency versions. Answers and control SQL remain evaluation metadata;
generation receives the same question and evidence as the existing runner.
Versions are observations, not a dependency lock or proof that an installed
package matches the repository revision.

Each case directory retains its synthetic inputs and `started.json`. A returned
investigation, including an incomplete one or a supported wrong answer, is
serialized unchanged to `investigation.json`; its byte hash is recorded in
`result.json`. Early failures retain available inputs and their classified
result without inventing an investigation export. Provider failures and
incomplete results do not trigger whole-case retries or prevent later cases
from being attempted.

The completed batch writes `summary.json` and prints that same report. Existing
numeric scoring and exit codes are unchanged. The runner does not invoke the
optional claim output gate or certify analytical task acceptance.

Existing directories, dangling symlinks, and combining `--artifacts` with
`--output` are rejected. Files are created without overwriting earlier artifacts.
Preparation errors stop before any case starts; case-artifact write errors stop
the batch. Interrupted or failed writes may leave partial files. A start record
without a result is unfinished, and absence of an export is not zero calls,
a justified abstention, or a completed evaluation. There is no resume mode;
preserve partial directories and use a separate identifier for any later batch.

This is the existing Python-facade evaluation path, not an installed-CLI
subprocess test. It does not implement ordered DIFFERENCE tasks or
justified-abstention scoring. It adds no provider
calls and does not recover old temporary artifacts. Retained files contain
synthetic questions, source values, SQL, and conclusions; review them before
committing. No credentials or arbitrary environment dump are included by the
new manifest.

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

`run_public_operation()` retains optional `provider_diagnostics` separately from
its unchanged public error code and message. The CLI includes this field in
operation-error exports only when valid provider metadata is available. It
contains HTTP status (or null), retryability, attempt count, generation stage,
and per-client call number. Only explicit exception causes are followed;
incidental exception context and malformed metadata are not exported. Raw
exception messages, tracebacks, requests, prompts, and responses are omitted.
A null HTTP status does not distinguish timeout from other transport failures.
Missing diagnostics mean unavailable metadata, not zero calls or no failure.
This export adds no retry or generation call and does not recover diagnostics
that an earlier wrapper discarded. Returned incomplete investigations retain
their existing nested failure metadata.

Token audits may miss unsupported number formats. Digit coverage flags unparsed
digit characters but does not interpret them. Number words remain outside the
coverage check, and `all_digits_parsed` does not certify a narrative.

Built-in generation requires disclosure permission and can send schema,
profiles, questions, query results, and bounded observed categorical values
used by SQL planning and repair. Those categorical values come from the original
loaded data before caller-selected population filters and can contain raw
identifiers or other sensitive strings. They are not automatically redacted.
Population filters restrict analytical query relations; they do not redact model
context. Original-data profiles can also describe excluded rows.

Never send local datasets merely because they exist in the working directory.
Keep credentials, private datasets, raw provider messages, and rejected responses
out of diagnostic artifacts.
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

### Tested Windows Python 3.13 environment snapshot

`requirements-dev-windows-py313.txt` records every package version installed by
`pip install -e ".[dev]"` on Windows AMD64 with CPython 3.13.17, build tools
included. With it, ruff, strict mypy and all 4,108 tests passed with 100%
statement and branch coverage. It replaced an earlier CPython 3.11.9 snapshot with
the same packages.

This development snapshot includes transitive dependencies and build/test
tools. It is not a minimal dependency specification, a cross-platform lock,
or a hash-verified package archive. Version pins do not guarantee continued
package availability or artifact integrity. Supported dependency ranges
remain in `pyproject.toml`.

From the repository root, replay with Windows AMD64 and CPython 3.13.17:

    $replayEnvironment = Join-Path $env:TEMP (
        "verisight-replay-" + [guid]::NewGuid().ToString("N")
    )

    py -3.13 -m venv $replayEnvironment
    if ($LASTEXITCODE -ne 0) { throw "Environment creation failed." }

    $replayPython = Join-Path $replayEnvironment "Scripts/python.exe"

    & $replayPython -c "import platform; assert platform.python_version() == '3.13.17'; assert platform.system() == 'Windows'; assert platform.machine() == 'AMD64'"
    if ($LASTEXITCODE -ne 0) { throw "Unexpected Python or platform." }

    & $replayPython -m pip install -r requirements-dev-windows-py313.txt
    if ($LASTEXITCODE -ne 0) { throw "Snapshot installation failed." }

    & $replayPython -m pip install --no-deps --no-build-isolation -e .
    if ($LASTEXITCODE -ne 0) { throw "Project installation failed." }

    & $replayPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw "Dependency check failed." }

Run the documented development gates with `$replayPython`.
Editable installation imports this checkout; it does not independently
validate an installed wheel. The historical result applies to the recorded
revision. Later source or dependency changes require validation before
claiming equivalent behavior. No live model calls are needed.

### Behaviour changes in pandas 3, DuckDB 2 and sqlglot 30

Each upgrade was made on its own, and the audit corpus, damaged-file suite,
benchmarks and replays pass unchanged after each one.

- **pandas 3** gives text its own `str` dtype from `read_csv(dtype=str)`,
  `pd.Series` of strings and `infer_objects()`. Such columns skip every
  `dtype == object` path (cleaning, totals, exact decimal binding) and change
  `physical_dtype` in prompts. Loaders keep text in object columns:
  `ingestion/dtypes.py` wraps `infer_objects`. pandas 3 also parses dates at
  microsecond resolution and accepts years before 1677; dates stay at
  `datetime64[ns]` with the old range, and Excel dates outside it stay as
  objects. It needs numpy 2.0.2 or newer, and no longer needs `pytz`.
- **DuckDB 2** reports `PRAGMA` as its own statement type, where 1.x rewrote it
  into a `SELECT`. The PRAGMA check now runs before the statement-type check, so
  the error stays specific. Decimals, result limits and memory settings behave
  as before.
- **sqlglot 30** adds `exp.Expr` as the root node class. Functions and
  conditions no longer inherit from `exp.Expression`, so
  `find_all(exp.Expression)` and `isinstance(node, exp.Expression)` silently
  skip them; the code uses `exp.Expr`. `version()` now parses as
  `exp.CurrentVersion` rather than `exp.Anonymous` and is blocked by class.
  `parse_one` takes `ErrorLevel.RAISE` instead of the string `"RAISE"`.