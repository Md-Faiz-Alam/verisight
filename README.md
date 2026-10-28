# VeriSight

An evidence-verifying autonomous investigator for structured tabular datasets.

VeriSight loads and profiles data, executes analytical SQL, and supports
Gemini-driven investigations. Its default synthesizer produces structured
numerical claims that application code checks against collected query results.

Processing is domain-independent within the supported tabular formats and
types. This does not promise arbitrary-format ingestion or automatic knowledge
of unfamiliar business definitions.

A supported number does not establish that the SQL, interpretation, or narrative
is correct. Narrative verification remains explicitly false.

## Current capabilities

| Capability | Status |
| --- | --- |
| CSV, JSON, and Excel ingestion | Implemented |
| Schema inference, profiling, and data-quality analysis | Implemented |
| Validated DuckDB queries with configured resource limits | Implemented |
| Gemini planning, query repair, and bounded investigations | Implemented |
| Structured synthesis and numerical claim verification | Implemented |
| Application-rendered statements linked to claims | Implemented |
| Limited narrative token audit and Unicode digit coverage | Implemented |
| Evidence recovery for tested expected workflow failures | Implemented |
| Safe failure metadata and generation telemetry | Implemented |
| Five default and three challenge synthetic live development cases | Implemented |
| Caller-selected relation populations | Implemented |
| Optional caller-selected claim output acceptance | Implemented |
| Python 3.11 CI on Windows and Linux | Implemented |
| Narrative meaning and analytical correctness on unfamiliar data | Not established |
| Local CLI for profile, preview, investigation, and JSON export | Implemented |
| Unfamiliar-data reliability and release readiness | Remaining work |

## Installation

Python 3.11 or newer is required. CI currently exercises Python 3.11.

Windows PowerShell, from the repository root:

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

## Local command-line workflow

Install or refresh the editable package after adding the CLI entry point:

```powershell
python -m pip install -e ".[dev]"
verisight --help
```

The same workflow is available as `python -m verisight.cli` without relying on
the console launcher. It uses the existing Python facade and adds no UI dependency.

Start with a supported local file. Profiling and preview never make model calls,
even when a provider key and disclosure permission exist in the environment:

```powershell
verisight profile transactions.csv
verisight investigate transactions.csv --question "What is the net posted amount?" --preview
```

Optional population constraints are supplied as a UTF-8 JSON file. UTF-8 with a
BOM, as commonly written by Windows PowerShell, is accepted. For a relation
named `transactions` with a text column named `state`, the complete file is:

```json
[
  {"relation": "transactions", "column": "state", "values": ["posted"]}
]
```

Use exact schema relation and column names shown by `profile`. One value means
equality; multiple values mean membership. Filters combine with AND. The initial
contract supports homogeneous strings, booleans, or signed 64-bit integers matched
to supported column types. Nulls, dates, decimals, floating-point filters, arbitrary
SQL predicates, and implicit conversions are rejected. The CLI accepts at most
64 KiB of population JSON, 32 filters, and 128 values per filter.

Review the question, supplied scope, original-data profile, and budgets offline:

```powershell
verisight investigate transactions.csv --question "What is the net posted amount?" --population population.json --preview
```

To run generation, configure the provider key/model and explicitly permit this
invocation to disclose analytical context. This flag is required even if the
existing environment configuration enables disclosure:

```powershell
verisight investigate transactions.csv --question "What is the net posted amount?" --population population.json --max-steps 3 --max-seconds 120 --request-timeout-seconds 60 --allow-llm-data-disclosure
```

Omitting `--population` runs an unscoped investigation; it does not infer or
confirm deterministic filters from the question. Units, grain, denominators,
time periods, and business definitions still require review. Population filtering
does not provide privacy isolation; profiles can describe excluded rows.

The CLI prints readable JSON to stdout and phase messages to stderr. Live runs
also show a preliminary profile/request before generation. Files are loaded again
by `investigate()`: the exported final profile comes from that actual investigation,
not the preliminary inspection. Do not mutate input files during a run.

Reports keep workflow status, numerical statements, applied population, unverified
model interpretation, SQL observations, failures, and repair history distinct.
A complete workflow can contain contradicted claims. Numerical support does not
certify analytical meaning, and the CLI assigns no analytically reviewed label.

Optionally require an exact claim count and operations, with supported numerical
evidence and the stricter numeric-token checks described in
[Output contracts](docs/output-contracts.md):

```powershell
verisight investigate transactions.csv --question "Return the net posted amount as exactly one VALUE claim." --population population.json --require-claim value --allow-llm-data-disclosure
```

