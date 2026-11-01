# Caller-selected claim output contracts

Workflow completion, numerical support, and task acceptance are separate.
A complete investigation may contain supported claims yet violate the caller's
requested output shape.

`ClaimOutputContract` checks a narrow postcondition on an existing result.
The caller supplies a nonempty tuple of `ClaimOperation` values. Its length
specifies the exact claim count; repetitions specify repeated operations.
Operation order is ignored. No requirements are inferred from question text.

Acceptance requires all of the following:

- A complete investigation workflow.
- Exactly the specified claim operations, including their multiplicities.
- Every returned claim has a supported numerical verification result.
- Every parsed narrative numeric token links to a returned claim.
- No digit characters remain unparsed by the existing narrative audit.
- No whole-word English cardinals from the bounded contract vocabulary appear
  in the conclusion, even if they express a supported claim value.

These checks preserve the verifier's existing tolerances and rounding rules.
An incomplete result or an empty claim list cannot satisfy a nonempty contract.

## Python

```python
from verisight.execution.claim_verification import ClaimOperation
from verisight.execution.investigation_result import ClaimOutputContract

contract = ClaimOutputContract((ClaimOperation.DIFFERENCE,))
result = app.investigate(
    paths,
    question,
    claim_output_contract=contract,
)
assessment = result.assess_output(contract)
if not assessment.accepted:
    print(assessment.violations)
```

The assessment is separate from the original result. Assessing it does not
change workflow status, remove claims, alter evidence, or make model calls.
API consumers must inspect `assessment.accepted` when enforcing this contract.

## CLI

```powershell
verisight investigate readings.csv `
    --question "Measure before and after; report only after minus before as one DIFFERENCE claim." `
    --require-claim difference `
    --allow-llm-data-disclosure `
    --output new-report.json
```

Repeat `--require-claim` once per required claim. For example, two occurrences
of `--require-claim value` require exactly two VALUE claims. `--preview` shows
the selected contract without generation.

The option passes the selected contract into investigation state and structured
synthesis, without rewriting the question. State the intended output in the
question as well. The synthesizer receives the contract as application policy,
separately from untrusted evidence. A nonempty response with the wrong operation
multiset or claim count uses the existing single format-repair attempt. Feedback
contains the safe `claim_output_contract_mismatch` category and the original
evidence, not the rejected response. There is no additional repair loop, query
retry, or silent removal of claims.

In contract mode, structured synthesis also checks the same narrative predicates
as final assessment: every detected numeric token must link to a returned claim
expected value, all digit characters must be covered by parsed tokens, and
conclusions must not contain the bounded English cardinal words listed below.
Question-context numbers are not exempt. These failures use the existing
`unlinked_narrative_number` category and share the single repair attempt with
schema and shape failures; they do not receive an additional attempt.
Repair instructions require removing prose numbers when their claims are removed,
unless another retained claim links them. Component cells remain referenced by
claims without repeating their values in final-only prose. Evidence can exist
without its numbers being permitted in the conclusion. Contract-mode generation
instructions require numerical quantities to use numeric literals rather than
number words. The bounded cardinal-word restriction is enforced locally, not
only requested in the prompt.
Out-of-scope quantities must be omitted entirely, not spelled out. Context and
references may be described without stating their quantities.

If evidence is insufficient, empty claims remain allowed; they cannot pass a
nonempty output contract. The system does not force a numerical assertion to
fill the required count. Repeated shape failure produces an incomplete result
with SQL observations retained and synthesis failure metadata. Numerical
contradictions do not trigger shape repair. Provider failures and the shared
deadline retain their existing handling.

Final `assess_output()` remains a separate deterministic check with no model
calls. A rejection there does not trigger further generation. Custom injected
synthesizers receive the contract in state but can ignore its generation policy;
consumers must still check the final assessment.

The report retains `workflow_status`, the complete investigation evidence,
`request.claim_output_contract`, and `claim_output_assessment`. With a selected
contract, CLI exit code 0 requires both completion and contract acceptance.
Exit code 1 includes rejected contracts and incomplete workflows; input and
export errors retain their existing handling. Without the option, the contract
and assessment are null and exit behavior remains workflow-based.

## Targeted numerical repair feedback

When a selected contract rejects a parsed conclusion for unlinked numbers, the
existing single repair attempt can include `unlinked_numeric_values`. This field
contains up to eight distinct parsed values, each represented as a canonical
numeric string of at most 32 characters, in first-appearance order. Linked values,
unparseable tokens, and oversized representations are omitted. The examples are
not a complete list of violations and do not authorize the values as claims.

Repair guidance asks the model to omit those quantities entirely from the
conclusion, including number-word forms, use nonquantitative contextual
descriptions where appropriate, preserve the requested metric and valid evidence
references, and avoid dummy claims. The rejected prose, raw token text, and raw
validation messages are not copied into feedback. These
bounded generated numeric values are sent to the same synthesis provider; they
are not added to public failure diagnostics or logs by this feature.

The complete repair prompt remains subject to its existing character budget.
Malformed responses and other validation categories retain generic error-category
feedback. Calls without a selected output contract do not receive these numeric
examples and retain their existing question-context allowance.

