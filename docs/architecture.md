# VeriSight architecture

## Boundaries

VeriSight separates deterministic data processing from generative proposals.
Models propose decisions, SQL, conclusions, and numerical claims. Application
code validates queries, executes them, and checks referenced numerical values.

Numerical support, analytical correctness, and narrative correctness are
separate questions. The current verifier addresses the first.

## Facade and deterministic processing

`VeriSight` in `src/verisight/service.py` exposes `analyze`, `execute`, `ask`,
and `investigate`. Inputs accept a string path, a `Path`, or an iterable of
either. Empty collections and invalid entries are rejected.

CSV, JSON, and Excel loaders validate supported inputs and produce loaded
relations. Schema inference, profiling, and quality rules produce deterministic
analysis. Loader precision protections do not establish source-data accuracy.
The Excel loader uses a header-only parse to configure converters for the full
parse. Identity-based temporary cell wrappers prevent pandas inference and
equality caching from merging native booleans with numeric `0`/`1`. Scalars are
restored into object series before application inference, preserving exact
integers. Empty string cells are treated as missing; literal text such as `NA`
remains text.

Columns containing only native booleans among nonmissing cells become `bool`
or nullable `boolean`. Mixed boolean/numeric or boolean/text columns retain
native scalars in loaded data and infer as `unknown`. Pure numeric `0`/`1`
columns remain integer columns, and boolean-looking text is not reinterpreted.
All-blank columns remain unknown. SQL engines can still coerce heterogeneous
object columns; preserving mixed source scalars at ingestion is not a guarantee
of mixed scalar types in SQL results.

Loaded tables reject column identities that collide after string conversion
and ASCII case normalization, matching DuckDB's identifier behavior even for
quoted names. This is not Unicode case folding. CSV loading rejects implicit
pandas row indexes that would otherwise hide extra source fields. Short records
can still produce missing trailing cells; this guard is not a complete CSV
record-width validator.

For inferred CSV numerical columns that cannot retain their source decimal
values through ordinary numeric conversion, loading falls back to Decimal.
Object-backed numerical columns are bound through explicitly checked DuckDB
DECIMAL precision and scale. Non-finite values in that binding path or a required
precision above 38 digits raise a query runtime error. Native float columns keep
their existing floating-point semantics, and digits lost before ingestion cannot
be recovered. These protections do not make every SQL operation exact.

Duplicate profiling falls back to structural snapshots for nested lists and
objects when pandas cannot hash their cells. Mapping order is immaterial;
sequence order and container kinds remain distinct. Source cells are unchanged.
This supports nested JSON values, not arbitrary custom Python objects.

Planner, investigator, repairer, and synthesizer dependencies support injection
for deterministic tests and alternative behavior.

## SQL execution and investigation

The analytical service builds query context, plans SQL, validates it, and uses
DuckDB to execute against loaded dataset relations. The executor disables
external access and automatic extension loading/installation. Configured limits
cover result rows, query execution time, memory, and temporary storage.
These controls are not a complete deployment security assessment.

With `max_steps=1`, an investigate decision plans the caller's original question,
not the model's rewritten subquestion. A component-only query would exhaust the
sole attempt before another query could collect the requested final metric.
With larger budgets, the investigator's subquestion remains the planning task.
The investigator still decides whether to request a query and when to finish.
This policy removes a task-narrowing step; it does not guarantee correct SQL,
sufficient evidence, or successful completion. Observation and failure questions
identify the task actually sent to planning, including in custom runners.

The orchestrator also passes the original question as context for every task.
`QueryRequest.original_question` and `QueryRepairRequest.original_question` are
optional context fields; `question` remains the current evidence request and
plan identity. Planning and runtime repair receive the same original context.
Prompts distinguish explicit inclusions from exclusions and require checking the
population actually queried before completion or synthesis. This preserves
context; it does not deterministically validate SQL semantics.

`AnalyticalQueryRunner.run` and service `plan`/`run` accept an optional keyword
`original_question`. Custom runners must accept that keyword. Existing calls
without it remain valid, and direct `ask()` uses its question as prompt context.
No mutable per-investigation context is stored on the execution service.

Planner and repair prompts specify double-quoted identifiers, exact supplied
names, and the distinction between relation identifiers and display names.
Quoting does not authorize an unavailable relation.

Expected SQL parsing and source-resolution errors, including duplicate aliases,
become `QueryValidationError`. Relation analysis must succeed before execution;
analysis failure does not bypass authorization. The built-in executor rejects
nested or binary result cells before constructing `QueryResult`. Use scalar
columns and grouped rows instead of map, list, struct, or BLOB results.

