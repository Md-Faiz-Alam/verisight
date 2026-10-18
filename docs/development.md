
# VeriSight Development Guide

## 1. Purpose

This document defines the development workflow, engineering standards, testing requirements, and contribution practices for VeriSight.

VeriSight is a Python-based autonomous AI data analyst that combines deterministic data processing, controlled analytical SQL execution, and AI-assisted investigation.

The project has progressed beyond its initial ingestion and profiling foundation.

Its current implementation includes:

- Structured data ingestion
- Schema inference
- Deterministic profiling
- Data-quality analysis
- Structured analytical evidence
- DuckDB analytical execution
- SQL security validation
- Gemini-assisted query planning
- Bounded SQL repair
- Autonomous investigation
- Structured investigation decisions
- Prompt budgeting
- Generative synthesis
- Public Python workflows
- Structured public error reporting

The next major engineering objective is to establish measurable analytical correctness through evidence-linked claim verification and end-to-end acceptance evaluation.

This guide describes the existing development workflow. Planned functionality is explicitly identified as future work.

---

## 2. Engineering Principles

VeriSight development follows several principles.

### 2.1 Correctness Before Feature Expansion

New functionality must preserve existing domain contracts and tested behavior.

A feature should not be introduced merely because it appears on an outdated roadmap.

Before implementing a capability, determine whether it already exists and whether the actual problem is missing functionality, incomplete integration, or insufficient evaluation.

### 2.2 Deterministic Execution

Deterministic components should remain independent of generative model behavior wherever possible.

AI-generated SQL must pass through the established validation and controlled execution layers.

Generated analytical conclusions must not be treated as verified solely because their underlying SQL executed successfully.

### 2.3 Preserve Source Meaning

Dataset ingestion must avoid unnecessary or unsafe coercion.

Particular care is required for identifiers, leading-zero values, nullable columns, and integers that cannot be represented exactly by floating-point numbers.

An explicit loading failure is preferable to silent data corruption.

### 2.4 Stable Domain Contracts

Shared analytical concepts should have one canonical representation.

Avoid introducing parallel models for measurements, evidence, query results, or investigation observations without a demonstrated requirement.

Changes to public contracts require corresponding tests and documentation.

### 2.5 Security and Privacy

Do not weaken established query validation, dataset-access restrictions, or external data-disclosure controls.

Never commit secrets or private datasets.

Do not include raw credentials, sensitive dataset values, or provider exception details in public error messages.

### 2.6 Bounded Development

Each development increment should have:

1. A specific objective
2. An identified implementation boundary
3. Explicit acceptance criteria
4. Relevant regression tests
5. A complete quality-gate run
6. A reviewed Git diff
7. A coherent commit

Avoid indefinite investigation of speculative edge cases.

---

## 3. Development Environment

VeriSight requires Python 3.11 or newer.

The primary verified local environment is:

| Component | Environment |
| --- | --- |
| Operating system | Windows 11 |
| Shell | PowerShell |
| Python | 3.11.9 |
| Virtual environment | `.venv` |
| Repository directory | `F:\verisight` |
| Primary branch | `main` |
| Package layout | `src/verisight` |

The repository's Python requirement is defined in `pyproject.toml`.

### Core Technologies

The project uses:

- Python
- pandas
- NumPy
- DuckDB
- SQLGlot
- Pydantic
- pydantic-settings
- Google Gen AI SDK
- openpyxl
- xlrd

### Development Tools

The development toolchain includes:

- Ruff
- mypy
- pytest
- pytest-cov
- pandas-stubs

Dependency version constraints are maintained in `pyproject.toml`.

Do not independently change or relax these constraints without a specific compatibility requirement.

---

## 4. Environment Setup

### Windows PowerShell

From the repository root:

```powershell
cd F:\verisight

python -m venv .venv

.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip

python -m pip install -e ".[dev]"
```

After activation, PowerShell should normally display an environment prefix similar to:

```text
(.venv) PS F:\verisight>
```

### Verify the Environment

