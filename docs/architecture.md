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

Successful analytical execution adds a `QueryObservation` containing:

- The analytical question.
- The executed SQL.
- The query result.

Selected query failures are recorded in internal investigation state.
Repeated questions and exhausted analytical-step budgets terminate investigation
with an incomplete result.

`max_steps` bounds analytical attempts rather than total provider calls.

Prompt-budget and incomplete-evidence paths preserve collected observations.
Other errors, including some provider and synthesis failures, can still escape
without returning a partial investigation result.

## Structured synthesis

The default Gemini-enabled facade uses `StructuredInvestigationSynthesizer`.

It serializes investigation state into a budgeted prompt and requests a JSON
object containing a conclusion and numerical claims. The prompt treats
investigation state as untrusted data.

The response contract requires:

- A nonblank conclusion.
- At most 50 claims.
- Decimal strings for expected values.
- Supported operations: `value` or `difference`.
- Explicit observation, row, and column references.
- No unknown fields or model-selected tolerance.

Duplicate JSON fields and nonstandard constants are rejected.

The current synthesis parser rejects fenced JSON. Invalid responses raise
`InvestigationError`; there is no synthesis-format repair loop yet.

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

Verdicts are:

- `supported`
- `contradicted`
- `unverifiable`

The direct claim API supports an absolute tolerance. Structured model-generated
claims use zero tolerance and cannot override it.

There is no separate rounded-match verdict or application rounding policy yet.

## Investigation results

`InvestigationResult` contains:

- Question and conclusion.
- Deterministic analysis.
- Collected observations.
- Workflow status.
- Generated numerical claims.
- Computed `verified_claims`.
- Fixed `narrative_verified=False`.
- Fixed `verification_scope="referenced_numeric_values_only"`.

Verification is computed from generated claims and retained observations.

`complete` is a workflow status. It is not a certification of the conclusion.
An empty claim list does not establish that the narrative has no numerical
assertions.

The result currently omits internal failed attempts and repair history.

## Verification boundary

Three questions must remain distinct:

1. Does the submitted number match its referenced evidence?
2. Does that evidence answer the analytical question correctly?
3. Does the narrative accurately describe the evidence and its limitations?

Current numerical verification addresses the first question.

A claim can be supported while its query uses an incorrect join, filter, or
denominator. A narrative can also contradict a supported claim.

Future narrative linkage and semantic evaluation must not relabel numerical
support as general correctness.

## Provider integration and diagnostics

`GeminiTextGenerationClient` handles provider requests and bounded application
retries. SDK retries are disabled by the client configuration.

Retryable failures include selected HTTP failures and transport or timeout
errors. Retry policy and request timeout come from Settings.

Safe diagnostics can include:

- HTTP status.
- Retryability.
- Attempt count.
- Inferred generation stage.
- Per-client generation call number.

Generation stages are coarse categories, not a complete distributed trace.

Public provider exceptions avoid carrying raw SDK messages as public diagnostics.
A successful connectivity request does not establish that a multi-request
investigation will complete.

## Configuration and public errors

`Settings` loads optional `.env` values and `VERISIGHT_` environment variables.
Built-in generative components require an API key and disclosure permission.

The key is excluded from normal Settings serialization and representation.
It remains a string available to application code.

`run_public_operation` translates failures into fixed public error reports.
Retryable Gemini failures can map to `provider_unavailable`.
Unexpected internal failures are logged by exception type only.

## Serialization

`to_jsonable` converts supported domain results into JSON-compatible structures.
Decimal values are preserved as strings.

Serialization preserves declared evidence and verification fields. It does not
supply missing provenance or verify report prose.

## Evaluation boundaries

Deterministic benchmarks exercise real numerical verification and SQL behavior
with controlled generative components.

The live evaluator exercises the default provider-backed investigation path on
three temporary synthetic fixtures.

These serve different purposes:

- Deterministic tests establish reproducible implementation behavior.
- Live runs measure provider-backed behavior for the recorded fixtures.
- Neither establishes correctness on every unfamiliar dataset.

## Outstanding architectural work

- Preserve partial observations across synthesis and provider failures.
- Return structured failure and repair provenance.
- Link narrative findings to claim identities.
- Define application-controlled rounding.
- Extend independent semantic and ground-truth evaluation.
- Improve nullable Excel boolean inference.
- Remove private attribute assignment in the legacy synthesis component.
- Add identifier-quoting instructions to planner and repair prompts.
- Establish CI, deployment isolation, and operational acceptance criteria.