Every repaired response must pass the unchanged parser, claim-shape, token-linkage,
digit-coverage, and contract-mode cardinal-word checks. Numerical evidence
verification and final output
assessment remain separate. A failed second response still produces the existing
terminal synthesis failure; this adds no generation loop, SQL query, automatic
text edit, relaxed comparison, or contextual-number exemption.

## Limits

The assessment scope is `claim_shape_and_numeric_evidence_only`, with
`task_semantics_verified=false`. Acceptance does not verify populations,
denominators, grain, units, query order, causal meaning, or narrative truth.
A plausible number from the wrong SQL can still pass.

Numeric-token checks inherit the existing audit's syntax limits. Contract mode
adds a case-insensitive whole-word restriction for `zero` through `nineteen`,
`twenty`, `thirty`, `forty`, `fifty`, `sixty`, `seventy`, `eighty`, `ninety`,
and singular or plural `hundred`, `thousand`, `million`, `billion`, and `trillion`.
Hyphenated forms containing these words are rejected. Words embedded in longer
identifiers such as `someone` or `one_source` are not matched.

This is a lexical output policy, not a number-word parser. It rejects a correct
`fifty` as well as an incorrect `seventy`, and it also rejects nonquantitative
uses such as `one source`. Use numeric literals for the permitted metric and
context descriptions without these cardinal words. Quoted labels are not exempt.
The assessment reports `english_cardinal_words`. Structured synthesis uses the
existing `unlinked_narrative_number` category and the same single repair attempt;
it does not add rejected prose or word values to repair feedback.

Fractions such as `half`, ordinals, other English number words, other languages,
repeated values, semantic roles, and direction remain unverified. For example,
`fell by 50` can pass when a supported claim is 50, regardless of whether the
metric actually fell. Absence of a cardinal-word violation does not establish
absence of numerical assertions or narrative truth. Calls without a contract
retain their existing narrative behavior; explicitly assessing any result with a
contract applies this restriction.

Contextual numbers such as years are rejected when detected and not linked to
claims. The built-in contract-mode synthesizer offers its bounded repair before
returning such a response. Do not add irrelevant claims merely to pass; keep
final-only conclusions within the requested output scope. Offline tests establish
the deterministic checks and scripted repair behavior, not live model compliance.
Any claim of improved live completion requires a separately specified repeated
evaluation at fixed settings.

The numerical checks introduce no dataset-specific rules. The additional
cardinal-word restriction is English-specific and is not multilingual validation.


## Advisory population review

Built-in natural-language execution attaches `population_review` to each
executed observation. CLI JSON exposes it under
`investigation.observations[].population_review`. Custom query runners and
manually constructed observations can leave this field null (not assessed).
The review does not rewrite SQL, run extra SQL, call a model, change claim
acceptance, or change the CLI exit status.

The heuristic compares exact case-insensitive category mentions in the original
question with bounded observed string values and simple SQL filters. It handles
one directly queried outer table, aliases, conjunctions, equality, inequality,
and literal membership. A nested membership query on another column does not
establish a category filter on the outer table. An exact single-value caller
filter is recognized separately from the SQL text.

- `review_required`: a uniquely mentioned category lacks a recognized explicit
  inclusion filter. Inspect the original question, SQL and caller population.
- `no_warning_detected`: this narrow heuristic found no warning. This is not
  semantic verification; units, grain, denominators and other filters can be wrong.
- `not_assessed`: the wording or SQL falls outside the supported subset, or no
  unique category was identified. This is not a successful population check.

Direct negative mentions are skipped, but natural-language interpretation is
incomplete. CTEs, joins, derived tables, OR predicates on the target column,
conditional aggregation, functions on that column, ambiguous labels and absent
category evidence are not assessed. False alarms and missed concerns remain
possible. Multiple positive category mentions in the same question are ambiguous
for this first version. No status establishes intended business meaning.

Warnings contain the relation, column, mentioned category and a stable code.
These local diagnostics can contain dataset identifiers and values. They use
original-data category evidence, not a redacted or population-filtered vocabulary.
They are excluded from synthesis prompts and never treated as numerical evidence.
Existing caller-selected population enforcement remains independent.


## Advisory counting-grain review

Built-in natural-language execution also attaches `grain_review` to executed
observations. CLI JSON exposes it under
`investigation.observations[].grain_review`. This is separate from population
review, numerical support and output-contract acceptance. Custom runners and
manually constructed observations may leave it null.

The first version recognizes positive instructions of the form "count account
identities, not rows" or "count entities, not source rows", with bounded
intervening words. It does not infer an entity key or fully interpret arbitrary
wording. For a single count-based projection over one directly queried table,
ordinary COUNT expressions produce `review_required` with warning
`row_counts_for_identity_request`. Distinct counts produce
`no_warning_detected`, which does not establish that the correct identity
columns, conditions, numerator or denominator were used.

CTEs, nested queries, joins, grouped queries, window calculations, multiple
projections, other aggregate types and unrecognized requests are `not_assessed`.
A legitimate row-count request is not treated as an identity-count request.
Ordinary counts can be correct when source rows are already unique; a warning
requests review rather than proving the SQL wrong. Caller population filters
restrict rows but do not deduplicate identities or suppress this diagnostic.

The check does not rewrite SQL, run additional queries, call a model, change
acceptance or change the CLI exit status. Its metadata is excluded from synthesis
prompts. Every status retains `task_semantics_verified=false`. This is a narrow
advisory, not autonomous enforcement of analytical grain.