Repeat `--require-claim` once per required claim. The selected contract appears
in previews and final reports and is passed to structured synthesis. A nonempty
response with the wrong claim count or operations uses the existing single
format-repair attempt. Claims are never silently removed. Empty claims remain
allowed when evidence is insufficient, but cannot pass a nonempty contract.
The final assessment makes no model calls and does not rewrite the result.
State the intended output in the question too. Acceptance does not validate
SQL meaning, and successful repair is not guaranteed.

Add `--output report.json` to profile, preview, or investigation commands to
explicitly export JSON. The parent directory must exist; existing files are never
overwritten. Exports can contain private questions, source evidence, and SQL
literals. No file export occurs without this option. Failed operations can export
classified errors; incomplete investigations retain available evidence.

Exit codes are 0 for a completed workflow or successful offline inspection,
with a selected output contract also requiring its acceptance; 1 for a rejected
contract, incomplete investigation, or operation failure; 2 for invalid command
input or export failure, and 130 for a handled keyboard interruption. Exit code 0
is not an answer-correctness verdict. Keyboard interruption does not promise
recovery of an in-progress investigation or completed report.

## Local analysis and SQL

This example uses temporary synthetic data and requires no Gemini API key.

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from verisight import VeriSight
from verisight.config import Settings

with TemporaryDirectory() as directory:
    path = Path(directory) / "transactions.csv"
    path.write_text(
        "amount,state\n100,posted\n-20,posted\n50,pending\n",
        encoding="utf-8",
    )
    app = VeriSight(settings=Settings(allow_llm_data_disclosure=False))
    analysis = app.analyze(path)
    result = app.execute(
        path,
        "SELECT SUM(amount) AS net_amount FROM transactions WHERE state = 'posted'",
    )
    print(result.columns)
    print(result.rows)
```

Expected query result: column `net_amount`, row `(80,)`.

| Method | Purpose | Return type |
| --- | --- | --- |
| `analyze(paths)` | Profile data and assess quality | `DatasetAnalysisResult` |
| `execute(paths, query)` | Execute supplied analytical SQL | `QueryResult` |
| `ask(paths, question)` | Plan and execute a question | `QueryResult` |
| `investigate(paths, question, max_steps=5)` | Investigate and synthesize | `InvestigationResult` |

Inputs accept a string path, a `Path`, or an iterable of either. Empty inputs
and invalid entries are rejected. `ask()` does not expose planning or repair
history in its return value.

Excel columns containing native booleans and blanks use a nullable boolean
dtype and infer as boolean. Numeric `0`/`1` cells and boolean-looking text remain
distinct from native booleans. Mixed boolean/numeric or boolean/text columns
retain their scalar types in loaded data and infer as `unknown`. This does not
guarantee heterogeneous scalar types survive conversion into a SQL column.

Excel ingestion never recalculates formulas. For `.xlsx`, formulas require a
saved result; missing caches and Excel error cells are rejected before parsing.
Saved numeric, boolean, text, and explicitly empty-string formula results are
supported, but their freshness is not verified. For legacy `.xls`, the loader
uses saved values exposed by xlrd and rejects error cells; it does not recover
formula definitions or independently identify missing or stale formula caches.
Recalculate and save affected workbooks, or export corrected values before loading.

The data boundary rejects blank or NUL-containing column names and names that
collide under DuckDB's ASCII case-insensitive identifier rules. Names are
rechecked before SQL registration because loaded DataFrames remain mutable.
Valid punctuation and distinct Unicode identifiers are preserved. CSV inputs
that pandas would turn into an implicit row index are rejected. JSON duplicate
keys are rejected before they can discard source fields. Decimal fallback and
explicit SQL binding protect supported mixed numerical columns from silent
float conversion; exact decimal
binding has a 38-digit precision limit. Existing floating-point values do not
recover digits already lost upstream.

Numeric profiles use stable arithmetic on finite float-converted values for
mean, median, and sample standard deviation. If the standard deviation itself
exceeds float range, it is null with `standard_deviation_overflow=true`.
`non_finite_count` counts source non-finite values, not computed overflow.
These summaries retain float precision and are not exact decimal aggregates.

Duplicate profiling supports nested JSON lists and objects. SQL results must
contain supported scalar cells; maps, lists, structs, and binary values are
rejected before becoming observations. These protections do not establish
support for arbitrary file formats, data sizes, or domain semantics.

## CSV parsing choices

Automatic CSV loading validates UTF-8 (with or without its BOM) or BOM-marked
UTF-16. It no longer guesses CP1252 or Latin-1 after invalid UTF-8. Declare
legacy encodings explicitly; a successful decode cannot establish the original
encoding. Explicit encoding names use Python's installed codecs and strict
decoding. Incorrect caller declarations can still produce incorrect text.

Delimiter detection considers comma, semicolon, tab, and pipe in an 8,192-character
sample. An inconclusive sample containing a possible separator, or reaching the
sample limit, is rejected rather than silently treated as comma-separated.
A short sample without any supported separator remains a single-column input.
Detection is a convenience, not proof of the intended CSV dialect. Declare
known delimiters explicitly, especially for long quoted or multiline fields.

Both CLI commands accept per-file parsing options; repeat them for other inputs:

```powershell
verisight profile data.csv --csv-encoding data.csv cp1252 --csv-delimiter data.csv ";"
verisight investigate data.csv --question "Describe this table" --preview --csv-encoding data.csv shift_jis --csv-delimiter data.csv ";"
```

Paths in these options must identify supplied CSV inputs. Declare an encoding
or delimiter only once for each file. The same options work for live
investigations; existing disclosure and model configuration requirements apply.

The Python facade accepts independent choices for each input:

```python
from verisight import VeriSight
from verisight.ingestion.models import CsvReadOptions

