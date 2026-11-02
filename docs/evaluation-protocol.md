# Fixed local CLI evaluation protocol

## Purpose and status

This protocol evaluates the existing local CLI without changing production
reasoning, SQL validation, numerical verification, or output acceptance.

It separates:

- Provider and process availability.
- Workflow completion.
- Numerical support against referenced evidence.
- Correctness against independent fixture answers.
- Caller-selected claim output acceptance.
- Compliance with the requested analytical task.

These cases are synthetic development evaluations. They are visible to the
developer and must not be described as a private held-out benchmark.

The protocol defines one initial six-case batch. No live results are implied
by this document. Passing it does not establish general analytical reliability,
hosted deployment readiness, or support for arbitrary file structures.

VeriSight remains domain-independent within its supported data contracts.
Fixture-specific answers and acceptance rules belong to evaluation only.

## Freeze before execution

Before the first provider call:

1. Commit the protocol, fixture definitions, and evaluation runner.
2. Select one clean implementation revision.
3. Materialize the exact fixtures and questions below.
4. Record a manifest containing the revision, questions, fixture hashes,
   configuration, independent answers, and acceptance requirements.
5. Review the manifest and run all offline controls.
6. Preserve the manifest unchanged throughout the batch.

A fixture or question change creates a new protocol version. An implementation
change requires a new batch. Never silently continue an old batch against new
code.

Hash the actual UTF-8 fixture and manifest bytes. Write evaluation-created text
with LF newlines explicitly. Record encoding and newline conventions.

Preserve historical report hashes. Do not replace earlier CRLF fingerprints
with hashes of normalized or reserialized content.

## Fixed execution policy

Run the six cases once each, in the order listed here.

| Setting | Value |
| --- | --- |
| Interface | Installed `verisight investigate` CLI |
| Model | `gemini-3.1-flash-lite` |
| Whole-case attempts | One |
| Application provider retries | One, as configured by the current CLI |
| Request timeout | 30 seconds |
| Shared investigation budget | 90 seconds |
| Outer CLI process timeout | 150 seconds |
| Analytical attempts | One, except the ordered-measurement case uses two |
| Result row limit | 20, as configured by the current CLI |
| Other execution limits | Explicitly recorded from the effective configuration |
| Live disclosure | Only the synthetic fixtures defined here |

The model identifier is a frozen requested configuration, not a guarantee of
availability or an immutable provider implementation.

Record all inherited settings that affect execution. Do not allow unrelated
environment variables to change limits silently.

The outer timeout includes CLI startup and preliminary inspection. The shared
investigation deadline starts later and is not the same boundary.

Stop the launched process if the outer timeout expires. Retain available
artifacts and classify the attempt as an outer timeout. Do not describe that
event as proof that application cancellation worked.

Do not retry a whole case because of HTTP 429/503, malformed output, an
incorrect answer, output rejection, or an incomplete workflow.

A later diagnostic retry is a separate batch with a separate identifier.
Preserve the original result.

## Environment record

Record before execution:

- Exact Git revision and tracked-change status.
- Python version, OS, and architecture.
- VeriSight package version and installed CLI location.
- DuckDB, SQLGlot, pandas, NumPy, Google GenAI, HTTPX, Pydantic,
  pydantic-settings, openpyxl, and xlrd versions.
- Requested model and any model-version information actually returned.
- Effective provider retry, request, investigation, SQL, row, byte,
  memory, temporary-storage, and upload limits.
- Fixture, population, and manifest hashes.
- Runner version and start time in UTC.

Use an explicit package-version allowlist. Do not collect environment-variable
dumps, credentials, `.env` contents, or authenticated package-index URLs.

Dependency versions describe the observed environment. Without a lock or
equivalent environment specification, they do not guarantee recreation.

## Case 1: weighted eligibility

File: `weighted.csv`

```csv
id,state,weight,reading
a,accepted,2,7
b,accepted,6,3
c,rejected,100,99
d,accepted,0,500
e,accepted,-1,100
f,accepted,8,
```

Question:

> What is the weighted mean reading among accepted records with strictly
> positive weight and a non-missing reading? Use the same eligible records
> in numerator and denominator. Compute the final metric in one analytical
> query. Report only the final metric as exactly one VALUE claim referencing
> its result cell.

CLI contract: `--require-claim value`

Population: none.

Independent answer:

`(2 * 7 + 6 * 3) / (2 + 6) = 4`

SQL control:

```sql
SELECT
    SUM(weight * reading) / NULLIF(SUM(weight), 0) AS answer
FROM weighted
WHERE state = 'accepted'
  AND weight > 0
  AND reading IS NOT NULL
```

Task acceptance requires the same eligible population in both sums and the
final weighted mean in a result cell. Components alone are insufficient.

## Case 2: membership without join multiplication

File: `entries.csv`

