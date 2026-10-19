# VeriSight architecture

## Scope

VeriSight separates deterministic data processing from generative investigation.
Models propose queries and conclusions; application code validates queries,
executes them, and checks submitted numerical claims.

The current verification boundary is referenced numerical evidence.
Narrative correctness and analytical semantics remain outside that boundary.

## Public facade

`VeriSight` in `src/verisight/service.py` provides:

| Operation | Responsibility |
| --- | --- |
| `analyze` | Load datasets and build deterministic analysis |
| `execute` | Validate and execute supplied SQL |
| `ask` | Plan and execute a natural-language analytical request |
| `investigate` | Coordinate bounded investigation and synthesis |

Inputs may be a string path, a `Path`, or an iterable of either.
Input validation rejects empty collections and invalid entries.

Planner, investigator, repairer, and synthesizer dependencies support controlled
substitution in tests.

## Ingestion and deterministic analysis

The ingestion layer dispatches supported CSV, JSON, and Excel inputs to loaders.
Validation checks file and table constraints before downstream analysis.

Schema inference, profiling, and quality rules produce structured analysis
results. These deterministic results supply context for investigation.

Preservation of source meaning is a contract: identifiers, missing values,
large integers, and text values must not be silently reinterpreted.
Known remaining gaps include nullable Excel boolean inference.

## Analytical execution

The execution layer separates planning, validation, execution, and repair.

1. A planner produces an analytical SQL plan.
2. Validation checks the query against supported operations and relations.
3. DuckDB executes the validated query under configured resource limits.
4. Eligible failures may enter query repair.
5. Successful execution produces a `QueryResult`.

SQL restrictions and resource controls reduce risk. They do not establish that
a query answers the intended question or provide a general operating-system
sandbox.

`ask()` returns `QueryResult`. Its public return value does not include a full
planning and repair audit trail.

## Investigation orchestration

`InvestigationOrchestrator` maintains an `InvestigationState` containing the
original question, deterministic analysis, observations, and failed attempts.

The investigator decides whether to ask another analytical question or finish.
Successful execution adds a `QueryObservation` containing the question, SQL,
and query result.

Selected query failures are recorded in internal investigation state.
Repeated questions and exhausted analytical-step budgets terminate investigation
with an incomplete result.

`max_steps` bounds analytical attempts rather than total provider calls.

Prompt-budget and incomplete-evidence paths preserve collected observations.
Expected synthesis failures also return incomplete results with observations.
Other errors, including provider failures during investigation decisions or
query planning, can still escape without returning a partial result.
Unexpected programming errors continue to raise.

## Structured synthesis and format repair

The default Gemini-enabled facade uses `StructuredInvestigationSynthesizer`.
It serializes investigation state into a budgeted prompt and requests a JSON
object containing a conclusion and numerical claims.
The prompt treats investigation state as untrusted data.

The response contract requires:

- A nonblank conclusion.
- At most 50 claims.
- Decimal strings for expected values.
- Supported operations: `value` or `difference`.
- Explicit observation, row, and column references.
- No unknown fields or model-selected tolerance.

Duplicate JSON fields and nonstandard constants are rejected.
Responses exceeding 60,000 characters are rejected.

The parser accepts plain JSON or one complete code fence labeled `json`,
case-insensitively, or with no language label. LF and CRLF line endings are
supported. Surrounding prose and other language labels are not accepted as
valid response wrappers.

If response parsing or validation fails, the synthesizer permits one additional
generation call for format repair. The repair prompt contains the original
schema and evidence plus one application-defined validation category:

- `invalid_json`
- `invalid_schema_or_claim`
- `response_too_large`

The rejected response, raw validation messages, and parser input values are
omitted from repair feedback. The repair prompt must pass the character budget
before a second call is made.

The second response passes the same strict parser and claim construction rules.
A second format failure raises an `InvestigationError` subtype, which the
orchestrator converts into an incomplete result with evidence preserved.

Format repair does not repair SQL or establish numerical correctness.
Successfully parsed claims still pass through deterministic verification.
A contradicted claim does not trigger this format-repair mechanism.

Provider-generation failures bypass format repair. Existing provider retry
settings apply independently to each generation call. Consequently, two
synthesis generation calls can involve more than two network requests.

