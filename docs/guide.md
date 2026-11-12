# VeriSight guide

Detailed use of the command line, the Python API, cleaning rules, investigations and verification. For a short introduction, see the [README](../README.md); for limits and targets, see the [system specification](system-spec.md).

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
[Output contracts](output-contracts.md):

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

## Automatic dashboards

Every upload gets a dashboard with headline figures, a trend over time, category
breakdowns, value spreads and short findings. It is computed by validated SQL
without any model call, so no data leaves the server, and each figure can show
its query. In Python, use `VeriSight().dashboard_builder(paths).build()`.

The table's subject area is recognised from its relation and column names:
retail, finance, healthcare, HR, marketing, logistics, education, energy,
manufacturing, real estate, environment, economy or sports. A table with too
little evidence stays "General data". The area only decides which measures lead
and how the page is titled; it never changes a number, and it is a guess from
names, so check that it fits.

Three rules protect the figures:

- Rows detected as totals of other rows are left out, and the page says so.
- A measure is summed only when its name says it can be, such as `amount` or
  `quantity`. Everything else, including prices, rates and unfamiliar names, is
  averaged, and every figure is labelled "Total" or "Average".
- Labels that differ only by case or outer spaces are grouped together.

Clicking a category filters the whole dashboard. Column names decide what is
treated as an ID, a date or a measure, so an unusually named column can be
charted the wrong way.

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

Text columns become datetime columns when every present value fits one clear
format: an ISO 8601 date such as `2026-01-31`, with or without a time; a date with
a time zone, such as `2026-01-31T10:15:00Z`, which is converted to UTC; a spelled-out
month such as `Jan 5, 2024`; or a numeric date such as `25/12/2026` when some value
in the column proves the day and month order. If nothing proves the order, as with
`03/04/2026`, the column stays text and an `ambiguous_dates` warning is reported.
Each value must be a real date in pandas' timestamp range (years 1677 to 2262). Date
columns profile as `datetime` and support SQL date functions such as `YEAR()`,
`strftime` and `date_diff`; Excel date cells were already loaded as datetimes.

Common messy values are cleaned only when every present value in a column fits
one clear rule, in CSV, JSON and Excel alike, and every change is reported:

| Rule | Example | Result |
| --- | --- | --- |
| Missing-value markers in a column that is otherwise numbers or ISO dates | `3, N/A, 2` | `N/A` becomes missing |
| Comma group separators | `1,234.50` | `1234.5` |
| One currency mark on every value, before or after the number | `$12.00`, `USD 100`, `100 €` | `12.0`, noted as `$ removed` |
| A percent sign on every value | `10%` | `10`, in percent points |
| Numbers in brackets | `(1,234.50)` | `-1234.5` |
| K, M or B after a number, when the column is shown to hold amounts | `1.2K` | `1200` |
| One known unit on every value | `12 kg` | `12`, noted as `kg removed` |
| Comma decimals, when the values prove them | `1.234,50`, `1,5` | `1234.5`, `1.5` |
| Up to 5% stray values in a column of 20 or more | `10, 20, TBD` | `TBD` becomes missing, with a warning |
| Placeholders in a text column | `N/A`, `null`, `--` | Missing |
| A last row labelled as a summary whose number matches the rows above | `Total,,550` | Row removed, with a warning |
| Leading or trailing spaces in a column name | `" Amount "` | `Amount`, when the name stays distinct |

The markers for otherwise numeric or date columns are `N/A`, `NA`, `#N/A`, `null`,
`None`, `NaN`, `-`, `--`, `?` and common case variants. In text columns, `NA` stays
a label because it can mean North America, and words that can be real categories,
such as `unknown` or `None`, are kept and reported as `possible_missing_labels`.
Columns named like identifiers (`id`, `code`, `sku`, `zip`, `phone`, `key`, `ref`,
`serial`) never lose stray values, and leading zeros, mixed currencies and mixed units
stay as text.