app = VeriSight(
    csv_options={
        "data.csv": CsvReadOptions(encoding="shift_jis", delimiter=";"),
    }
)
analysis = app.analyze(["data.csv", "other.csv"])
```

Unspecified files use automatic mode. Resolved file paths select options, so
relative and absolute spellings of the same path match. Loaded source metadata
records `csv_encoding` and `csv_delimiter`; deterministic analysis retains it
in `analysis.analysis.sources`. CLI profiles and investigation reports expose
this metadata under `profile.sources`. Explicit investigation declarations also
appear in `request.csv_options`. Other formats leave CSV metadata fields null.
This parsing contract does not certify analytical meaning or recover source
text whose encoding was declared incorrectly.

## Gemini investigations

Configure a local `.env` file or environment variables:

```dotenv
VERISIGHT_GEMINI_API_KEY=replace-with-your-key
VERISIGHT_ALLOW_LLM_DATA_DISCLOSURE=true
```

Set `VERISIGHT_GEMINI_MODEL` to override the configured model. Check available
models and quotas for your provider project. Disclosure permission defaults to
false. Enabling it permits built-in generation to send analytical context,
including schema, profiles, questions, and query observations.

The API key is excluded from normal Settings serialization and representation.
It remains a string accessible to application code. Never commit credentials
or private datasets.

With Gemini configured and a supported dataset available:

```python
from verisight import VeriSight
from verisight.config import Settings

app = VeriSight(settings=Settings())
result = app.investigate(
    "transactions.csv",
    "What is the net posted amount? Exclude pending transactions.",
    max_steps=3,
)
print(result.status.value)
print(result.conclusion)
print(result.narrative_digit_coverage)
for statement in result.quantitative_statements:
    print(statement.text)
```

`max_steps` limits analytical attempts, including failed attempts. It does not
limit provider calls: decisions, planning, repair, and synthesis may each
require generation. `StructuredInvestigationSynthesizer` is the default for
configured Gemini investigations. Custom components can be injected.

The shared `max_investigation_seconds` budget starts after loading and profiling.
The Python API defaults to 300 seconds; the CLI defaults to 120. Provider request
timeouts apply per attempt and are clamped by the shared budget. Expiry of a
shared-budget cancellation stops further provider retries. Client setup, custom
callbacks, cancellation, and cleanup can add overhead; these are cooperative
deadlines, not hard process termination limits.

DuckDB restrictions include relation authorization and blocked metadata calls,
including `current_schemas`. Memory and temporary-storage settings apply to
DuckDB, not all Python or ingestion allocations. The result byte limit applies
after cells are materialized. These controls do not establish a complete sandbox.

## Verification and narrative audit

Claims reference observation rows and named columns. Supported operations are
`value` and `difference` (left minus right). Verdicts are `supported`,
`contradicted`, or `unverifiable`. Opt-in rounding can additionally return
`supported_rounded`.

Structured model-generated claims require decimal strings and use zero
tolerance. The model cannot choose a tolerance. A rounded presentation can
therefore be contradicted in the default investigation result.

Application code can explicitly reverify selected claims using a
`DecimalRoundingPolicy` with 0–12 decimal places and rounding to nearest,
with exact ties away from zero (`ROUND_HALF_UP`), matching DuckDB `ROUND`
for exact decimal inputs:

```python
from verisight.execution.claim_verification import DecimalRoundingPolicy