```powershell
python --version
python -m pip --version
ruff --version
mypy --version
pytest --version
```

### macOS and Linux

From the repository root:

```bash
python3 -m venv .venv

source .venv/bin/activate

python -m pip install --upgrade pip

python -m pip install -e ".[dev]"
```

The documented production verification baseline comes from Windows.

Other platforms should run the complete quality gate before being considered independently verified.

---

## 5. Repository Structure

The main repository structure is:

```text
verisight/
|
|-- src/
|   `-- verisight/
|       |-- analysis/
|       |-- execution/
|       |-- ingestion/
|       |-- profiling/
|       |-- quality/
|       |-- config.py
|       |-- error_reporting.py
|       |-- evidence.py
|       |-- exceptions.py
|       |-- logging.py
|       |-- public_api.py
|       |-- serialization.py
|       `-- service.py
|
|-- tests/
|
|-- docs/
|   |-- architecture.md
|   `-- development.md
|
|-- .env.example
|-- .gitignore
|-- LICENSE
|-- pyproject.toml
`-- README.md
```

The new `docs/roadmap.md` is part of the documentation-reconciliation milestone and will become the canonical roadmap once created.

### Package Responsibilities

| Location | Responsibility |
| --- | --- |
| `ingestion/` | File loading, validation, normalization, schema inference |
| `profiling/` | Deterministic dataset statistics |
| `quality/` | Structured data-quality checks |
| `analysis/` | Dataset analysis, summaries, insights |
| `execution/` | SQL execution, planning, repair, investigation, synthesis |
| `evidence.py` | Shared immutable evidence |
| `serialization.py` | JSON-compatible representations |
| `config.py` | Application configuration |
| `error_reporting.py` | Stable public error mapping |
| `logging.py` | Logging infrastructure |
| `public_api.py` | Public error and execution boundary helpers |
| `service.py` | High-level `VeriSight` facade |

Implementation details should be verified against the current source before modifying existing modules.

---

## 6. Configuration and Secrets

VeriSight uses Pydantic settings.

Application environment variables use the `VERISIGHT_` prefix.

The repository contains an `.env.example` file.

Create a local `.env` file to configure application settings.

### Gemini Configuration

A local configuration may include:

```dotenv
VERISIGHT_GEMINI_API_KEY=your-private-api-key
VERISIGHT_GEMINI_MODEL=your-supported-model
VERISIGHT_ALLOW_LLM_DATA_DISCLOSURE=true
```

The API key must never be committed or included in tests.

The existing settings implementation excludes the Gemini API key from ordinary settings representations and serialization.

### Data-Disclosure Permission

Credentials alone must not enable external data disclosure.

Default Gemini-backed analytical workflows require explicit permission through the relevant setting.

Enabling this permission means analytical context may be sent to the configured external model provider.

Only enable it when the dataset's privacy and usage requirements permit this disclosure.

### Secret-Handling Rules

- Never hardcode actual API keys.
- Never print complete settings objects containing secrets.
- Never include credentials in exception messages.
- Never publish `.env`.
- Never commit private datasets.
- Avoid logging untrusted provider exception details.
- Use synthetic credentials and synthetic datasets in automated tests.

The `.gitignore` file excludes `.env` and related secret files.

It does not automatically exclude every possible sensitive dataset location.

Developers must explicitly review staged files before committing.

---

## 7. Formatting

VeriSight uses Ruff's formatter.

Format the repository with:

```powershell
ruff format .
```

Check formatting without modifying files:

```powershell
ruff format --check .
```

The configured formatting style includes:

- Python 3.11 target
- Maximum line length of 88 characters
- Double-quoted strings
- Space indentation

Formatting must pass before a change is considered complete.

---

## 8. Linting

Run the complete Ruff lint check:

```powershell
ruff check .
```

The configured lint rule families are:

- `E`
- `F`
- `I`
- `UP`
- `B`
- `SIM`

These cover categories including Python style, correctness, import ordering, modernization, common bug patterns, and simplification.