The synthesizer returns `StructuredSynthesis`. Legacy injected synthesizers may
return plain text, which does not supply generated claims.

## Numerical verification

`NumericalClaimVerifier` resolves evidence references and evaluates numerical
comparisons using Decimal-based arithmetic.

References must identify an available observation, row, and unambiguous column.
Nulls, booleans, strings, non-finite values, and invalid references cannot support
a numerical claim.

The verifier supports direct values and differences. Unsafe or inexact required
arithmetic fails closed as `unverifiable`.

Verdicts are `supported`, `contradicted`, and `unverifiable`.
The direct claim API supports an absolute tolerance. Structured model-generated
claims use zero tolerance and cannot override it.

There is no separate rounded-match verdict or application rounding policy yet.

## Investigation results and synthesis failures

`InvestigationResult` contains:

- Question and conclusion.
- Deterministic analysis.
- Collected observations.
- Workflow status.
- Generated numerical claims and computed `verified_claims`.
- Computed `quantitative_statements` linked to those verified claims.
- Computed `narrative_numbers` and `unlinked_numbers` for a limited token audit.
- Fixed `narrative_number_audit_scope="ascii_numeric_tokens_only"`.
- Optional `synthesis_failure` metadata.
- Fixed `narrative_verified=False`.
- Fixed `verification_scope="referenced_numeric_values_only"`.

Verification is computed from generated claims and retained observations.
`complete` is a workflow status rather than a certification of the conclusion.
An empty claim list does not establish that a narrative has no numerical claims.

A recorded synthesis failure requires `INCOMPLETE` status. Its kind is:

| Kind | Meaning |
| --- | --- |
| `provider_unavailable` | A typed transient provider-generation failure |
| `provider_error` | Another typed provider-generation failure |
| `synthesis_error` | Another expected synthesis failure, including invalid output |

Failure classification follows explicit exception causes with cycle protection.
Metadata retains existing safe provider diagnostics when available, without
retaining exception objects or copying exception messages.

`synthesis_failure` is null when no such failure was recorded. It is not a
complete description of every incomplete-result path. For example, a prompt
budget failure can produce an incomplete result without synthesis metadata.

The result still omits internal failed query attempts and repair history.

## Claim-linked quantitative statements

`InvestigationResult.quantitative_statements` provides one application-rendered
statement per generated numerical claim. Each immutable `ClaimLinkedStatement`
contains:

- `claim_index`: a zero-based index into the result's generated and verified claims.
- `verified_claim`: the corresponding claim and its numerical verdict.
- `text`: computed from the operation, expected value, evidence value, absolute
  tolerance, and verification status.

Human-readable claim labels start at 1. The stored `claim_index` starts at 0.
Evidence references in the linked claim lead to observation rows, columns,
and the executed SQL.

For example, a contradicted value claim can render as:

> Claim 1 (value): expected 31; evidence 30; absolute tolerance 0; status contradicted.

An unavailable numerical result is rendered as `evidence unavailable`, with
its `unverifiable` status. Decimal values are rendered without rounding or
conversion to float. Tolerances remain visible, including tolerances supplied
through the direct Python claim API.

The model supplies conclusions and claims; the application computes statement
text after verification. Statement text does not copy the generated conclusion,
column labels, or interpretation. It does not infer units or causal meaning.

`InvestigationVerificationReport` also exposes `quantitative_statements` for
claims passed to `verify_claims()`. In that report, indexes refer to its own
submitted claim sequence, which may differ from the investigation's generated
claims.

Statements are rebuilt when a result is constructed, including reconstruction
with a changed claim sequence. Empty claim sequences produce empty statement
sequences. This does not certify an empty or number-free narrative.

The original `conclusion` remains unverified. A separate numerical token audit
reports unmatched tokens within a limited syntax. Neither the rendered statements
nor token matching establish a semantic link between narrative sentences and
submitted claims. Consumers can display quantitative statements with their
explicit verdicts and expose the generated conclusion as unverified interpretation.

## Numerical token audit of the conclusion

`narrative_audit.py` scans the conclusion and compares detected numerical tokens
with `generated_claims` expected values using exact Decimal equality.
It does not match against observed values or apply claim tolerances.
Calling `verify_claims()` with a separate claim sequence does not mutate the
original investigation's audit.

