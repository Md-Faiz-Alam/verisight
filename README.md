# VeriSight

**Ask questions about CSV, Excel and JSON files from any domain in plain English.
VeriSight answers with the SQL it ran, and accepts a number only when it matches
the query result.**

[![CI](https://github.com/Md-Faiz-Alam/verisight/actions/workflows/ci.yml/badge.svg)](https://github.com/Md-Faiz-Alam/verisight/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![Test coverage 100%, enforced in CI](https://img.shields.io/badge/coverage-100%25-brightgreen)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

![VeriSight reporting data-quality findings for a messy orders file, the SQL Gemini wrote, and an answer verified against the SQL result](docs/assets/demo.svg)

*From a live run ([evaluation v2](docs/results.md), run 3): VeriSight reports the
messy values it found while loading, Gemini writes the SQL, and the answer is
checked against the executed result.*

## Why VeriSight

- **Verified, not just generated.** Gemini plans the SQL and states each number
  as a claim on a result cell. VeriSight checks the claim against the executed
  query and refuses numbers it cannot support. On the website, a second query
  written without seeing the first must reach the same number before an answer
  is marked verified. When it cannot verify an answer, it says so instead of
  guessing.
- **Messy data handled in the open.** `N/A`, `$1,234.50`, `10%`, `Shipped ` /
  `shipped` and padded headers are cleaned under strict rules, and every change
  is reported as a data-quality finding.
- **Safe SQL.** One read-only statement over the loaded tables only: no file,
  network or settings access, with time, memory and result-size limits.
- **Measured honestly.** 150 live attempts across 7 domains, with every run
  published, failures included.

## Quickstart

Windows PowerShell (on macOS or Linux, use `source .venv/bin/activate` and
forward slashes):

```powershell
git clone https://github.com/Md-Faiz-Alam/verisight.git
cd verisight
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .

# Create three messy demo files: no download, no AI
python evaluation\v2\run_v2_eval.py --prepare --data-dir demo --preflight-only

# Profile a file: schema, statistics and data-quality findings, no AI
verisight profile demo\orders.csv

# Ask a question: needs a free Gemini API key in .env
Copy-Item .env.example .env   # then set VERISIGHT_GEMINI_API_KEY=your-key
verisight investigate demo\orders.csv --question "How many orders were shipped?" --require-claim value --allow-llm-data-disclosure
```

`--allow-llm-data-disclosure` is required because the schema, profile, question
and observed values are sent to Gemini. `profile` and `--preview` never call the
model. Get a key from [Google AI Studio](https://aistudio.google.com/apikey).

## Website

VeriSight also runs as a website: upload files or try the demo data, review the
data-quality findings, ask questions, and see the SQL behind every verified
answer. It is a FastAPI REST API with interactive docs at `/docs`, plus a single
page with no external scripts.

```powershell
python -m pip install -e ".[web]"
verisight-web
```

Then open <http://127.0.0.1:8000>. Visitors can paste their own Gemini key,
which is used for one question and never stored. To publish it, see
[Deploy on AWS](docs/deploy-aws.md).

## Live results

Across **150 development attempts** on 37 frozen questions in 7 domains and 3
formats (CSV, JSON, Excel), VeriSight accepted **85 answers, all correct**; in
13 it said no number could be verified instead of guessing. On **held-out**
datasets that played no part in development, with questions committed before
each run, the first set exposed bugs and **3 wrong accepted answers** where the
SQL answered a different question. After the fixes, a second held-out set of
15 questions on 5 more unseen datasets gave **26 correct and 0 wrong** in 30
attempts. Every run is listed, including failures, in
[Live results](docs/results.md).

## Scope and limits

Processing is domain-independent within the supported tabular formats and
types. This does not promise arbitrary-format ingestion or automatic knowledge
of unfamiliar business definitions.

A supported number shows that the value came from an executed SQL result. It
does not establish that the SQL, interpretation, or narrative is correct, so
review the SQL. Narrative verification remains explicitly false.

## Current capabilities

| Capability | Status |
| --- | --- |
| CSV, JSON, and Excel ingestion | Implemented |
| Website and REST API with uploads, data-quality view and verified answers | Implemented |
| Reported cleaning of missing markers, separators, currency, percent, padded headers | Implemented |
| ISO date and date-time columns in CSV and JSON | Implemented |
| Schema inference, profiling, and data-quality analysis | Implemented |
| Validated DuckDB queries with configured resource limits | Implemented |
| Gemini planning, query repair, and bounded investigations | Implemented |
| Structured synthesis and numerical claim verification | Implemented |
| Independent second-query cross-check of single-number answers | Implemented; required for the website's verified label, not yet evaluated live |
| Application-rendered statements linked to claims | Implemented |
| Limited narrative token audit and Unicode digit coverage | Implemented |
| Evidence recovery for tested expected workflow failures | Implemented |
| Safe failure metadata and generation telemetry | Implemented |
| Five default and three challenge synthetic live development cases | Implemented |
| Caller-selected relation populations | Implemented |
| Optional caller-selected claim output acceptance | Implemented |
| Python 3.11 CI on Windows and Linux | Implemented |
| Analytical correctness on unfamiliar data | Evidenced on 67 live questions, 30 of them held out ([Live results](docs/results.md)); not guaranteed |
| Narrative meaning | Not verified |
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

Temporary provider errors, such as 503 "model overloaded", are retried
`--provider-retries` times per model call (0-5, default 1). The first wait is
`--provider-retry-delay-seconds` (default 1) and each later wait doubles, up to 8
seconds. All waits count toward `--max-seconds`. The request block in the report
records both values.

Omitting `--population` runs an unscoped investigation; it does not infer or
confirm deterministic filters from the question. Units, grain, denominators,
time periods, and business definitions still require review. Population filtering
does not provide privacy isolation; profiles and observed categorical values can
include information from excluded rows.

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
| `plan(paths, question)` | Generate proposed SQL without analytical execution | `QueryPlan` |
| `execute(paths, query)` | Execute supplied analytical SQL | `QueryResult` |
| `ask(paths, question)` | Plan and execute a question | `QueryResult` |
| `investigate(paths, question, max_steps=5)` | Investigate and synthesize | `InvestigationResult` |

Inputs accept a string path, a `Path`, or an iterable of either. Empty inputs
and invalid entries are rejected. `ask()` does not expose planning or repair
history in its return value.

CSV and JSON text columns become datetime columns only when every present value
is an ISO 8601 calendar date, such as `2026-01-31`, optionally with a time such as
`2026-01-31 10:15` or `2026-01-31T10:15:30.5`. Each value must be a real date in
pandas' timestamp range (years 1677 to 2262). A single other value keeps the whole
column as text. Regional formats such as `03/04/2026` are never guessed, and values
with time-zone offsets stay text because no zone is attached or converted. Date
columns profile as `datetime` and support SQL date functions such as `YEAR()`,
`strftime` and `date_diff`; Excel date cells were already loaded as datetimes.

Common messy values are cleaned only when every present value in a column fits
one clear rule, in CSV, JSON and Excel alike, and every change is reported:

| Rule | Example | Result |
| --- | --- | --- |
| Missing-value markers in a column that is otherwise numbers or ISO dates | `3, N/A, 2` | `N/A` becomes missing |
| Comma group separators | `1,234.50` | `1234.5` |
| One currency symbol (`$`, `€`, `£`, `₹`, `¥`) on every value | `$12.00` | `12.0`, noted as `$ removed` |
| A percent sign on every value | `10%` | `10`, in percent points |
| Leading or trailing spaces in a column name | `" Amount "` | `Amount`, when the name stays distinct |

The markers are `N/A`, `NA`, `#N/A`, `null`, `None`, `NaN`, `-`, `--`, `?` and
common case variants. Text columns, such as a region column where `NA` means North
America, are never changed. Leading zeros, mixed currencies, European formats such
as `1.234,50` and malformed grouping stay as text. Plain numbers stored as JSON or
Excel text are not converted. Labels that differ only by letter case or
surrounding spaces, such as `Shipped` and `shipped `, are never changed; they are
reported as label variants, and SQL planning compares them with
`LOWER(TRIM(column))` unless the question distinguishes them. Each change or
variant appears as a data-quality finding (`missing_value_markers`,
`formatted_numbers`, `label_variants` or `trimmed_column_name`) with the column,
the number of affected values and up to three original examples. A CSV column
with a blank header, such as the unnamed index column of a pandas export, is
named `unnamed_<position>` and reported as `named_blank_column`; Excel workbooks
still need every used column to have a header.

Rows that hold the total of other rows, such as a `Total` region per month or an
`All causes` entity per year, are detected when a category value's measure equals
the sum of the other rows in nearly every group of rows sharing the remaining
key columns. They are reported as a `total_row` warning, listed for SQL planning
so totals are not added to their own parts, and an aggregate that ignores them is
marked for review.

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
collide under DuckDB's ASCII case-insensitive identifier rules (CSV blank headers
are named first, as described above). Names are
rechecked before SQL registration because loaded DataFrames remain mutable.
Valid punctuation and distinct Unicode identifiers are preserved. CSV inputs
that pandas would turn into an implicit row index are rejected. JSON duplicate
keys are rejected before they can discard source fields. JSON can be an array
of row objects or an object of equal-length column arrays. Columns of exact
decimals infer as `decimal` and are profiled as numbers. Decimal fallback and
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

Delimiter detection considers comma, semicolon, tab, and pipe using a sample
of at most 65,536 decoded characters. It uses complete sampled CSV records,
including quoted multiline records, and permits missing trailing cells in
short rows. A truncated sample requires at least two complete records.
Competing delimiters, records wider than the header, or too little complete
data require an explicit delimiter. Supported single-column files can load
automatically. Detection is a convenience, not proof of the intended CSV
dialect; declare known delimiters explicitly.

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
including schema, profiles, questions, query observations, bounded observed
categorical values and detected total-row values used by SQL planning and repair.
These values come from the original loaded data before caller-selected
population filters.
They can include raw identifiers or other sensitive strings and are not
automatically redacted. Population filters restrict analytical query relations;
they do not redact model context.

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

One exception covers binary floating-point noise, not rounding. SQL adds DOUBLE
values in binary, so a sum of currency amounts such as 333819.64 can arrive as
`333819.64000000036`. When a cited cell is a float, a claim written with at most
12 significant digits is `supported` if it agrees with the evidence to 12
significant digits of the largest cited cell. The reason says so, and the
original cell is kept. A double carries 15–17 significant digits, so `333819.6`,
`333820` and claims with more than 12 digits are still contradicted. Integer and
decimal cells stay exact.

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

## Independent cross-check

A number that matches its own SQL can still answer the wrong question. With
`investigate(..., cross_check=True)`, which the website always uses, an answer
that passed every other check is calculated again by a second query. That query
is planned from the question and dataset alone: the planner never sees the first
SQL, its result or the conclusion. It costs at least one more model call and
shares the investigation's time budget.

`result.cross_check` records one of three outcomes:

| Status | Meaning |
| --- | --- |
| `agreed` | Both numbers match, allowing only for binary floating-point noise. A rounded value does not match. |
| `disagreed` | The numbers differ. Both values and the second SQL are kept. |
| `not_assessed` | No comparison was possible: the answer has several claims, the second query failed or returned no single number, the provider was unavailable, or time ran out. |

The website marks an answer as verified only on `agreed`. Agreement is evidence,
not proof: both queries can make the same mistake, and that is more likely when
one model writes both. Set `VERISIGHT_GEMINI_CROSS_CHECK_MODEL` to a different
model to reduce that risk. `identical_sql` shows when the second query only
repeated the first formulation. The CLI does not run this check.

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
CLI investigation reports include the same allowlisted metadata as
`generation_calls`, including for operation errors, so time-budget failures can
be attributed to individual calls. Previews make no calls and omit the field.
Returning text does not imply valid JSON or a correct answer.

## Review SQL before execution

For questions with an explicit target population, select that population before
planning and pass the same filters to execution. A question asking for production
records requires production records; excluding test records can also include
calibration records. The caller supplies this meaning. VeriSight does not infer
or confirm it deterministically.

The Python facade supports planning separately from execution. This complete
example assumes local `generation.csv` and `reviews.csv` inputs. Their relation
names must be `generation` and `reviews`, and the generation table must have a
text column named `record type` whose target value is `production`. Inspect the
schema with `analyze()` or CLI `profile` before choosing these names.

Run the example as a Python script or in an interactive Python session so that
standard input is available for the review prompt:

```python
from hashlib import sha256
from pathlib import Path

from verisight import VeriSight
from verisight.config import Settings
from verisight.execution.context import PopulationFilter

paths = (Path("generation.csv"), Path("reviews.csv"))
question = (
    "What is the total production output in kWh for readings with at least "
    "one approved review? Count each generation row once."
)
population = (
    PopulationFilter(
        relation="generation",
        column="record type",
        values=("production",),
    ),
)
before = {path: sha256(path.read_bytes()).hexdigest() for path in paths}

planner = VeriSight(
    settings=Settings(
        allow_llm_data_disclosure=True,
        gemini_request_timeout_seconds=30,
        gemini_max_retries=0,
    )
)
plan = planner.plan(paths, question, population=population)
print("Question:", plan.question)
print("Enforced input population:", population)
print("Proposed SQL:")
print(plan.sql)

if input("Review the SQL; type EXECUTE to run it: ").strip() != "EXECUTE":
    raise SystemExit("Stopped without executing analytical SQL.")

after = {path: sha256(path.read_bytes()).hexdigest() for path in paths}
if after != before:
    raise SystemExit("Inputs changed. Plan and review again before execution.")

executor = VeriSight(
    settings=Settings(
        _env_file=None,
        gemini_api_key=None,
        allow_llm_data_disclosure=False,
    )
)
result = executor.execute(paths, plan.sql, population=population)
print(result.columns)
print(result.rows)
```

Model-backed planning requires configured credentials and explicitly enables
data disclosure in this example. It can send original-data profiles and observed
categories, including values from rows excluded by the population. Planning does
not execute analytical SQL or invoke SQL repair. The execution instance disables
built-in model generation and executes the exact reviewed SQL.

Before typing `EXECUTE`, inspect the SQL for entity grain, duplicate review rows,
approval membership, missing values, units, and calculation. A membership query
using `EXISTS` or `IN` can avoid multiplying generation rows by repeated reviews;
a plain join can inflate the sum. Population enforcement alone does not check
these requirements. Stop and correct the SQL if review finds a problem.

Population filters restrict input relations before SQL runs. They are not a
substitute for conditions that must apply after an operation, such as choosing
the latest revision before testing eligibility. A returned plan and a completed
query do not establish general analytical correctness.

Execution applies existing SQL validation, population restrictions, and resource
limits. It does not replan or invoke model-based SQL repair. An invalid query
fails rather than being replaced automatically.

Use the same file paths, CSV parsing options, and population for planning and
execution. The example uses automatic CSV parsing for both instances. If explicit
`csv_options` are needed, pass the same mapping to both. The hash comparison
detects changed file bytes between its two checks; it is not an atomic snapshot
and cannot prevent concurrent changes during loading. Keep input files stable.
Keep the reviewed SQL, population, input fingerprints, and result together when
recording evidence.

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

### Evaluation v2: messy values, dates and a join

`evaluation/v2/run_v2_eval.py` asks 14 frozen questions over three generated
files: `orders.csv` with currency text, thousands separators, percent signs,
`N/A` and `-` markers, label variants and a padded header; `customers.xlsx`,
joined to orders, where region `NA` means North America; and `sensors.json`
with ISO date-times and kWh numbers mixed with `N/A`. A fixed seed makes the
files identical on every machine. Expected answers come from the generator's
clean values, and offline preflight checks each control SQL and trap SQL
before any model call.

```powershell
python evaluation\v2\run_v2_eval.py --prepare --data-dir datasets\v2 --preflight-only
python evaluation\v2\run_v2_eval.py --data-dir datasets\v2 --out F:\verisight-validation-artifacts\eval-v2\run-1
```

Live runs use three provider retries starting at two seconds by default. Every
attempt is kept, and `--out` must be a new folder.

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