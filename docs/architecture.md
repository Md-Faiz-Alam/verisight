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
Nullable Excel boolean inference remains a known gap.

Planner, investigator, repairer, and synthesizer dependencies support injection
for deterministic tests and alternative behavior.

## SQL execution and investigation

The analytical service builds query context, plans SQL, validates it, and uses
DuckDB to execute against loaded dataset relations. The executor disables
external access and automatic extension loading/installation. Configured limits
cover result rows, query execution time, memory, and temporary storage.
These controls are not a complete deployment security assessment.

A runtime SQL failure can trigger one query repair. The returned `QueryExecution`
contains the successful plan and result; it does not retain a complete repair
history. `ask()` returns only `QueryResult`.

The orchestrator tracks successful observations and internal failed attempts.
`max_steps` limits analytical attempts, including failures. It does not cap
provider requests. Repeated normalized questions and exhausted step budgets
produce incomplete results.

Ordinary query validation, execution, and nonprovider planning failures can be
recorded internally so the investigator can choose another bounded attempt.
The final result does not yet expose those internal failed-attempt records.

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
structured claims.

## Numerical verification and rendered statements

`NumericalClaimVerifier` resolves observation, row, and named-column references.
Supported operations are `value` and `difference` (left minus right).
Decimal-based arithmetic avoids float coercion. Unsuitable cells, ambiguous
columns, invalid references, and unsafe required arithmetic fail closed.

Default verdicts are `supported`, `contradicted`, and `unverifiable`. The direct Python
claim API accepts an absolute tolerance. Structured model-generated claims
use zero tolerance and cannot supply their own comparison policy.

`DecimalRoundingPolicy` is an opt-in application policy with 0–12 decimal places
and fixed `ROUND_HALF_EVEN`. It can be passed to `NumericalClaimVerifier` or to
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
safe failure metadata. Decimal values become strings. Full investigation results
contain source evidence; content-free diagnostic metadata does not make the
whole result safe to publish automatically.

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