A runtime SQL failure can trigger one query repair. `QueryExecution` retains the
successful plan, result, and available `repair_history`. Each `QueryRepairAttempt`
records the failed plan, optional replacement, outcome, and optional public error
code. Successful observations inherit repair history; recorded failed attempts
can retain unsuccessful repairs. This is query provenance, not a complete trace
of provider requests or synthesis-format repair. `ask()` returns only `QueryResult`.

The orchestrator tracks successful observations and recorded failed attempts.
`max_steps` limits analytical attempts, including failures. It does not cap
provider requests. Repeated normalized questions and exhausted step budgets
produce incomplete results.

The orchestrator initializes `InvestigationState.remaining_steps` from the
configured limit. Each successful or recorded failed attempt reduces that
immutable snapshot, clamped at zero. Manually constructed states may leave it
unknown (`None`). Both full and compacted investigator prompts preserve the
actual remaining count and instruct the investigator to prioritize requested
measurements over unnecessary exploration. Compaction does not replenish the
budget when observation details are omitted.

The runtime limit remains authoritative even if the model requests another
query at zero. A decision after the last permitted attempt can still choose
finish and allow synthesis from existing evidence. That decision can fail, and
finishing does not establish that all requested measurements were collected.
Budget visibility does not guarantee that the model allocates attempts correctly
or that the provider remains available.

Ordinary query validation, execution, and nonprovider planning failures can be
recorded so the investigator can choose another bounded attempt.
`InvestigationResult.failed_attempts` exposes the recorded question, exception
type, fixed public message, and available repair history. Exhausting the budget
returns incomplete results with prior observations and recorded failures.

## Optional caller-selected populations

The public `execute`, `ask`, and `investigate` methods accept a keyword-only
`population` tuple. Each `PopulationFilter`, imported from
`verisight.execution.context`, names an exact relation and column and a nonempty
tuple of values. One value expresses equality; multiple values express
membership. Filters combine with AND; values within one filter combine with OR.

The initial contract accepts homogeneous text, boolean, or signed 64-bit integer
values, matched to the corresponding inferred column type. Unknown relations,
unknown columns, mixed values, mutable collections, null values, and unsupported
column/value types are rejected. Dates, decimals, floating-point comparisons,
expressions, ranges, and caller-supplied SQL predicates are not supported by this
contract. Missing cells do not satisfy membership. No match is an empty
population, not an invalid policy.

The built-in executor applies these filters while registering queryable relations,
after its existing precision-preserving numeric projection. The original source
frames are unchanged. Every reference to that relation, including CTEs, joins,
subqueries, UNION branches, and repaired queries, uses the restricted relation.
Generated SQL cannot broaden that relation by omitting its WHERE clause or adding
OR TRUE. Relation authorization and resource limits still apply. Mutable dataset
schemas are revalidated before each scoped execution.

A policy restricts only its named relations. Other supplied relations remain
available under their own policies. A comparison needing excluded records must
use a separately supplied, deliberately scoped comparison relation or a separate
request. This is a query-population contract, not tenant isolation or a guarantee
that the requested comparison is meaningful.

Planning, repair, investigator prompts, compacted investigator prompts, and
structured synthesis receive the supplied policy. Row counts, profiles, insights,
and quality findings still describe the original loaded data; prompts distinguish
these from restricted query evidence. They can contain information about excluded
rows, so this mechanism is not a data-disclosure control.

Complete and incomplete `InvestigationResult` values serialize `population`.
As with existing results, manually constructed objects and injected execution
components are trusted application code; metadata alone is not proof of
enforcement. Direct `execute` and `ask` retain their existing `QueryResult` return
contract, so their callers must retain the submitted population specification.

The model cannot supply or replace the policy through its generated response.
The application enforces supplied constraints but does not establish that they
capture a natural-language question's business meaning, grain, denominator, or
metric. Unscoped calls retain their existing behavior. Existing live evaluations
remain unscoped: a caller-scoped run must be reported separately and must not be
presented as evidence that autonomous population interpretation was corrected.

## Structured synthesis

The default configured synthesizer is `StructuredInvestigationSynthesizer`.
It sends a compact provider JSON schema while retaining strict local Pydantic
validation. The provider schema does not replace the local contract.

Local validation rejects unknown fields, duplicate JSON keys, nonstandard
non-finite constants, invalid reference structures, unsupported operations, and
invalid expected-value formats. Expected numbers must be decimal strings.
The response allows at most 50 claims and a bounded nonblank conclusion.

Plain JSON and supported JSON fences are accepted. One response-format repair
is allowed. Feedback contains original bounded evidence and an approved error
category, not the rejected response or raw validation details. Each prompt
must pass the character budget before generation.