report = result.verify_claims(
    result.generated_claims,
    rounding_policy=DecimalRoundingPolicy(decimal_places=2),
)
for statement in report.quantitative_statements:
    print(statement.text)
```

Choose precision for the metric's existing units in application code, never
from model-selected decimal places. Exact zero-tolerance matches remain
`supported`; permitted rounded matches receive `supported_rounded`. Reports
retain original evidence, rounded evidence, and the policy. Nonzero absolute
tolerance cannot be combined with rounding. Unsafe quantization returns
`unverifiable`.

This creates a separate verification report. It does not change the original
result, default synthesis, narrative audit, or live evaluator. There is no
unit conversion or automatic interpretation of floating-point differences.

Results expose `generated_claims`, `verified_claims`, and application-rendered
`quantitative_statements`. The fixed scope is
`verification_scope="referenced_numeric_values_only"`; `narrative_verified`
remains false. A `complete` workflow does not certify answer correctness.

The conclusion has two supplementary diagnostics:

- `narrative_numbers` and `unlinked_numbers` compare supported ASCII numerical
  tokens with submitted claim values. Equal values do not establish semantic
  linkage, and tokens can link to contradicted claims.
- `narrative_digit_coverage` counts Unicode digit characters inside and outside
  successfully parsed tokens. Its statuses are `no_digits`, `all_digits_parsed`,
  and `unparsed_digits`.

Neither diagnostic verifies narrative meaning. `all_digits_parsed` does not
validate signs, units, or truth. `no_digits` can include number words.
Unsupported formats such as `12k`, `3.5x`, Unicode minus, and ranges can produce
`unparsed_digits` even when `unlinked_numbers` is empty.

A wrong join, filter, or denominator can produce a number that a claim correctly
repeats. Numerical verification does not establish causation, source quality,
or completeness of generated claims.

Python consumers can call `result.assess_output(ClaimOutputContract(...))` and
inspect `accepted` and `violations`. This separate assessment checks exact claim
operations and count, support, workflow completion, and limited numeric audits.
Its scope remains `claim_shape_and_numeric_evidence_only`, with
`task_semantics_verified=false`. Without a selected contract, CLI exit status
remains workflow-based. See [Output contracts](docs/output-contracts.md).

## Partial results and safe diagnostics

Observations retain questions, SQL, query results, and available
`repair_history`. `InvestigationResult.failed_attempts` exposes recorded failed
attempts with public messages and available repair history. Repair records can
include both failed and replacement SQL, their outcome, and a public error code.
SQL can contain dataset values: this provenance is sensitive result content,
not content-free telemetry. `ask()` still returns only `QueryResult`.

Duplicate-alias SQL analysis failures and unsupported SQL result cells are
classified as query validation failures. During an investigation, these can be
recorded as failed attempts so another query can be tried within the step budget.
Earlier observations remain available when that budget is exhausted.

Expected synthesis failures return `incomplete` with observations and optional `synthesis_failure`.
After at least one successful observation, expected investigator failures and
provider failures during planning or repair return `incomplete` with
`investigation_failure`. Later query-attempt prompt-budget failures also
preserve observations.

Provider failures before evidence collection can still raise. Unexpected
programming errors propagate. Recovery is not a guarantee that every possible
failure returns a partial result.

`run_public_operation` converts raised exceptions into fixed public errors.
A returned incomplete investigation is a successful operation value: inspect
its workflow status and failure metadata. `to_jsonable` in
`verisight.serialization` prepares results for JSON, preserving Decimal values
as strings.

Safe provider diagnostics include HTTP status, retryability, attempts, a coarse
stage, and a per-client call number. Evaluation telemetry records generation
attempts, elapsed time, and whether text returned, without prompts or responses.
Returning text does not imply valid JSON or a correct answer.

## Review SQL before execution

The Python facade supports planning separately from execution:

```python
plan = app.plan(paths, question, population=population)
print(plan.question)
print(plan.sql)
```

`app` is a configured `VeriSight` instance. Model-backed planning requires
credentials and explicit data-disclosure permission. Planning can make provider
calls but does not execute analytical SQL or invoke SQL repair.

Inspect the proposed SQL for population, entity grain, denominator, units,
joins, missing values, and operation order. A returned plan does not establish
SQL validity or analytical correctness.

After review, execute its SQL explicitly:

```python
result = app.execute(paths, plan.sql, population=population)
```

Execution applies the existing SQL validation, population restrictions, and
resource limits. It does not replan or invoke model-based SQL repair. An invalid
query fails rather than being replaced automatically.

Use the same files, CSV parsing options, and population for both calls.
Execution reloads the files; this workflow does not freeze their contents.
The caller is responsible for keeping inputs unchanged between review and
execution. Keep the plan alongside the returned result when recording evidence.

This optional Python workflow returns a `QueryResult`, not an investigation
with generated claims or synthesis. The existing CLI preview remains offline
input inspection; it does not generate proposed SQL. Autonomous investigations
continue to use their existing workflow.

## Evaluation

Run the deterministic development benchmark:

```powershell
python -m pytest tests/test_verification_benchmark.py tests/test_analytical_correctness_benchmark.py tests/test_multistep_correctness_benchmark.py -q
```

The [controlled correctness evaluation](docs/evaluation.md) adds ten questions
with control SQL and intentionally incorrect queries. It exercises the pipeline
and scorer against independent expected answers; generation is scripted, so it
does not measure live model accuracy. The bounded multi-step cases add
cross-observation differences, misleading intermediate results, and partial
failure/step-budget checks, also with scripted generation.

The default live suite (`--case all`) uses five temporary synthetic fixtures: finance,
retail, manufacturing, healthcare, and logistics. Each permits one analytical
step and scores one numerical answer against an independent expected value.

```powershell
python -m scripts.live_evaluation --live --case finance
New-Item -ItemType Directory -Force reports/evaluations | Out-Null
$evaluationStamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
python -m scripts.live_evaluation --live --case all --request-timeout-seconds 60 --provider-retries 1 --output "reports/evaluations/live-$evaluationStamp.json"
```

An additional `--case challenge` suite tests join duplication, a weighted mean,
and a distinct-learner denominator on energy, research, and education schemas.
Each case checks supplied control SQL against an independently specified answer
before model generation. These are development fixtures, not held-out evidence;
see [Evaluation](docs/evaluation.md) for the questions, arithmetic, and protocol.

Live calls require a key and may incur charges. The evaluator enables disclosure
for its synthetic fixtures. Defaults remain 20 seconds per request and zero
additional provider retries; overrides are recorded.

JSON is printed and optionally saved with `--output`. The parent directory must
exist and an existing file is never overwritten. Reports retain revision,
tracked-change status, settings, timings, outcomes, audits, and available failure
and generation metadata. Older reports may lack newer fields.

Current synthetic reports include questions, conclusions, SQL, result cells,
and claim details. The historical record includes successful caller-scoped and
CLI runs as well as supported wrong-population answers, provider failures, and
unmet output contracts. These are separate observations across revisions;
they cannot be pooled into a general reliability rate. See
[Evaluation](docs/evaluation.md) for the evidence checkpoints and remaining protocol.

`correct_numeric` scores the submitted metric; it does not certify prose or SQL
semantics. `no_claims` is not automatically a justified abstention. Retain failed
runs. These known fixtures are not a held-out generalization benchmark.

## Quality gates and CI

```powershell
python -m ruff format --check .
python -m ruff check .
python -m mypy --strict src tests scripts
python -m pytest --cov=verisight --cov=scripts --cov-report=term-missing --cov-fail-under=100
git diff --check
```

[GitHub Actions](https://github.com/Md-Faiz-Alam/verisight/actions) runs these gates
on Windows and Linux with Python 3.11 for pushes to `main`, pull requests, and
manual dispatch. CI uses offline tests without provider credentials. Full
statement and branch coverage measures exercised paths, not universal accuracy.

## Remaining work

- Evaluate unfamiliar schemas and multi-step questions against independent
  answers, with a defined baseline and all attempted cases reported.
- Define and integrate per-metric rounding conventions where justified; the
  current opt-in policy rounds exact ties away from zero, matching decimal SQL
  `ROUND`, while default verification remains strict.
- Validate the local CLI workflow on unfamiliar files, improve demonstrated
  usability gaps, and establish repeatable installation and deployment evidence.

See [Architecture](docs/architecture.md), [Development](docs/development.md),
and [Roadmap](docs/roadmap.md).

## Dataset attribution

Local development has used Bank Marketing, associated with:

Moro, S., Cortez, P., and Rita, P. (2014).
*A Data-Driven Approach to Predict the Success of Bank Telemarketing.*
Decision Support Systems, 62, 22–31.

Source: [UCI Bank Marketing](https://archive.ics.uci.edu/dataset/222/bank+marketing).
Check applicable licensing before redistribution. Local datasets are not part
of the standard source-code commit workflow.

## License

MIT. See [LICENSE](LICENSE).