### Fixing Import Ordering

For an import-order failure such as `I001`:

```powershell
ruff check --select I --fix path/to/file.py
```

Then rerun:

```powershell
ruff format .
ruff format --check .
ruff check .
```

### Automatic Fixes

Ruff can automatically fix supported violations:

```powershell
ruff check . --fix
```

Automatic fixes must still be reviewed.

Do not assume an automated edit is correct merely because linting passes afterward.

---

## 9. Static Type Checking

VeriSight uses mypy in strict mode.

The established command is:

```powershell
mypy src tests
```

Both production code and tests are checked.

The strict configuration is declared in `pyproject.toml`.

### Type-Safety Rules

- Prefer precise domain types.
- Avoid unnecessary `Any`.
- Avoid introducing casts solely to silence errors.
- Use explicit protocols for injected dependencies.
- Preserve frozen and immutable model contracts.
- Check nullable values before use.
- Validate untrusted input at public boundaries.
- Do not weaken strict mode to accommodate a new implementation.

When a type-checking error reveals disagreement between two components, investigate the underlying contract.

Type ignores should be narrowly justified and tested when used.

---

## 10. Automated Testing

VeriSight uses pytest.

Run the complete suite:

```powershell
pytest
```

For verbose output:

```powershell
pytest -v
```

### Focused Tests

During development, individual test modules may be executed:

```powershell
pytest tests/test_execution_gemini.py -v
```

Related tests may also be executed together:

```powershell
pytest tests/test_execution_gemini.py tests/test_service.py -v
```

Focused tests provide faster feedback.

They are not a substitute for the full quality gate before committing.

### Testing Categories

The current suite covers:

- Configuration
- Ingestion
- Schema inference
- Profiling
- Data quality
- Evidence
- Serialization
- Deterministic analysis
- Public interfaces
- DuckDB execution
- SQL validation
- SQL security restrictions
- Natural-language planning
- Gemini client behavior
- Provider failure handling
- Retry logic
- SQL repair
- Prompt construction
- Prompt budgeting
- Investigation decisions
- Autonomous orchestration
- Failed-attempt recovery
- Incomplete investigations
- Generative synthesis
- Public error reporting

### Regression Tests

A confirmed defect should receive a regression test.

Regression tests should reproduce the relevant failure and verify the corrected behavior.

For ingestion changes, test the actual source values and normalized results.

For execution changes, test permitted and rejected SQL.

For generative integration, use controlled responses to test deterministic software behavior.

For investigation changes, verify both successful and incomplete execution paths.

---

## 11. Coverage Requirements

VeriSight requires 100% statement and branch coverage according to the repository's configured coverage measurement.

Run:

```powershell
pytest --cov=verisight --cov-report=term-missing --cov-fail-under=100
```

Coverage configuration is defined in `pyproject.toml`.

### Coverage Standards

New production behavior should receive appropriate tests covering:

- Successful paths
- Failure paths
- Relevant boundary conditions
- Conditional branches
- Invalid inputs
- Public error behavior

Do not weaken production requirements merely to satisfy coverage.

Do not add meaningless tests that exercise code without validating behavior.

Do not exclude ordinary production code solely to preserve a coverage percentage.

### Interpreting Coverage

100% coverage means the configured statements and branches have been exercised.

It does not prove:

- Analytical answer correctness
- Correct SQL semantics
- Absence of hallucinations
- Security completeness
- Provider reliability
- Performance under load
- Production readiness

These require separate evaluation.

---

## 12. Established Complete Quality Gate

Before committing a completed code change, run exactly:

```powershell
ruff format .
ruff format --check .
ruff check .
mypy src tests
pytest --cov=verisight --cov-report=term-missing --cov-fail-under=100
```

All commands must pass.

This is the established project quality gate.

Do not substitute alternative coverage commands as the final milestone verification.

Alternative commands may be used for focused debugging, but the established gate remains authoritative for local development.

### Latest Verified Baseline

The Gemini structured-output implementation was verified on October 18, 2026.

