
# VeriSight

**Autonomous AI Data Analyst — a Python analytical engine built around deterministic execution, controlled AI investigation, and traceable evidence.**

VeriSight ingests structured datasets, interprets schemas, profiles data, identifies quality issues, executes analytical SQL, and supports AI-assisted investigations.

The project's central design principle is:

> AI may plan and interpret analytical work, but deterministic components must validate and execute its queries.

VeriSight is under active development. Its analytical engine is implemented, but real-world analytical reliability and deterministic verification of generated conclusions are not yet established.

## Project Status

VeriSight is currently an advanced engineering prototype and Python library.

### Implemented

- CSV, Excel, and JSON ingestion
- File validation and conservative type inference
- Dataset and SQL-relation normalization
- Schema inference
- Numeric, text, and datetime profiling
- Missing-value and duplicate analysis
- Deterministic data-quality findings
- Structured summaries and analytical insights
- Immutable evidence models
- DuckDB analytical SQL execution
- SQL validation and registered-dataset access restrictions
- Query resource and result limits
- Gemini-assisted natural-language query planning
- Bounded SQL repair
- Autonomous investigation orchestration
- Investigation decisions using structured JSON output
- Evidence-bearing query observations
- Prompt budgeting and context management
- Generative analytical synthesis
- Complete and incomplete investigation statuses
- Public Python facade
- Automated regression and integration tests

### Not yet established or implemented

- Deterministic verification of claims in generated conclusions
- Structured claim-to-observation references in final conclusions
- A benchmark demonstrating analytical correctness across representative tasks
- Comprehensive real-provider end-to-end evaluation
- A public command-line interface
- An HTTP API
- An interactive user interface
- A reporting or visualization product

**Important:** Having evidence-bearing observations does not guarantee that every statement in a generated conclusion is supported by those observations.

## Requirements

- Python 3.11 or newer
- Supported operating system for the project dependencies
- Gemini API credentials for default AI-assisted workflows
- Explicit permission to disclose analytical context to an external LLM

Deterministic dataset analysis and direct SQL execution do not require Gemini credentials.

## Installation

Clone the repository:

```powershell
git clone https://github.com/Md-Faiz-Alam/verisight.git
cd verisight
```

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

The development dependencies include pytest, pytest-cov, Ruff, mypy, and pandas type stubs.

## Python API

The public facade exposes four primary operations:

| Operation | Purpose | Gemini required by default? |
| --- | --- | --- |
| `analyze()` | Deterministic profiling, quality analysis, summaries, and insights | No |
| `execute()` | Execute validated analytical SQL against loaded data | No |
| `ask()` | Generate and execute SQL from a natural-language question | Yes |
| `investigate()` | Run a bounded autonomous analytical investigation | Yes |

Custom planner, investigator, repairer, and synthesizer components can be supplied through dependency injection where supported.

### 1. Analyze a dataset

```python
from verisight import VeriSight

result = VeriSight().analyze("data/orders.csv")

print(result.summary)
print(result.insights)
```

The result is a `DatasetAnalysisResult`.

It provides access to deterministic dataset analysis, structured summaries, insights, and quality findings.

### 2. Execute analytical SQL

```python
from verisight import VeriSight

result = VeriSight().execute(
    "data/orders.csv",
    """
    SELECT
        COUNT(*) AS order_count
    FROM orders
    """,
)

print(result.columns)
print(result.rows)
```

The source file `orders.csv` is registered under the normalized SQL relation name `orders`.

SQL is validated before execution. Queries are restricted to supported analytical constructs and authorized dataset relations.

### 3. Ask a natural-language question

```python
from verisight import VeriSight

result = VeriSight().ask(
    "data/orders.csv",
    "How many orders are in the dataset?",
)

print(result.columns)
print(result.rows)
```

With the default configuration, `ask()` requires a configured Gemini provider and explicit LLM data-disclosure permission.

The AI generates an analytical query. VeriSight then validates and executes it through its controlled SQL engine.

Successful execution is not proof that the generated SQL correctly interpreted the user's question.

### 4. Run an autonomous investigation

```python
from verisight import VeriSight

result = VeriSight().investigate(
    "data/orders.csv",
    "Investigate the distribution of order amounts.",
    max_steps=5,
)

print(result.status)
print(result.conclusion)

for observation in result.observations:
    print(observation.question)
    print(observation.sql)
    print(observation.result.columns)
    print(observation.result.rows)
```

An investigation can plan analytical questions, execute queries, collect observations, and generate a conclusion.

Investigation execution is bounded. The orchestration layer includes checks for repeated questions, unsuccessful queries, and incomplete investigations.

The returned `InvestigationResult` includes:

- `question`
- `conclusion`
- `analysis`
- `observations`
- `status`

It also exposes `observation_count`.

The `status` is either `complete` or `incomplete`.

An `incomplete` result must not be interpreted as a verified analytical conclusion.

