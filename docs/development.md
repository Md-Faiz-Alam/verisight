# VeriSight development guide

## Setup

Use Python 3.11 or newer.

From the repository root in Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

On macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

Dependencies and tool configuration are defined in `pyproject.toml`.

## Repository responsibilities

| Location | Responsibility |
| --- | --- |
| `src/verisight/ingestion/` | File validation, loading, and schema handling |
| `src/verisight/execution/` | SQL, provider integration, investigation, and verification |
| `src/verisight/service.py` | Public Python facade |
| `src/verisight/error_reporting.py` | Safe public error classification |
| `src/verisight/public_api.py` | Framework-independent operation boundary |
| `tests/` | Automated regression and benchmark tests |
| `scripts/` | Development evaluation utilities |
| `docs/` | Architecture, development guidance, and roadmap |

The `scripts` package is used from the repository root. It is not included by
the current `src` package discovery configuration.

## Required quality gate

Run from the repository root:

```powershell
ruff format .
ruff format --check .
ruff check .
mypy src tests scripts
python -m pytest --cov=verisight --cov=scripts --cov-report=term-missing --cov-fail-under=100
git diff --check
```

The project configures strict mypy checking and branch coverage.

Include `scripts` explicitly in type checking and coverage. The default
configuration alone does not cover that entire development surface.

Use focused tests while changing behavior, then run the complete gate for
runtime changes.

Documentation-only changes require checking accuracy, examples, links, and the
diff. They do not require inventing tests solely to exercise documentation.

## Test design

Use synthetic inputs and deterministic substitutes for external generation.

Tests should establish behavior that matters:

- Source-value preservation.
- Correct input validation.
- SQL validation and resource-limit handling.
- Known analytical answers.
- Safe failure classification.
- Evidence retention.
- Numerical comparison boundaries.
- Serialization and secret exclusion.

Do not treat 100% coverage as proof of analytical correctness.

Extend an existing relevant test file when practical. Create a new test module
when it represents a distinct responsibility.

## Numerical verification contracts

The current verifier supports `value` and `difference`.

Generated claims identify observation rows and named columns. Structured
generation requires decimal strings and does not accept a model-selected
tolerance.

Preserve these distinctions:

- Numerical support versus analytical correctness.
- Workflow completion versus answer correctness.
- No submitted claims versus justified abstention.
- Unverifiable evidence versus contradicted evidence.
- Exact comparison versus a future rounded presentation policy.

The fixed result fields are:

```text
narrative_verified = False
verification_scope = referenced_numeric_values_only
```

Changes to this contract require implementation, regression tests, and matching
documentation updates.

## Deterministic benchmark

Run:

```powershell
python -m pytest tests/test_verification_benchmark.py -q
```

The benchmark includes five-domain numerical scenarios and adversarial SQL
examples.

Expected answers must be independent of the generated SQL and submitted claims.
Otherwise a wrong query can become its own correctness oracle.

The adversarial cases deliberately demonstrate that a supported claim can repeat
the result of an analytically wrong query.

## Live evaluation

Configure the API key locally, then run:

```powershell
python -m scripts.live_evaluation --live --case finance
```

To run all current synthetic cases:

```powershell
python -m scripts.live_evaluation --live --case all
```

The evaluator creates temporary synthetic files and explicitly enables provider
disclosure for those fixtures.

Its current settings include:

- One analytical step per case.
- Zero application provider retries.
- A 20-second provider request timeout.
- A five-second SQL execution limit.
- At most 20 query result rows.

One analytical step may involve multiple provider requests.

The script prints a JSON report. Exit codes are:

| Code | Meaning |
| --- | --- |
| `0` | Every selected case received `correct_numeric` |
| `1` | At least one case had another outcome |
| `2` | Argument or configuration failure |

Do not silently discard failed runs. Provider errors, missing claims, incomplete
investigations, and incorrect answers are part of evaluation evidence.

Current fixtures are development cases, not a held-out benchmark.

## Provider troubleshooting

Use safe diagnostic fields instead of raw exception text:

- HTTP status.
- Retryability.
- Attempt count.
- Stage.
- Per-client call number.

Keep transport failures separate from response-format failures and analytical
errors.

A connectivity test that returns text establishes only that that request
succeeded. It does not establish successful SQL planning, synthesis, or numerical
correctness.

Do not change timeouts or retry counts without recording the changed settings.
Do not interpret an SDK warning as the cause of a failure without evidence.

## Security and disclosure

Keep credentials out of commits, examples, logs, and evaluation artifacts.

Built-in generation requires disclosure permission. Prompts can contain schema,
profiling context, questions, and query results.

Use synthetic data for ordinary tests and live development fixtures.
Do not send local datasets to a provider merely because they exist in the
working directory.

The API key is excluded from normal Settings serialization. This is not a
guarantee against every possible way application code could expose a string.

Treat dataset text and model output as untrusted inputs.

## Development workflow

1. Inspect the current implementation and existing tests.
2. Define a small observable behavior change.
3. Implement it using existing public contracts where possible.
4. Add regression tests for the concrete failure.
5. Run focused checks and the appropriate quality gate.
6. Update documentation when behavior or limitations change.
7. Review the complete diff.
8. Stage only the intended files.

Use explicit paths when staging. Do not use `git add .` for routine milestones
when local datasets or unrelated files are present.

Before committing:

```powershell
git status --short
git diff --check
git diff --cached --check
git diff --cached --stat
git diff --cached --name-only
```

Inspect staged contents, not only their filenames.

## Documentation maintenance

Update documentation when changing:

- Public methods or result contracts.
- Verification scope and verdicts.
- Error classification.
- Provider diagnostics or retries.
- Evaluation fixtures, metrics, or commands.
- Installation and deployment behavior.

Avoid undated test-count badges or unsupported readiness percentages.
Separate implemented behavior from proposed work.

## Current engineering priorities

1. Preserve evidence when synthesis or provider generation fails.
2. Expose structured failure provenance.
3. Link report statements to numerical claims.
4. Define application-controlled rounding behavior.
5. Expand independent evaluations and retain reproducible results.
6. Resolve remaining ingestion and prompt-contract gaps.
7. Add continuous integration.

There is no committed CI workflow in the reviewed project snapshot.
Local gates remain necessary until automated CI is implemented.