Provider failures bypass format repair; bounded provider retries apply
independently to each generation call. Contradicted claims do not trigger
format repair. Legacy injected synthesizers may return plain text without
structured claims. Legacy synthesis formatter dependencies are configured
through the prompt builder's constructor.

## Numerical verification and rendered statements

`NumericalClaimVerifier` resolves observation, row, and named-column references.
Supported operations are `value` and `difference` (left minus right).
Decimal-based arithmetic avoids float coercion. Unsuitable cells, ambiguous
columns, invalid references, and unsafe required arithmetic fail closed.

Default verdicts are `supported`, `contradicted`, and `unverifiable`. The direct Python
claim API accepts an absolute tolerance. Structured model-generated claims
use zero tolerance and cannot supply their own comparison policy.

`DecimalRoundingPolicy` is an opt-in application policy with 0–12 decimal places
and fixed `ROUND_HALF_UP`: round to nearest, with exact ties away from zero.
This matches DuckDB `ROUND` for exact decimal inputs; binary floating-point
representations can still differ. It can be passed to `NumericalClaimVerifier` or to
`InvestigationResult.verify_claims()`. Precision is not inferred from the claim.
Nonzero absolute tolerance and rounding cannot be combined.

The verifier first performs its existing numerical comparison. Exact matches
remain `supported`. For a usable contradicted result, the policy quantizes the
original numerical evidence and accepts only equality with that rounded value,
returning `supported_rounded`. Wrong values remain contradicted; unsuitable or
unsafe numerical evidence remains unverifiable. Unsafe quantization also returns
unverifiable, retaining the original computed value.

Verification metadata includes `rounding_policy` and `rounded_actual`. Decimal
context precision and exponent limits can make quantization unavailable. Local
rounding changes do not mutate caller context. Evidence arithmetic is not
silently rounded to make an otherwise unsafe computation pass.

Application-rendered statements expose the policy and rounded evidence when
configured. This policy does not infer units, scale percentages, or certify SQL
semantics. The original investigation's computed verdicts and token audit stay
unchanged when a separate rounded report is requested. Default synthesis and live
evaluation continue to use strict comparison.

`InvestigationResult` computes `verified_claims` and `quantitative_statements`
from generated claims and observations. Each immutable `ClaimLinkedStatement`
contains a zero-based claim index, the verified claim, and application-rendered
text showing operation, expected value, evidence value, tolerance, and verdict.
Human-readable claim labels start at 1.

Evidence references lead to observation rows, columns, and executed SQL. Rendered
statements do not certify the conclusion, infer units, or establish causation.
`verify_claims()` can create a separate `InvestigationVerificationReport` whose
indexes refer to its own submitted claim sequence.

## Narrative tokens and digit coverage

`find_narrative_numbers()` scans the conclusion for a limited ASCII numerical
syntax. Supported forms include signed integers and decimals, leading-dot
values, scientific notation, conventional comma grouping, and a percentage
suffix. Percentages compare the printed value: `25%` can match `25`, not `0.25`.

Each `NarrativeNumberToken` stores original text, Python string offsets
(`start` inclusive, `end` exclusive), a parsed Decimal or null, and matching
zero-based claim indexes. Matching uses exact expected claim values, independent
of verdict or tolerance. Repeated occurrences remain separate.

`unlinked_numbers` contains detected tokens without matching submitted claims.
Tokens with rejected syntax or conversion limits remain unlinked. The lexer
excludes or misses formats including identifiers, dates, ranges, ratios, glued
units, scaled suffixes, Unicode minus, Unicode digits, and number words.
Standalone years and numbered headings can still be detected.

`narrative_digit_coverage` provides a separate backstop. It counts characters
recognized by `str.isdigit()`, including Unicode digits, and checks whether
they fall inside successfully parsed tokens from that same conclusion.

| Field | Meaning |
| --- | --- |
| `total_digit_count` | Number of digit characters, including repeated occurrences |
| `parsed_digit_count` | Digit characters within tokens with parsed values |
| `unparsed_digit_count` | Remaining digit characters |
| `status` | `no_digits`, `all_digits_parsed`, or `unparsed_digits` |

Rejected tokens count as unparsed. This backstop does not normalize Unicode,
interpret suffixes, split ranges, or infer numerical meaning. An empty
`unlinked_numbers` list can coexist with `unparsed_digits`.

`all_digits_parsed` establishes character coverage only. It does not certify
signs, units, matching claims, or truth. `no_digits` does not exclude number
words. Digit counts and unlinked tokens are not hallucination metrics without
independent semantic labels.