```csv
id,state,amount
a,posted,45
b,posted,-5
c,posted,10
d,pending,100
```

File: `labels.csv`

```csv
id,label
a,eligible
a,eligible
b,eligible
c,other
d,eligible
```

Question:

> Sum the amount of posted entries whose ID has at least one eligible label.
> Count each entry once even when its label is repeated. Use one analytical
> query. Report only the final metric as exactly one VALUE claim referencing
> its result cell.

CLI contract: `--require-claim value`

Population: none.

Independent answer:

`45 + (-5) = 40`

SQL control:

```sql
SELECT SUM(amount) AS answer
FROM entries
WHERE state = 'posted'
  AND id IN (
      SELECT id
      FROM labels
      WHERE label = 'eligible'
  )
```

Task acceptance requires membership semantics without multiplication from
duplicate label rows. An ordinary multiplying join is incorrect even if an
unrelated adjustment happens to produce the expected scalar.

## Shared fixture for cases 3 and 4

File: `members.csv`

```csv
person,state,cohort,outcome
u1,active,2029,complete
u1,active,2029,complete
u2,active,2029,incomplete
u3,active,2029,complete
u4,active,2029,incomplete
u5,paused,2029,complete
u6,cancelled,2029,complete
u7,active,2029,
u8,active,2028,complete
```

Each person has a consistent known outcome in this fixture. The duplicate
u1 row tests identity counting, not conflict resolution between outcomes.

## Case 3: autonomous exact population

Question:

> Among distinct people with state exactly active in cohort 2029 and an
> outcome of complete or incomplete, what percentage have outcome complete?
> Exclude every other state, cohort, and missing outcome. Count people,
> not rows. Compute the final percentage in one analytical query. Report
> only that percentage as exactly one VALUE claim referencing its result
> cell. Do not repeat contextual numbers in the conclusion.

CLI contract: `--require-claim value`

Population: none.

Independent answer:

`100 * 2 / 4 = 50`

SQL control:

```sql
SELECT
    100.0 * COUNT(DISTINCT CASE
        WHEN outcome = 'complete' THEN person
    END) / NULLIF(COUNT(DISTINCT person), 0) AS answer
FROM members
WHERE state = 'active'
  AND cohort = 2029
  AND outcome IN ('complete', 'incomplete')
```

Task acceptance requires exact active status, the requested cohort, known
outcomes, distinct identities, and percentage scaling.

Replacing exact active status with non-cancelled status produces 60 here.
Counting eligible rows instead of people also produces 60. Both are incorrect.

## Case 4: caller-selected population

Use exactly the question from case 3.

CLI contract: `--require-claim value`

Additional population file: `population.json`

```json
[
  {
    "relation": "members",
    "column": "state",
    "values": ["active"]
  },
  {
    "relation": "members",
    "column": "cohort",
    "values": [2029]
  },
  {
    "relation": "members",
    "column": "outcome",
    "values": ["complete", "incomplete"]
  }
]
```

Independent answer: `50`

Control SQL, executed with the supplied population:

```sql
SELECT
    100.0 * COUNT(DISTINCT CASE
        WHEN outcome = 'complete' THEN person
    END) / NULLIF(COUNT(DISTINCT person), 0) AS answer
FROM members
```

Task acceptance requires the exported requested and applied populations to
match the supplied policy, together with distinct counting and scaling.

This is a caller-constrained task. Report it separately from autonomous
population interpretation in case 3.

The broad offline control checks enforcement when SQL omits the filters.
A live query that independently includes the same filters does not isolate
the enforcement mechanism.

## Case 5: ordered measurements

File: `flows.csv`

```csv
id,period,state,litres
a,before,accepted,25
b,before,accepted,55
c,after,accepted,100
d,after,accepted,20
e,after,rejected,999
f,other,accepted,700
```

Question:

> Use two separate analytical queries. First measure total litres where
> period is before and state is exactly accepted. Then measure total litres
> where period is after and state is exactly accepted. Exclude other periods.
> Report only after minus before, in litres, as exactly one DIFFERENCE claim
> referencing the two observed totals. Do not add component VALUE claims or
> report component totals in the conclusion.

CLI contract: `--require-claim difference`

Analytical attempts: two.

Population: none.

Independent arithmetic:

- Before: `25 + 55 = 80`
- After: `100 + 20 = 120`
- Difference: `120 - 80 = 40`

First SQL control:

```sql
SELECT SUM(litres) AS answer
FROM flows
WHERE period = 'before'
  AND state = 'accepted'
```

Second SQL control:

```sql
SELECT SUM(litres) AS answer
FROM flows
WHERE period = 'after'
  AND state = 'accepted'
```

Task acceptance requires two successful analytical observations in the requested
order. Each must measure its requested total. A single grouped query does not
satisfy the explicit procedure.

The DIFFERENCE claim must reference after on the left and before on the right.
Additional claims or component totals in the conclusion violate output scope.