| Measurement | Verified result |
| --- | --- |
| Python version | 3.11.9 |
| Tests | 1,357 passed |
| Statements | 2,339 |
| Missing statements | 0 |
| Branches | 604 |
| Partial branches | 0 |
| Coverage | 100.00% |
| Ruff formatting | Passed |
| Ruff linting | Passed |
| Mypy | Passed |

The corresponding implementation was committed and pushed as:

```text
f7685a8
feat: enable structured JSON for Gemini investigation
```

These results were obtained in the local Windows development environment.

They should not be represented as independent cross-platform verification.

---

## 13. Deterministic and Live Integration Tests

VeriSight distinguishes deterministic automated tests from external-provider validation.

### Deterministic Tests

Normal automated tests should not require a real Gemini API key.

Use mocks, stubs, or controlled generation responses to validate:

- Prompt construction
- Generation configuration
- Provider-error translation
- Response parsing
- Retry behavior
- Investigation decisions
- Query repair
- Synthesis orchestration

Deterministic tests should produce reproducible results without network access.

### Live Gemini Tests

Live tests verify interaction with the actual configured model and provider.

They may introduce:

- Network variability
- API quota consumption
- Usage charges
- Rate limiting
- Model-dependent behavior
- Provider outages

Live tests must not be required for the ordinary deterministic quality gate.

### Structured JSON Smoke Test

The October 18 development session verified a live request using the configured Gemini model.

The test used synthetic order amounts:

```text
10, 20, 30
```

The model returned a valid structured investigation decision.

VeriSight's parser accepted that response.

The observed action was:

```text
investigate
```

This confirms basic compatibility between:

1. The configured Gemini model
2. The JSON response schema
3. The Gemini text-generation client
4. The investigation response parser

It does not prove the correctness of a complete autonomous analytical investigation.

### Privacy Rules for Live Tests

Use synthetic data unless an explicitly authorized dataset is required.

Never print the API key.

Avoid printing raw provider exceptions that may include sensitive request context.

Do not upload local datasets merely to test response formatting.

---

## 14. Development Workflow

Every bounded development increment should follow the same sequence.

### Step 1 — Establish the Objective

Define what the increment must accomplish.

Identify the existing failure, requirement, or missing capability.

Avoid implementing speculative improvements without a demonstrated need.

### Step 2 — Inspect Existing Source

Review:

- Relevant production modules
- Domain models
- Related tests
- Downstream consumers
- Public interfaces
- Configuration
- Documentation

Do not invent new interfaces without verifying the existing design.

### Step 3 — Define Acceptance Criteria

Acceptance criteria should identify observable behavior.

Examples:

- An input is accepted or rejected correctly.
- A SQL query is validated before execution.
- A query result preserves exact values.
- An investigation is correctly marked incomplete.
- A generated response conforms to the expected schema.

### Step 4 — Implement the Smallest Coherent Change

Keep changes limited to the relevant responsibility.

Avoid unrelated refactoring.

Preserve backward compatibility unless a contract change is deliberate and documented.

### Step 5 — Add Regression Tests

Tests should cover both expected behavior and meaningful failure conditions.

Where existing behavior is intentionally changed, update all affected consumers.

### Step 6 — Run Focused Validation

Use focused Ruff, mypy, and pytest commands during implementation.

### Step 7 — Run the Complete Quality Gate

Run the established five-command quality gate.

Do not proceed to commit with failing formatting, linting, typing, tests, or coverage.

### Step 8 — Review Git Changes

Inspect both tracked modifications and untracked files.

### Step 9 — Commit and Push

Stage only the files belonging to the increment.

Use a concise descriptive commit message.

Push only after reviewing the staged diff.

### Step 10 — Return to the Roadmap

Record the increment as completed only after verification.

Then select the next bounded task from the canonical roadmap.

---

## 15. Git Workflow

### Check the Working Tree

```powershell
git status --short
```

### Check for Whitespace Problems

```powershell
git diff --check
```

### Review Changes

```powershell
git --no-pager diff --stat
git --no-pager diff
```

