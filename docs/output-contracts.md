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

In contract mode, every claim reference must also resolve to an existing
numeric SQL result cell (observation, row and exact column), and a difference
must reference two different cells. A claim citing a missing column, missing
row, missing observation or non-numeric cell, or subtracting a cell from itself,
can never pass the contract. It uses the existing single repair attempt with the
safe `invalid_claim_reference` category; feedback does not include the rejected
values. Without a contract, such claims are returned and verified as
`unverifiable`, as before.

A contract-mode claim whose expected value is not even a rounding of the cited
evidence, such as a percentage that cites a count cell, uses the same single
repair attempt with the `claim_value_mismatch` category. A value that equals the
evidence rounded to the claim's own decimal places is not rejected here; it
reaches verification unchanged, so rounding policies apply and genuine
contradictions are still reported.

### Final-value recovery query

In contract mode, a finished synthesis whose evidence lacks the requested final
value gets one recovery query, if an analytical step remains. The triggers are a
terminal `invalid_claim_reference` or `claim_value_mismatch` failure, or a
complete synthesis with empty claims. The recovery query plans the original
question, asking for each value the claim needs as its own numeric result
column. Synthesis then runs once more on all observations, without another
investigator decision. Recovery happens at most once per investigation.

The result records it as `synthesis_recovery`, with `trigger`,
`repair_attempted` from the first synthesis, and `query_succeeded`. If the
recovery query fails, the first outcome is returned with the failed attempt
added to its history. If it succeeds, the new synthesis replaces the first one,
and only the safe categories above describe the replaced outcome. Recovery
uses the normal step budget and shared deadline, and the final claims are
verified exactly as before.

If evidence is insufficient, empty claims remain allowed; they cannot pass a
nonempty output contract. The system does not force a numerical assertion to
fill the required count. Repeated shape failure produces an incomplete result
with SQL observations retained and synthesis failure metadata. Numerical
contradictions that are a rounding of the cited evidence do not trigger
shape repair. Provider failures and the shared
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

If the repair attempt also fails for unlinked numbers, the terminal
`synthesis_failure` keeps the same bounded `unlinked_numeric_values`, so the
rejected quantities can be diagnosed without storing the rejected conclusion.
It is empty for other failure reasons.

A conclusion number is linked when it equals a claim's expected value, one of
the two cells a `difference` claim subtracts, or either of those rounded to the
number's own decimal places, such as `3851.41` for `3851.4105577…`. Data labels
that mix letters and digits and come from the question or the evidence, such as
`VVS1`, or hyphenated ones such as `PG-13` and `COVID-19`, are not treated as
numbers. A hyphenated label is compared whole, and one that appears in neither
the question nor the evidence still counts. Every accepted number still traces to a
claim or the evidence cells it cites.

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
The review does not rewrite SQL, run extra SQL, call a model, or change claim
acceptance. It changes the CLI exit status only when a requested metric display
is withheld; see [Metric displays and advisory reviews](#metric-displays-and-advisory-reviews).

The heuristic compares exact case-insensitive category mentions in the original
question with bounded observed string values and simple SQL filters. A regular
English plural of a value's last word also counts as a mention, so `earthquakes`
names `Earthquake` and `categories` names `Category`. The values come from a
review-only list of up to 200 distinct strings per column (64 KiB in total) that
is never sent to a model; the smaller prompt list is used only when the review
list is unavailable. It handles
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
for this first version. Two narrow refinements apply. Words in the `as ...`
complement of a reporting instruction, such as `Report it as a single number`,
describe the answer's form and are not category mentions. When one mentioned
value is shared by several columns, it is attributed to a single column only if
the question names that column for it, as in `loan is yes`,
`default status is no` or `loan = 'yes'`. No status establishes intended business
meaning.

The review also warns, with the code `total_rows_not_excluded`, when an aggregate
over one directly queried table never references a column that holds detected
total rows (see the `total_row` data-quality finding). Such a query neither
filters nor groups by that column, so it may add each total to its own parts.

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

The check does not rewrite SQL, run additional queries, call a model or change
acceptance. Like population review, it withholds a requested metric display.
Its metadata is excluded from synthesis
prompts. Every status retains `task_semantics_verified=false`. This is a narrow
advisory, not autonomous enforcement of analytical grain.


## Metric displays and advisory reviews

`--metric-description LABEL COUNTING_UNIT UNIT` (Python: `render_metric`)
prints one supported VALUE cell with caller-supplied wording. Select another
claim with `--metric-claim-index`. The wording stays local; it is never sent to a
provider and is not checked against the executed SQL.

Every investigation report includes `advisory_reviews`, listing the zero-based
observations whose population or counting-grain review is `review_required`.
An empty list means no built-in heuristic raised a warning; unassessed queries
also produce no warning, so this is not a verification of population or grain.

A caller-worded display would present a value with more authority than its
evidence supports when the selected claim's observation is flagged. In that case
`render_metric` raises `MetricReviewRequiredError` and the CLI reports
`metric_display: null`, `metric_display_status: "review_required"` and exits 1.
Workflow status, numerical verdicts, output-contract acceptance and the retained
evidence are unchanged. Without `--metric-description`, advisory reviews do not
change the exit status. Flags on other observations do not block a display of
an unflagged claim, but they remain listed in `advisory_reviews`.