Equivalent safe SQL is allowed. Do not require textual equality with controls.

## Case 6: unavailable denominator

File: `events.csv`

```csv
event,status
e1,converted
e2,converted
e3,converted
```

Question:

> What percentage of all exposed people converted? This file records
> conversion events only and does not contain exposed-person counts or
> person identities. If the requested percentage cannot be determined,
> explain the missing evidence and return no numerical claims. Do not
> substitute the percentage of rows marked converted.

Analytical attempts: at most one.

Population: none.

CLI claim contract: none. The existing nonempty claim contract cannot express
an expected absence of claims.

Independent answer: not identifiable from the supplied data.

The three events could belong to different people or repeated events for one
person. Neither the distinct converted-person count nor exposed-person
denominator is established.

Task acceptance requires no numerical claims and an explicit explanation of
the missing person-level numerator and exposed-person denominator.

No-claims output alone is insufficient. A provider error, unrelated refusal,
or empty response is not a justified abstention.

A complete or incomplete workflow can preserve a justified abstention.
Record workflow status separately; do not change it to make the case pass.

## Offline preparation checks

Before live execution:

- Load every fixture through the public facade.
- Check inferred schemas and exact relation names.
- Execute the supplied numeric controls.
- Compare control values with independent arithmetic.
- Execute the broad population control with the supplied policy.
- Confirm the installed CLI accepts selected budgets and claim contracts.
- Preview all six requests without model calls.
- Confirm questions sent to generation contain no control SQL or oracle answer.
- Verify that the runner preserves failure artifacts and distinguishes process
  failure, workflow status, output acceptance, and task assessment.

Any failed preparation check blocks the batch. Retain its evidence and correct
the preparation problem before freezing a new manifest.

## Evidence retained for every attempt

Use one new directory per batch and one directory per case. Never overwrite
an earlier run.

Retain:

- Frozen manifest and fixture files.
- CLI arguments with credentials excluded.
- Original exported report bytes and SHA-256 hash.
- Standard output and standard error.
- Process exit code, start time, elapsed time, and timeout classification.
- Any available partial report.
- Automatic checks and a separate reviewed task assessment.

Logs and exports can contain questions, SQL, and source values. Use only these
synthetic inputs and review artifacts before committing.

If paths are made portable in a repository copy, preserve the original export
hash and document exactly which fields changed.

## Assessment rules

For each case, record separately:

| Dimension | Assessment |
| --- | --- |
| Process | Finished, outer timeout, launch failure, or interrupted |
| Provider failure | Reported stage and safe diagnostics when available |
| Workflow | Original complete/incomplete status or no result |
| Numerical support | Original verification results |
| Independent answer | Correct, incorrect, unavailable, or not applicable |
| Claim output contract | Accepted, rejected, unavailable, or not selected |
| Analytical requirements | Pass, fail, or unresolved, with evidence |
| Task outcome | Accepted answer, justified abstention, rejected, or unresolved |

For numeric cases, independent correctness uses zero tolerance for these exact
fixture answers. Do not introduce rounding or widen tolerances after a failure.

Review SQL, observations, claim references, and conclusion. Correct scalar
output alone cannot establish the right method.

An unresolved task review is not a pass. Preserve uncertainty rather than
inventing an automated semantic verdict.

Evaluate requirements independently. For example, three claims can fail claim
cardinality while the DIFFERENCE arithmetic and reference order remain correct.
Do not skip those checks because another check already failed.

Never modify original workflow statuses, numerical verdicts, CLI exit codes,
or automatic scores during review. Add the reviewed assessment separately.

## Reporting and decision

Report all six attempts with explicit denominators.

Report autonomous and caller-scoped population results separately, despite
sharing a fixture. Do not treat those cases as independent evidence of broad
domain coverage.

Distinguish:

- Five numeric-answer cases.
- One insufficient-evidence case.
- Process completion.
- Workflow completion.
- Independent numeric correctness.
- Output-contract acceptance.
- Full reviewed task acceptance.
- End-to-end elapsed time and provider failures.

For this small batch, show individual latencies and their range. Do not present
a six-case tail-latency estimate as a production service-level measurement.

The milestone passes only if all five numeric tasks satisfy their independent
answers and full task requirements, and the insufficient-evidence task produces
a justified abstention.

A failed or unavailable case means the milestone is not demonstrated by this
batch. Diagnose it from retained evidence rather than selecting a successful
whole-case retry.

Passing this milestone establishes these six development workflows only.
It does not authorize an accuracy percentage for unfamiliar user data.

The supplied SQL queries are deterministic controls, not a competing AI-system
baseline. A comparative performance claim requires a separately frozen baseline
with comparable inputs, budgets, and assessment rules.

A later release evaluation needs independently prepared, previously unused
cases and release targets fixed before results are inspected. Cases used to
tune VeriSight become development cases.