### Review a Specific File

```powershell
git --no-pager diff -- src/verisight/service.py
```

### Stage Explicit Files

Prefer explicit staging:

```powershell
git add src/verisight/service.py
git add tests/test_service.py
```

Do not use `git add .` when unrelated or private files exist.

### Inspect the Staged Diff

```powershell
git diff --cached --check
git diff --cached --stat
git --no-pager diff --cached
```

### Commit

Use a message reflecting the actual change.

For example:

```powershell
git commit -m "feat: enable structured JSON for Gemini investigation"
```

### Push

```powershell
git push origin main
```

### Confirm Status

```powershell
git status --short
```

An untracked local dataset directory may remain after a successful commit.

That does not mean the commit failed.

However, untracked datasets must be excluded from unintended staging.

---

## 16. Canonical Data Contracts

VeriSight uses explicit shared domain models.

Before introducing a new structure, determine whether the same information already exists.

Important contracts include:

- `LoadedDataset`
- `LoadedTable`
- `DatasetAnalysis`
- `DatasetAnalysisResult`
- `AnalysisSummary`
- `AnalysisInsight`
- `QueryPlan`
- `QueryResult`
- `QueryObservation`
- `InvestigationState`
- `InvestigationDecision`
- `InvestigationResult`

### Canonical Ownership

Source parsing belongs to ingestion.

Statistical measurements belong to profiling.

Data-quality findings belong to quality.

Dataset-level deterministic composition belongs to analysis.

SQL plans and query results belong to analytical execution.

Investigation observations and decisions belong to the investigation subsystem.

Shared structured evidence belongs to the established evidence contract.

Avoid maintaining multiple independent representations of the same analytical value.

---

## 17. Evidence Engineering

Shared structured evidence is defined in:

```text
src/verisight/evidence.py
```

Evidence is validated and recursively frozen.

Supported values include approved scalar types and nested evidence structures.

The contract rejects unsupported values rather than retaining arbitrary objects.

### Evidence Rules

- Preserve deterministic measurements.
- Avoid mutable shared evidence structures.
- Do not silently convert invalid evidence into plausible values.
- Keep evidence serialization separate from evidence construction.
- Reuse established evidence contracts.
- Preserve meaningful provenance.

### Query Observations

Autonomous investigation records executed analytical observations.

A `QueryObservation` includes:

- Analytical question
- Executed SQL
- Structured query result

These observations provide the evidence available to generative synthesis.

They are not equivalent to verified conclusion claims.

### Future Claim Verification

A future verification layer should reuse existing query observations and shared evidence contracts.

It should not create another unrelated evidence system.

---

## 18. Ingestion Engineering

Ingestion correctness is a core requirement.

The existing implementation supports CSV, Excel, and JSON.

### CSV

Pay particular attention to:

- Encodings
- Delimiters
- Quoted fields
- Missing values
- Large integers
- Leading-zero identifiers
- Numeric-looking strings
- Ambiguous source values

Avoid parsing values through floating-point representations when doing so can lose information.

### Excel

Preserve native values where possible.

Be careful with mixed-type columns and missing values.

Nullable integer handling must not introduce floating-point precision loss.

Excel's own storage and precision limitations must be distinguished from precision loss introduced by VeriSight.

### JSON

Preserve supported exact integer values.

Use appropriate nullable integer and boolean representations.

Do not silently convert unsupported JSON structures into misleading tables.

### Regression Expectations

When changing ingestion, include tests that compare source values with loaded values.

For SQL-facing values, test round-trip behavior when appropriate.

Silent corruption is a correctness failure even if loading succeeds.

---

## 19. Analytical SQL Engineering

The SQL execution system is a controlled analytical execution boundary.

Relevant production components include:

- `AnalyticalExecutionService`
- `DuckDBExecutor`
- `AnalyticalQueryValidator`
- `validate_dataset_relations()`

### SQL Rules