The public result does not yet expose complete repair history or structured verification results for each claim.

## Gemini Configuration

VeriSight uses the Google Gen AI SDK.

Configuration is loaded through `Settings`, using environment variables prefixed with `VERISIGHT_`.

Create a local `.env` file based on `.env.example`.

For example:

```dotenv
VERISIGHT_GEMINI_API_KEY=your-api-key
VERISIGHT_GEMINI_MODEL=your-supported-model
VERISIGHT_ALLOW_LLM_DATA_DISCLOSURE=true
```

Use a Gemini model available to your API account.

Never commit a real API key, disclose it in an issue, or include it in test fixtures.

### Data-disclosure permission

Setting an API key alone does not authorize AI-assisted access to dataset context.

The default Gemini workflows also require:

```dotenv
VERISIGHT_ALLOW_LLM_DATA_DISCLOSURE=true
```

Enable this only for datasets whose analytical context may be sent to the configured external model provider.

VeriSight should not be treated as a guarantee that sensitive or regulated data remains local when external generation is enabled.

### Structured investigation output

The Gemini-backed investigator requests JSON responses using a defined decision schema.

Its decisions contain:

- `action`: `investigate` or `finish`
- `reasoning`: a string
- `question`: a string or `null`

VeriSight applies its own response validation after receiving the model output.

SQL planning, SQL repair, and narrative synthesis continue to use text generation rather than the investigator's JSON response schema.

## Supported Data Sources

### CSV

CSV ingestion supports:

- Comma, semicolon, tab, and pipe delimiter detection
- Quoted fields
- UTF-8 and UTF-8 with BOM
- UTF-16 with recognized BOM
- Windows-1252 and Latin-1 fallbacks
- Missing-value handling
- Conservative inference of numeric and boolean values
- Preservation of significant leading-zero identifiers
- Protection against unsafe large-integer coercion

Unsupported or ambiguous input may be rejected rather than silently reinterpreted.

### Excel

Excel ingestion supports workbook formats handled by the configured `openpyxl` and `xlrd` dependencies.

Workbook sheets are represented as tables.

The ingestion layer uses conservative handling for text, native values, missing values, and large integers.

Excel's own numeric-storage limitations still apply. VeriSight cannot reconstruct digits already lost when a workbook was created.

### JSON

JSON ingestion normalizes supported JSON records into tables.

The loader includes handling for:

- Integral values
- Large and unsigned integers
- Nullable integers
- Nullable booleans
- Mixed values where safe coercion would lose precision

Unsupported JSON structures may produce explicit loading errors.

## Dataset Normalization

VeriSight represents supported source data as a collection of tables.

Each table has a display name and a normalized relation name used for SQL execution.

For example, repeated normalized names may become:

```text
sales
sales_2
sales_3
```

Normalization provides consistent identities across ingestion, profiling, and query execution.

The set of reserved relation names is defined by the implementation and is not a universal SQL-keyword catalog.

## Deterministic Profiling

Profiling operates on inferred logical schemas.

Supported measurements include:

- Row and column counts
- Non-missing and missing counts
- Distinct counts and ratios
- Numeric minimum, maximum, mean, median, and standard deviation
- Text length and frequency statistics
- Datetime ranges and spans
- Missing-value patterns
- Duplicate rows and duplicate groups

These measurements form part of the evidence available to downstream analytical components.

## Data-Quality Analysis

Deterministic quality checks identify issues such as:

- Missing values
- Entirely missing columns
- Fully missing rows
- Duplicate rows
- Empty strings
- Constant columns
- High-cardinality columns

Findings contain structured metadata, including severity, affected scope, counts, ratios, and supporting evidence where applicable.

## Analytical SQL Execution

VeriSight uses DuckDB for analytical SQL execution.

The execution subsystem includes:

- Read-only analytical query validation
- Registered-dataset relation restrictions
- SQLGlot-based relation analysis
- Explicit handling of supported SQL constructs
- Rejection of unauthorized SQL sources
- External-access restrictions
- Disabled automatic extension installation and loading
- Configurable memory and execution limits
- Result-row limits
- Query execution error handling

These controls provide defense in depth.

They are not a guarantee of complete isolation against every hostile SQL input, resource-exhaustion scenario, or future engine vulnerability.

A separate threat model and isolation assessment would be required before deployment into a hostile multi-user environment.

## AI-Assisted Analytical Workflow

The implemented analytical workflow consists of several components:

```text
Input datasets
      |
      v
Ingestion and schema inference
      |
      v
Profiling and quality analysis
      |
      v
Analytical question
      |
      v
AI query planning
      |
      v
SQL validation and controlled execution
      |
      v
Query observations
      |
      v
Bounded investigation and recovery
      |
      v
Evidence-aware synthesis
      |
      v
InvestigationResult
```

AI-generated SQL is not executed without passing the applicable validation and execution controls.