`InvestigationResult.narrative_numbers` records each detected token's text,
zero-based Python string character offsets (`start` inclusive, `end` exclusive),
parsed value, and matching zero-based `claim_indexes`.
Multiple equal claims can match one token. Repeated occurrences remain separate.

`unlinked_numbers` contains the original text of detected tokens without a
matching submitted claim, in occurrence order, including repetitions.
A conclusion containing `9999` with no corresponding claim reports that token.
A conclusion containing a number with no submitted claims also reports it.

Supported syntax includes ASCII integers, signed decimals, leading-dot decimals,
scientific notation, and conventional three-digit comma grouping.
A percentage suffix is retained in the token text. Matching compares the printed
number: `25%` can match a claim of `25`, while it does not match `0.25`.
Percentage scaling, units, and rounding are not inferred.

Detected tokens longer than 128 characters, malformed grouping, leading-zero
integer forms, and unconvertible exponents have a null parsed value and remain
unlinked. Conversion does not use float or Python integer parsing.

The lexer excludes word identifiers, dotted versions, and contiguous ASCII date
or arithmetic forms such as `ID123`, `1.2.3`, `2026-10-19`, and `10-5`.
Number words and unsupported Unicode signs are outside its syntax.
Standalone years and numbered headings can still produce audit warnings.
This audit cannot establish that every numerical assertion was detected.

Linkage is independent of verification: a token can match a contradicted or
unverifiable claim. Equal numbers also cannot establish direction, causation,
units, filters, or whether a sentence describes the correct measurement.
An empty `unlinked_numbers` sequence never sets `narrative_verified` to true.
Use token counts as audit diagnostics; a hallucination metric requires
independently labeled semantic outcomes.

These computed fields are rebuilt on result construction and included in
serialization. They preserve the original conclusion and workflow status.

## Verification boundary

Three questions must remain distinct:

1. Does the submitted number match its referenced evidence?
2. Does that evidence answer the analytical question correctly?
3. Does the narrative accurately describe the evidence and its limitations?

Current numerical verification addresses the first question.
A supported claim can repeat the result of an incorrect join, filter, or
denominator. A narrative can also contradict a supported claim.

## Provider integration and public errors

`GeminiTextGenerationClient` handles provider requests and bounded application
retries. SDK retries are disabled by the client configuration.
Retry policy and request timeout come from Settings.

Safe diagnostics can include HTTP status, retryability, attempt count,
inferred generation stage, and a per-client generation call number.
Stages are coarse categories, not a complete distributed trace.

`Settings` loads optional `.env` values and `VERISIGHT_` environment variables.
Built-in generation requires an API key and disclosure permission.
The key is excluded from normal Settings serialization and representation.
It remains a string available to application code.

`run_public_operation` translates raised failures into fixed public reports.
Retryable Gemini failures can map to `provider_unavailable`.
Unexpected internal failures are logged by exception type only.

A returned incomplete investigation is a value at that public boundary.
Callers must inspect investigation status and synthesis failure metadata in
addition to checking whether the public operation raised an error.

## Serialization and evaluation

`to_jsonable` converts supported domain results into JSON-compatible structures.
Decimal values are preserved as strings. Synthesis failure metadata is included
in serialized investigation results.

Deterministic benchmarks exercise numerical verification and SQL behavior with
controlled generative components.
The live evaluator exercises the default provider-backed investigation path on
three temporary synthetic fixtures.

An incomplete live result remains in the `incomplete` outcome bucket.
Its `synthesis_failure` details are included when available.
Exceptions that escape investigation retain the evaluator's separate failure
classification path.

Passing deterministic tests establishes reproducible implementation behavior.
It does not establish correctness on every unfamiliar dataset or consistent
live-provider availability.

## Outstanding architectural work

- Preserve partial evidence across remaining decision and planning failures.
- Return failed query and repair provenance.
- Link narrative findings to claim identities.
- Define application-controlled rounding.
- Extend independent semantic and ground-truth evaluation.
- Improve nullable Excel boolean inference.
- Remove private attribute assignment in legacy synthesis.
- Add identifier-quoting instructions to planner and repair prompts.
- Establish CI, deployment isolation, and operational acceptance criteria.