- Validate analytical SQL before execution.
- Restrict relation access to authorized dataset tables.
- Reject unsupported SQL constructs.
- Preserve configured execution limits.
- Avoid enabling arbitrary external access.
- Do not bypass relation validation during repair.
- Ensure repaired queries pass the same execution controls.

### Security Standards

The existing execution controls are defense-in-depth measures.

They do not constitute a complete operating-system sandbox.

Do not claim that arbitrary hostile SQL execution is completely isolated.

Additional deployment security work should follow a defined threat model.

### Security Regression Tests

A demonstrated vulnerability or security defect should receive a regression test.

Avoid reopening completed security milestones solely to accumulate speculative edge cases.

---

## 20. Generative AI Engineering

Generative components should remain separated from deterministic execution.

### Planning

The planner transforms an analytical request into a proposed query plan.

A query plan is not automatically executable or semantically correct.

### Gemini Client

The Gemini client handles:

- Model selection
- Provider communication
- Request timeouts
- Retries
- Response extraction
- Error translation
- Optional structured JSON configuration

### Structured Investigation Decisions

The investigator uses a defined JSON response schema.

Expected fields are:

- `action`
- `reasoning`
- `question`

The local parser remains authoritative for decision validation.

Structured output reduces formatting uncertainty.

It does not prove that the model's decision is analytically appropriate.

### Repair

SQL repair should remain bounded.

A repaired query must pass normal validation.

Do not introduce unlimited retries.

### Synthesis

Generative synthesis converts investigation evidence into a natural-language conclusion.

A well-formed conclusion is not necessarily correct.

Future verification should explicitly compare supported numerical claims with the observations used to justify them.

---

## 21. Autonomous Investigation Engineering

Autonomous investigation combines:

- Deterministic analysis
- AI planning
- Controlled SQL execution
- Investigation decisions
- Query observations
- Failure tracking
- Bounded recovery
- Generative synthesis

### Investigation Limits

Respect:

- Maximum step counts
- Duplicate-question detection
- Prompt budgets
- Query execution limits
- Resource restrictions

### Incomplete Results

Investigations must not manufacture a supported conclusion when required evidence is missing.

An incomplete result should preserve available observations and clearly communicate that a reliable conclusion was not established.

### Public Result Contract

The current `InvestigationResult` contains:

- `question`
- `conclusion`
- `analysis`
- `observations`
- `status`

Its status indicates whether the orchestration rules considered the investigation complete.

It is not a deterministic verification result for every claim.

The internal investigation state also contains failed-attempt information that is not fully exposed in this public result.

---

## 22. Public Error Handling

VeriSight uses domain-specific exceptions and a public error-reporting boundary.

The public boundary should distinguish known application failures from unexpected internal problems.

### Error Rules

- Prefer stable error codes.
- Provide safe public messages.
- Do not expose provider credentials.
- Do not expose sensitive dataset contents.
- Preserve meaningful distinction between input, configuration, query, and investigation failures.
- Avoid converting expected input errors into generic internal failures.

### Logging Rules

The existence of a logging module does not guarantee that all application operations are instrumented.

Logging must be introduced deliberately.

Do not log entire prompts, raw SQL, dataset rows, or provider exceptions without an explicit privacy and sanitization policy.

Structured operational logging should use safe metadata wherever possible.

---

## 23. Testing Analytical Correctness

Traditional unit and integration tests remain necessary.

However, they are not sufficient to establish autonomous analytical reliability.

Future acceptance evaluation should measure whether VeriSight answers realistic analytical questions correctly.

### Planned Evaluation Categories

- Exact row counts
- Sum and average calculations
- Filtered aggregations
- Rankings
- Group comparisons
- Percentages and ratios
- Time trends
- Missing-data handling
- Ambiguous questions
- Insufficient-evidence cases
- Failed SQL recovery
- Multi-step investigation

### Planned Metrics

- SQL semantic correctness
- Numerical answer correctness
- Evidence coverage
- Unsupported-claim rate
- Correct incomplete-result behavior
- Recovery success rate
- Claim-verification accuracy