These derived fields are rebuilt during result construction, including
`dataclasses.replace`, and included in serialization. The fixed fields remain
`narrative_verified=False` and
`verification_scope="referenced_numeric_values_only"`.

## Partial results and failure contracts

Task acceptance is separate from workflow completion and numerical support.
The built-in pipeline does not deterministically verify arbitrary natural-language
requirements such as query count, query order, claim count, requested units, or
business meaning. Treat task compliance as **not assessed automatically**.
A caller or evaluator must compare the original requirements with the ordered
observations, executed SQL, result populations, and submitted claims. A known
fixture may have an independent acceptance check; that check is not a general
semantic verifier and must not change the recorded workflow status or numerical
verdicts.

Prompts preserve explicit analytical procedures ahead of preferences for compact
queries and limit synthesis to the requested claim scope. Each planner or repair
call still returns exactly one safe SQL statement for its current evidence request.
Explicit requirements cannot override safety restrictions, response schemas, or
budgets. If the requested procedure is unmet, synthesis is instructed to state
the limitation rather than describe the procedure as completed. These instructions
are model guidance, not runtime enforcement. No domain-specific procedure or
fixture answer is built into production logic.

`complete` means the workflow reached synthesis completion. It does not mean
all claims are supported or the analytical answer is correct.

| Failure path | Behavior |
| --- | --- |
| Expected synthesis error or provider failure | Incomplete result with observations and `synthesis_failure` |
| Expected investigator error after a successful observation | Incomplete result with `investigation_failure` |
| Provider failure during later planning or repair | Incomplete result with `investigation_failure` |
| Prompt-budget failure during a later query attempt | Incomplete result with `investigation_failure` |
| Investigator/synthesis budget or incomplete-evidence failure | Incomplete result; failure metadata may be absent |
| Provider failure before any successful observation | Can raise to the caller |
| Unexpected programming error | Propagates |

`synthesis_failure` distinguishes `provider_unavailable`, `provider_error`, and
`synthesis_error`. `investigation_failure` records a stage (`investigator` or
`query_execution`), a safe kind, and optional provider diagnostics.
`query_execution` covers planning, execution, and repair; it is not a precise
planner-versus-repair trace.

Classification follows explicit exception causes with cycle protection.
Metadata does not retain exceptions or copy raw messages. Both failure fields
require incomplete status. They do not describe every incomplete path or
replace full failed-attempt and repair history.

## Provider requests and telemetry

`GeminiTextGenerationClient` disables SDK retries and applies bounded application
retries to typed transient failures. Timeouts and retry settings come from
Settings. Provider diagnostics can include HTTP status, retryability, attempts,
a coarse generation stage, and a per-client call number.

`generation_telemetry.py` uses context-local capture scopes. Each recorded call
contains stage, call number, attempts, elapsed seconds, and `returned_text`.
Duration includes application retry delays. Calls outside a capture scope are
not retained. Stages are inferred from response-schema fields; generic text
calls do not distinguish planning from repair. Call numbers are not globally
unique.

Capture records no prompt, response, credential, or raw exception message.
`returned_text=True` does not establish schema validity or answer correctness.
Telemetry does not measure token usage, provider charges, or server-side work.

## Public boundary, serialization, and evaluation

Settings load environment variables and an optional `.env` file. Built-in
provider generation requires a key and disclosure permission. Normal Settings
serialization and representation exclude the key; application code can still
access it as a string.

`run_public_operation` converts raised exceptions into fixed public reports.
Unexpected internal errors are logged by exception type only. A returned
incomplete investigation is a successful operation value; consumers must
inspect its workflow status and metadata.

`to_jsonable` serializes supported domain results, including derived audits and
safe failure metadata and query provenance. Decimal values become strings.
Observations and repair plans contain SQL that may embed dataset values.
Questions and source evidence can also be sensitive. Content-free diagnostic
metadata does not make a whole investigation result safe to publish automatically;
API and export consumers need an explicit disclosure policy.

The live evaluator uses the default investigation path with five temporary
synthetic fixtures. It scores one VALUE claim against an independent expected
metric. `correct_numeric` does not require complete digit coverage or certify
narrative or SQL semantics. Incomplete results retain available failure metadata;
escaping exceptions follow a separate failure-report path.

Saved reports include revision, tracked-change status, settings, timings,
audits, and observed generation calls when available. Older reports may lack
new fields. Missing telemetry is not evidence of zero provider calls.

## CI and remaining architecture work

`.github/workflows/ci.yml` runs offline gates on Windows and Linux with Python
3.11. Deployment isolation, cancellation, workload limits, richer provenance,
per-metric rounding integration, semantic evaluation, and the end-user workflow remain
separate acceptance work. See [Roadmap](roadmap.md).