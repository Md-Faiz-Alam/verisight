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
expected value, and all digit characters must be covered by parsed tokens.
Question-context numbers are not exempt. These failures use the existing
`unlinked_narrative_number` category and share the single repair attempt with
schema and shape failures; they do not receive an additional attempt.
Repair instructions require removing prose numbers when their claims are removed,
unless another retained claim links them. Component cells remain referenced by
claims without repeating their values in final-only prose. Evidence can exist
without its numbers being permitted in the conclusion.

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

## Limits

The assessment scope is `claim_shape_and_numeric_evidence_only`, with
`task_semantics_verified=false`. Acceptance does not verify populations,
denominators, grain, units, query order, causal meaning, or narrative truth.
A plausible number from the wrong SQL can still pass.

Numeric-token checks inherit the existing audit's syntax limits. Number words,
repeated values, and semantic roles are not certified. Contextual numbers such
as years are rejected when they are detected and not linked to claims. The
built-in contract-mode synthesizer offers its bounded repair before returning
such a response. Calls without a contract retain their question-context allowance.
Do not add irrelevant claims merely to pass; keep final-only conclusions within
the requested output scope. A contract does not prove that prose reports only
the requested metric or that an absence of detected tokens means no assertion.

This mechanism is domain-independent and introduces no dataset-specific rules.