A number with letters after it can be a code instead of a quantity: `10M` can be a
shoe size and `12A` a seat. K, M and B are expanded only when the column's name says
it holds amounts, such as `salary` or `followers`, or the values show it with a
currency mark or a decimal. A unit must be on a known list, and a one-letter unit
such as `V` also needs a space before it or a measurement in the column's name, such
as `voltage`. Columns named like labels (`size`, `seat`, `model`, `version` and
similar) are never read this way. Currency codes need a space or a decimal, so
`GBP100` stays as text, and numbers in brackets need another value to compare with,
so a column of nothing but `(123)` stays as text. A column left as text because its
values could be either gets an `ambiguous_numbers` warning.
`1,234` alone is read as 1234 with a note to check it, unless the file is separated
by semicolons, where it is read as 1.234. Plain numbers stored as JSON or Excel text
are not converted. Labels that differ only by letter case or surrounding spaces,
such as `Shipped` and `shipped `, are never changed; they are reported as label
variants, and SQL planning compares them with `LOWER(TRIM(column))` unless the
question distinguishes them. Each change or variant appears as a data-quality
finding with the column, the number of affected values and up to three original
examples.

File layouts are repaired and reported too. Title lines above the headers are
skipped when a lower row is clearly the header. Blank headers become
`unnamed_<position>`, and repeated headers become `name_2`. JSON can be an array of
rows, an object of columns, one wrapper object holding the rows, or one object per
line, and nested objects become columns such as `user.age`.

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
collide under DuckDB's ASCII case-insensitive identifier rules (CSV and Excel
headers are repaired first, as described above). Names are
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
UTF-16. A file that is neither is read as Windows-1252, the default for Excel on
Windows, and a `guessed_encoding` warning is reported because other encodings can
decode to the wrong letters. Declare the encoding explicitly when you know it.
Explicit encoding names use Python's installed codecs and strict
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
remains workflow-based. See [Output contracts](output-contracts.md).

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

The website marks an answer as verified only on `agreed`, and only when the second
query was written differently from the first. `identical_sql` records a repeat: the
same query apart from aliases, quoting and the order of AND conditions. A repeat
usually adds no evidence, so the answer stays at "Number matches SQL only".

The exception is a query with only one route, recorded as `single_route`: it reads
one table, returns one value built from aggregates, has no join, grouping,
subquery, distinct values, window or row-picking aggregate such as `arg_max`, and
never compares or combines two columns. `AVG(area)` or `SUM(amount) WHERE region =
'East'` qualify. `shipped <= required`, `price - cost` and `SUM(a) / SUM(b)` do
not, because relating two columns defines a new concept, and two models can share
the same wrong definition. For a single-route query, a blind repeat written by a
different model, recorded as `separate_model`, still shows that both models chose
the same rows, column and calculation, so it passes the check. When one model
writes both queries, a repeat never counts. Agreement
between different queries is still evidence, not proof: both can make the same
mistake, and that is more likely when one model writes both. Set
`VERISIGHT_GEMINI_CROSS_CHECK_MODEL` to a different model to reduce that risk. On the
command line, add `--cross-check` to run this check, the SQL audit and the
answers without AI. Without it, the report shows the trust level as `not_run`.

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

The controlled correctness evaluation in
`tests/test_analytical_correctness_benchmark.py` adds ten questions
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
before model generation. These are development fixtures, not held-out evidence.

Live calls require a key and may incur charges. The evaluator enables disclosure
for its synthetic fixtures. Defaults remain 20 seconds per request and zero
additional provider retries; overrides are recorded.

JSON is printed and optionally saved with `--output`. The parent directory must
exist and an existing file is never overwritten. Reports retain revision,
tracked-change status, settings, timings, outcomes, audits, and available failure
and generation metadata. Older reports may lack newer fields.

Current synthetic reports include questions, conclusions, SQL, result cells,
and claim details. Earlier hand-run reports remain in this repository's Git
history. They are separate observations across revisions and cannot be pooled
into a general reliability rate.

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