### Evaluation Principles

Use datasets with known answers.

Distinguish execution success from answer correctness.

Distinguish evidence availability from evidence support.

Avoid evaluation that only checks whether a second language model agrees with the first.

The initial benchmark should be small enough to inspect individual failures.

---

## 24. Documentation Standards

Documentation must reflect the source.

The primary documents are:

- `README.md` — project overview and public usage
- `docs/architecture.md` — implemented architecture and boundaries
- `docs/development.md` — engineering workflow and standards
- `docs/roadmap.md` — canonical development roadmap once created

### Documentation Rules

1. Do not describe implemented features as future work.
2. Do not claim planned features are implemented.
3. Use exact current public interface names.
4. Keep quality-gate statistics dated or tied to a commit.
5. Explain meaningful security and privacy limitations.
6. Distinguish mocked tests from live-provider verification.
7. Describe analytical reliability honestly.
8. Update documentation when a public contract changes.

Documentation reconciliation should be completed as a bounded milestone.

---

## 25. Development Priorities

Following the Gemini structured-output milestone, the recommended sequence is:

### Priority 1 — Documentation Reconciliation

Bring README, architecture, development documentation, and the canonical roadmap into agreement with the implemented source.

### Priority 2 — Evidence-Linked Claim Verification

Design and implement a deterministic first version of analytical claim verification.

Focus initially on measurable numerical claims supported by explicit query observations.

### Priority 3 — End-to-End Analytical Evaluation

Create a small benchmark with known expected analytical answers.

Measure correctness and unsupported claims.

### Priority 4 — Fix Measured Failures

Improve planning, execution, investigation, evidence handling, or synthesis according to demonstrated benchmark failures.

### Priority 5 — Product Interfaces

Evaluate a CLI, HTTP API, reporting layer, visualization, or graphical interface after the analytical core has been evaluated.

These priorities are development recommendations, not invented official numbered phases.

---

## 26. Before Every Commit

Use this checklist:

```text
[ ] Objective and acceptance criteria are clear
[ ] Existing implementation was inspected
[ ] Public contracts are preserved or intentionally updated
[ ] Change is limited to the intended responsibility
[ ] Relevant regression tests exist
[ ] Ruff formatting passes
[ ] Ruff linting passes
[ ] Strict mypy passes
[ ] Complete pytest suite passes
[ ] Coverage meets the established 100% threshold
[ ] No secrets were added
[ ] No private datasets were staged
[ ] git diff --check passes
[ ] Staged files match the intended change
[ ] Documentation is updated where necessary
[ ] Commit message accurately describes the change
```

For documentation-only changes, production test results do not need to change, but the repository should still be reviewed for accuracy and unintended modifications.

---

## 27. Development Completion Criteria

A development increment is considered locally complete when:

1. Its acceptance criteria are satisfied.
2. Relevant tests have passed.
3. The established quality gate passes.
4. The final diff has been reviewed.
5. The appropriate documentation is updated.
6. The change is committed.
7. The intended Git push succeeds.

A successful commit does not establish production readiness.

A successful live provider test does not establish complete analytical correctness.

A 100% coverage report does not establish absence of defects.

These conclusions require separate evidence.

---

## 28. Project Direction

VeriSight has reached a stage where additional software hardening should be driven primarily by reproducible problems.

The engineering foundation includes deterministic analysis, guarded SQL execution, AI planning, repair, investigation, and synthesis.

The next major challenge is verifying that the analytical conclusions produced by these components are correct and supported by explicit evidence.

The intended progression is:

```text
Deterministic analytical foundation
                |
                v
Controlled SQL execution
                |
                v
AI-assisted investigation
                |
                v
Structured observations
                |
                v
Deterministic claim verification
                |
                v
Measured analytical correctness
                |
                v
Product interfaces and deployment
```

The first four stages have substantial implementations.

Claim verification and formal analytical evaluation remain planned work.

Future development should preserve the existing engineering standards while shifting the project's success criterion from component completeness toward demonstrable analytical reliability.