The investigation system includes bounded steps, failure handling, duplicate-question detection, and prompt-budget controls.

The generative conclusion is not yet subjected to a separate deterministic claim-verification stage.

## Evidence and Serialization

VeriSight defines shared structured evidence contracts.

Evidence can contain supported scalar values and nested collections.

It is normalized and frozen to prevent unintended mutation.

Serialization provides JSON-compatible representations of supported domain models.

Analytical query observations retain the associated question, executed SQL, and structured result.

At present, the public investigation conclusion remains free-form text rather than a collection of individually verified claims.

## Error Handling

VeriSight uses domain-specific exceptions and a public error-reporting boundary.

Errors may represent:

- Invalid or unsupported inputs
- Dataset loading problems
- Configuration problems
- Query validation failures
- Query execution failures
- Prompt-budget failures
- Investigation failures
- Unexpected internal failures

Public error reporting is designed to avoid exposing sensitive provider details through ordinary error messages.

Error codes should be interpreted according to the implemented public error contract.

## Engineering Quality

The project uses:

- Ruff formatting
- Ruff linting
- Strict mypy checking
- Pytest
- Statement and branch coverage

The established quality gate is:

```powershell
ruff format .
ruff format --check .
ruff check .
mypy src tests
pytest --cov=verisight --cov-report=term-missing --cov-fail-under=100
```

### Latest verified local baseline

The quality gate reported for the Gemini structured-output commit:

| Measurement | Result |
| --- | --- |
| Python | 3.11.9 |
| Tests | 1,357 passed |
| Production statements | 2,339 |
| Missing statements | 0 |
| Production branches | 604 |
| Partial branches | 0 |
| Coverage | 100% |
| Ruff | Passed |
| Mypy | Passed |

The structured-output implementation was committed as `f7685a8` on October 18, 2026.

A separate live smoke test using a synthetic analytical question successfully exercised Gemini structured JSON generation and VeriSight's investigation parser.

These results establish the tested behaviors and a working provider interaction. They do not establish complete analytical correctness or production readiness.

## Known Limitations

1. There is no independently verified analytical-accuracy benchmark.
2. Final free-text conclusions are not yet deterministically checked against source observations.
3. The public investigation result does not include structured claim-level verification.
4. The current live Gemini test does not cover the complete ingestion-to-synthesis workflow.
5. Large datasets may require additional performance and resource-isolation work.
6. SQL safety restrictions are not a substitute for process or infrastructure isolation.
7. Some ambiguous source representations cannot be reconstructed without additional metadata.
8. There is no public CLI, HTTP API, dashboard, or visualization interface.
9. Generated conclusions may contain incorrect interpretations or unsupported claims.

## Development Roadmap

The immediate sequence is:

### 1. Documentation reconciliation

Align this README, the architecture guide, development instructions, and the authoritative roadmap with implemented source code.

### 2. Deterministic claim verification

Introduce structured analytical claims and explicit evidence references.

Verify numerical statements against returned observations wherever they can be checked deterministically.

Distinguish supported, contradicted, and unverifiable claims.

This feature is planned, not implemented.

### 3. Analytical acceptance evaluation

Build a small benchmark of representative datasets and questions with known answers.

Evaluate:

- SQL correctness
- Analytical answer correctness
- Numerical claim accuracy
- Evidence coverage
- Unsupported-claim frequency
- Correct incomplete-result behavior
- Failure recovery

### 4. Correct verified analytical failures

Use benchmark results to prioritize improvements to planning, execution, investigation, synthesis, and verification.

### 5. Product interface and deployment

Evaluate CLI, HTTP API, reporting, visualization, and user-interface requirements after the core analytical workflow has been measured.

See `docs/roadmap.md` for the canonical development roadmap once its reconciliation is complete.

## Development Documentation

- `docs/architecture.md` — implementation architecture and boundaries
- `docs/development.md` — engineering standards and development workflow
- `docs/roadmap.md` — planned canonical roadmap

## Dataset Attribution

The repository's local development datasets have included the Bank Marketing dataset associated with:

**Moro, S., Cortez, P., and Rita, P. (2014).** *A Data-Driven Approach to Predict the Success of Bank Telemarketing.* Decision Support Systems, 62, 22–31.

Dataset source: [UCI Machine Learning Repository — Bank Marketing](https://archive.ics.uci.edu/dataset/222/bank+marketing).

Check the dataset's current licensing and attribution requirements before redistribution.

Local datasets are not part of the standard source-code commit workflow. Do not accidentally stage private or unrelated data.

## License

VeriSight is distributed under the MIT License.

See [LICENSE](LICENSE).

## Project Direction

VeriSight's next objective is not to add more independent analytical subsystems.

It is to establish that the existing engine can produce **correct, traceable, evidence-supported conclusions** on representative real-world analytical tasks.

Deterministic claim verification and measurable analytical reliability are the next major product-development priorities.
