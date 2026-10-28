# Controlled analytical correctness evaluation

## Scope and commands

`tests/test_analytical_correctness_benchmark.py` adds ten synthetic question
fixtures across five domains. Each has a control query and an intentionally
incorrect query, producing twenty pipeline tests.

```powershell
python -m pytest tests/test_analytical_correctness_benchmark.py -q
python -m pytest tests/test_verification_benchmark.py tests/test_analytical_correctness_benchmark.py -q
```

The tests use real CSV ingestion, schema/profiling, SQL validation, DuckDB
execution, structured synthesis parsing, numerical verification, serialization,
and evaluation scoring. Planning and investigator decisions are scripted, and
the synthesis provider is replaced with deterministic text. No API calls occur.

These are known development fixtures, not a held-out benchmark or a measurement
of a model's ability to generate SQL.

## Independent answers

Expected answers are fixed with each fixture. They are not calculated from the
query output or generated claim. The following arithmetic explains the oracle
in the metric's stated units.

| Fixture | Independent calculation | Correct answer | Wrong-query answer |
| --- | --- | --- | --- |
| Signed posted transaction mean | `(0.5 - 0.25 + 1.25) / 3` | `0.5` | `0.875` |
| Principal-weighted annual rate | `(1000 * 1.5 + 3000 * 2.5) / 4000` | `2.25` | `2` |
| Recorded completed wait mean | `(1.25 + 2.5) / 2` | `1.875` | `1.25` |
| Patients with a readmission | `100 * 3 / 8` distinct patients | `37.5` | `50` |
| Order totals counted once | `10.5 + 10.5 + 20.25` | `41.25` | `62.25` |
| Selling price per unit | `(1 * 10.5 + 3 * 20.5) / 4` | `18` | `15.5` |
| Known inspection defect rate | `100 * 3 / 8` known outcomes | `37.5` | `30` |
| Pooled batch defect rate | `100 * 1 / (2 + 6)` | `12.5` | `25` |
| Mean signed delivered delay | `(0.5 + 1.5 - 0.25 + 0.25) / 4` | `0.5` | `0.625` |
| Pooled route on-time rate | `100 * (1 + 1 + 1 + 0) / (1 + 1 + 2 + 4)` | `37.5` | `62.5` |

The errors deliberately change analytical meaning: dropping refunds, ignoring
weights, imputing missing waits as zero, counting encounters instead of patients,
multiplying order totals through joins, including unknown outcomes, averaging
batch/route percentages without weights, and losing the sign of early arrivals.

The repeated `10.5` order totals are intentional. Equal values belong to distinct
orders; deduplicating amounts is not equivalent to deduplicating order identities.

All expected answers in this increment have finite decimal representations.
No comparison tolerance, presentation-rounding policy, or SQL rounding is used
to hide discrepancies.

## Control baseline and acceptance

The baseline is explicitly supplied control SQL for each question. The alternate
SQL is an injected semantic error. This is not a comparison against another AI
system or an independently implemented analyst.

Both synthesis responses accurately repeat their respective query cells. The
numerical verifier must therefore return `supported` for both paths. The
independent oracle and evaluator must distinguish them:

| Path | Evidence verdict | Ground-truth agreement | Evaluation outcome |
| --- | --- | --- | --- |
| Control query | `supported` | Yes | `correct_numeric` |
| Incorrect query | `supported` | No | `incorrect_numeric` |

Both paths can have zero unlinked tokens and `all_digits_parsed`. Neither
condition establishes analytical correctness. Narrative verification remains
false. Original SQL, numerical evidence, and verdicts survive serialization.

The tests fail if either SQL path produces a value other than its independently
specified fixture value, if an incorrect answer is scored as correct, or if
claim/evidence checks stop reflecting the executed result.

## Bounded multi-step benchmark

`tests/test_multistep_correctness_benchmark.py` adds five scripted investigations
with three successful SQL observations each: a broad intermediate metric, the
included before-period metric, and the included after-period metric.

```powershell
python -m pytest tests/test_multistep_correctness_benchmark.py -q
```

Every observation is checked against independently specified fixture values.
The final claim is a difference across observation references, not a newly
executed change query. Correct references use after minus before.

| Domain | Included before | Included after | Correct change | Broad metric | Wrong broad-minus-before change |
| --- | --- | --- | --- | --- | --- |
| Finance, posted amount | `10.5` | `12.25` | `1.75` | `122.75` | `112.25` |
| Healthcare, completed wait mean | `1.875` | `3.75` | `1.875` | `22.25` | `20.375` |
| Retail, paid order total | `30.75` | `40.75` | `10` | `171.5` | `140.75` |
| Manufacturing, defect percentage | `37.5` | `12.5` | `-25` | `40` | `2.5` |
| Logistics, on-time percentage | `50` | `62.5` | `12.5` | `80` | `30` |

Percentage changes here are percentage-point differences, not relative changes.
The broad metric intentionally includes both periods and excluded records.

Four final-claim modes are tested per fixture:

- Correct references and answer: supported and equal to the independent change.
- Broad intermediate observation used as the after value: supported but wrong
  against the independent change.
- Reversed references with the correct claimed change: contradicted.
- A nonexistent observation reference: unverifiable.

Another four paths per fixture stop on a two-attempt budget, an investigator
outage, a planning outage, or a synthesis outage. They assert bounded calls,
ordered retained observations, incomplete status, empty claim lists, available
safe failure metadata, and serialization without raw provider error text.
The budget test prevents the third query from executing. It does not prevent
the investigator from making the next decision.

This adds forty offline tests. Planning, decisions, and synthesis remain
scripted. The tests establish cross-observation plumbing, numerical verdicts,
independent-answer distinctions, and failure recovery; they do not establish
autonomous hypothesis formation or semantic error detection.

The live evaluator currently scores one VALUE claim. These multi-step DIFFERENCE
claims are checked directly against their independent fixture oracle; the live
runner and its scoring contract are not expanded by this test module.

## Live schema challenge suite

The opt-in runner adds three synthetic development cases under `--case challenge`.
The original `--case all` still selects the original five cases. Individual
challenge names can be selected to fit provider request limits.

| Case | Analytical requirement | Independent calculation | Expected |
| --- | --- | --- | --- |
| `energy_grain` | Include production readings with an approved review; count each reading identity once | `11.25 + 11.25 + 7.5` kWh | `30` |
| `research_weighted` | Accepted assays with known percentage and positive known mass; weight by mass | `(100 * 1 + 300 * 3) / 400` percentage units | `2.5` |
| `education_entities` | Active learners in cohort 2026 with known outcomes; count identities rather than enrolment rows | `100 * 3 / 8` percent | `37.5` |

The energy fixture has repeated approved reviews and distinct readings with
equal output. Summing a raw join or deduplicating output values gives a wrong
answer. The research fixture includes unknown mass/assay values, zero mass, and
a rejected sample. The education fixture repeats one learner and includes a
cancelled enrolment, an unknown outcome, another cohort, and two waitlisted
learners with known outcomes (one complete and one incomplete). Only the eight
active learners with known outcomes are eligible, of whom three completed.
Replacing the required active-only filter with merely not-cancelled includes
the waitlisted learners and returns `100 * 4 / 10 = 40`, rather than `37.5`.
This counterexample distinguishes explicit inclusion from exclusion. Earlier
committed reports used the fixture without these two waitlisted rows; compare
fixture definitions at each recorded revision before comparing results.

Answers are specified before execution. Supplied control SQL must produce one
finite numerical cell and match the independent answer before the model runs.
A disagreement produces `baseline_error` and skips generation. Control execution
errors remain classified application failures. A successful control report is
retained even when subsequent model generation fails.

`control_baseline` records its kind, expected and actual values, outcome, and
elapsed time. It is a supplied-query control through the same ingestion and SQL
engine, not an independent implementation or a competing model. The arithmetic
above is the independent oracle. The control SQL, its result, and the oracle are
not inserted into the investigator's question or observations.

When an investigation returns a result, `run_case()` also saves
`synthetic_evidence`: the investigation question and generated conclusion,
ordered observations with their analytical questions, SQL, and result rows,
plus claims, evidence references, and verification values/verdicts/reasons.
Compare the investigation question, observation question, and SQL to locate
where requested population, units, or other constraints were lost. The
conclusion permits inspection of unlinked narrative tokens; its inclusion does
not certify the prose. The observation question is the validated plan question;
it is not a complete trace of investigator reasoning or failed decisions.
Decimal values remain strings. The report's top-level `expected` is the fixture
oracle; a verification's `expected` is the model's claimed value. Inspect both
before deciding whether a failure concerns query semantics, references, or
synthesis. Incomplete results retain whatever evidence and claims are available.
Escaping exceptions before a result exists cannot supply this evidence.

This content-bearing evidence is confined to the synthetic runner; the reusable
`score_result()` stays a summary without questions, conclusion, SQL, or claim
details. Full analysis, prompts, credentials, and raw provider errors are not
added to the evidence field. Generated questions, conclusion, SQL, and result
cells still require review before publication. Do not repurpose this reporting
path for private datasets without an explicit disclosure policy. Older saved
reports cannot recover omitted values.

The live path uses default planning, investigation, and structured synthesis.
It still allows one analytical attempt and asks for one final VALUE claim.
These cases test generated analytical SQL, not autonomous multi-step reasoning.
No rounding tolerance is used; all three answers have finite decimal forms.

After offline gates pass, commit the fixture definitions before live execution.
Confirm no tracked changes with `git status --porcelain --untracked-files=no`.
Local untracked datasets are not part of the synthetic fixtures. Run one case
at a time if provider limits make a combined run impractical:

```powershell
New-Item -ItemType Directory -Force reports/evaluations | Out-Null
$evaluationStamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
python -m scripts.live_evaluation --live --case energy_grain --request-timeout-seconds 60 --provider-retries 1 --output "reports/evaluations/energy-grain-$evaluationStamp.json"
```

Select `research_weighted` or `education_entities` for the other cases. A single
`--case challenge` run selects all three under the same revision and settings.
No pacing between provider calls is added by this increment. A 429 may reflect
minute or daily limits; repeated immediate runs do not resolve exhausted quota.

Retain every attempt, including failed controls, provider errors, incomplete
results, and repeated runs. For this suite, report:

- Exact correct supported answers divided by all attempted cases.
- Incorrect supported answers separately from contradicted/unverifiable claims.
- Provider failures, application/control failures, and incomplete workflows.
- Case elapsed time and retry attempts where telemetry exists.

Case elapsed time includes control execution and investigation. Control timing
alone is not a comparable model-performance latency baseline. Do not select the
best retry per case and call that an overall success rate.

These fixtures are public development cases. They are not held out once used
to guide implementation, and three cases cannot establish cross-domain accuracy.
Claims about a live outcome must identify the report and tested revision.

## Retained live and CLI evidence checkpoints

The repository retains both successful and unsuccessful development runs.
The following records illustrate different outcomes; they are not a comparable
single-revision benchmark and must not be pooled into a success rate.

| Record | Tested revision | Observed result | Limit |
| --- | --- | --- | --- |
| [Education scope retry](../reports/evaluations/education-scope-retry-20261023-234139-577.json) | `c8bf4c0` | Supported `40.0` from non-cancelled learners; independent active-only answer `37.5` | Original-question propagation did not prevent population error |
| [Caller-scoped education](../reports/evaluations/education-caller-scoped-20261024-085546-292.json) | `34c3f30` | Caller-filtered answer `37.5`; broad SQL boundary control also restricted | Tests supplied scope, not autonomous population selection |
| [Posted CLI validation](../reports/evaluations/cli-posted-validation-20261024.json) | `939df6a` | Supported final sum `80` through the installed CLI | Generated SQL also supplied the filter; not an omitted-filter enforcement test |
| [Fixed four-case CLI batch](../reports/evaluations/fixed-cli-batch-20261024.json) | `46da4c9` | Freight `200` and programme `37.5` correctly grounded; orchard final `2.75` unlinked; reservoir incomplete after HTTP 429 | Known frozen fixtures; all original outcomes retained |
| [Orchard final metric recheck](../reports/evaluations/orchard-final-metric-recheck-20261024.json) | `78adc5e` | Final SQL cell and one supported VALUE claim `2.75` | Several implementation changes and model variation prevent causal attribution |
| [Reservoir contract recheck](../reports/evaluations/reservoir-contract-recheck-20261024.json) | `cc90792` | Supported difference `50`, but one grouped query included another period and three claims | Requested procedure and output contract unmet |
| [Reservoir procedure recheck](../reports/evaluations/reservoir-procedure-policy-recheck-20261024.json) | `5474cee` | Two ordered queries and supported after-minus-before `50`; still three claims | Requested single-claim output unmet; full task acceptance failed |

The last reservoir record preserves an automatic-check defect alongside a
separate reviewed correction. The runner only assessed difference support and
reference order when exactly one claim existed. Its false flags therefore
conflated claim count with independent arithmetic/reference checks. The reviewed
assessment confirms supported arithmetic and correct reference order while still
rejecting the output contract. Preserve both the original and the correction.

These historical reports predate the caller-selected claim output gate. Offline
replay can show that the gate rejects the recorded extra claims; it is not a
new provider run or proof that generation now satisfies the contract. Do not
retroactively rewrite report outcomes or assign new CLI exit codes to old runs.

## Reviewed local contract diagnostics and synthesis replay

The following checkpoints summarize reviewed Windows terminal output from
October 27–28, 2026. Their original reports, logs, and replay record remain in
the local temporary validation directories; those raw artifacts are not
committed with this summary. This section is a transcription of reviewed
results, not a replacement for those artifacts or a complete request trace.
The frozen synthetic task comes from `reservoir_two_queries` in the existing
[fixed CLI batch](../reports/evaluations/fixed-cli-batch-20261024.json).

The task requests separate before and after queries, accepted readings only,
other periods excluded, and exactly one final DIFFERENCE claim. Independent
CSV arithmetic gives before `100`, after `150`, and after minus before `50`
litres. The fixture's UTF-8 LF byte SHA-256 is
`92e923a4e027cdde97e90df27db66718d71e93c45c3e2d1fbae047cbcaf5ff7f`.
These checkpoints used `gemini-3.1-flash-lite`, no caller-selected population,
a DIFFERENCE output contract, request timeout 60 seconds, and shared budget
120 seconds. Full investigations allowed two analytical attempts; the replay
below performed no investigation decisions, planning, or SQL execution.

| Tested revision | Validation path | Observed outcome | Elapsed seconds |
| --- | --- | --- | --- |
| `bfba4ce` | Full CLI investigation | Correct ordered totals and supported difference, but three claims; output contract rejected, exit 1 | `76.164` |
| `aa6f51b` | Full CLI recheck | Correct ordered totals; incomplete with generic synthesis error and no claims, exit 1; terminal validation category unavailable | `42.314` |
| `001bb56` | Full CLI diagnostic recheck | Correct ordered totals; repaired synthesis failed `unlinked_narrative_number`, with `repair_attempted=true`; no claims, exit 1 | `49.859` |
| `a89ba7d` | Full CLI recheck | Only before `100` retained; investigation budget exhausted, no final claims, exit 1 | `122.209` |
| `a89ba7d` | Separate CLI invocation with telemetry | First investigator generation returned no text after two provider attempts; `provider_unavailable`, exit 1 | `11.729` |
| `3c60ea1` | Synthesis-only retained-evidence replay | One supported DIFFERENCE claim `50`, correct after-minus-before references, final-only numerical conclusion, output assessment accepted | `16.862` |

The two `a89ba7d` attempts are distinct. The telemetry attempt recorded one
investigator call lasting `9.693` seconds, including its two provider attempts.
It does not explain the preceding run's timeout. An `operation_error` report
has no request payload: comparing its missing request with the submitted one
does not establish that the submitted request changed. Missing failure fields
in the earlier deadline result do not identify which stage consumed its budget.

The successful replay at full revision
`3c60ea18392f7e208e5b2bda6596ace7cb008572` reused the two retained observations
from the `001bb56` run. It loaded the verified synthetic input for offline
analysis and supplied the original question and selected output contract to the
configured structured synthesizer. The retained SQL was not rerun. The replay
checked the referenced values against independent CSV arithmetic.

Telemetry recorded exactly one `structured_synthesis` generation call, one
provider attempt, `returned_text=true`, and `16.860` call seconds. No format
repair was needed. Its single claim referenced observation index 1 (after) as
left and observation index 0 (before) as right; actual and expected were `50`
at zero tolerance. The conclusion reported only `50` litres. The assessment
had no violations and retained `task_semantics_verified=false`. This standalone
replay did not invoke the CLI and has no CLI exit-code claim.

This is one successful live synthesis from known development evidence. It does
not establish end-to-end investigation success, live format-repair effectiveness,
repeatable compliance, unfamiliar-data accuracy, or a causal effect of the
implementation change. Preserve all preceding failures; do not pool these
different revisions and invocation paths into a success rate. Further changes
to synthesis are not justified solely by this successful replay.

## Scorer, output acceptance, and semantic review

`score_result()` requires a complete result with exactly one supported VALUE
claim and compares its actual value to the independent fixture answer.
It does not require clean narrative audits or independently inspect SQL meaning.
A coincidentally correct answer can pass despite a wrong analytical method.

The optional CLI `--require-claim` gate and Python `assess_output()` method check
exact claim-operation multiplicities, numerical support, completion, linkage,
and digit coverage. They have no fixture answer and do not establish correct
populations, units, query procedures, or narrative semantics. The live evaluation
runner does not invoke this gate. See [Output contracts](output-contracts.md).

Keep separate fields or reviewed assessments for workflow completion, provider
availability, numerical support, independent numeric correctness, output
acceptance, and procedural/semantic requirements. Do not use a supported claim
or an accepted output shape as a substitute for the independent oracle.

## Repeatable evaluation protocol still required

Before a release evaluation, freeze and record:

1. One implementation revision, fixture definitions, questions, independent
   numeric answers, and separate procedural acceptance rules. Distinguish
   caller-selected populations from unscoped interpretation tasks.
2. Model, request/retry/step/shared-time limits, execution limits, Python and
   dependency versions, OS, and relevant configuration. There is no committed
   dependency lock; current reports do not capture the complete environment.
3. A fixed attempt policy, release targets, and a meaningful model/system
   baseline before inspecting held-out results. Supplied SQL remains a control.
4. All attempts, including provider errors, incomplete results, incorrect
   supported answers, invalid output, and failed controls. Keep numerators and
   denominators explicit; do not select the best retry.
5. Independent review of populations, grain, duplicates, weights, null handling,
   units, denominator, time period, requested procedure, and insufficient
   evidence. A final scalar alone cannot prove these properties.

Record raw fixture/manifest hashes with their encoding and newline convention.
The fixed batch's original Windows manifest used CRLF: reserializing equivalent
JSON with LF changes its byte hash. Preserve the original hash and record any
normalization separately rather than replacing historical fingerprints.

Use unfamiliar held-out tasks after development fixtures stop driving changes.
Any case used to tune implementation becomes development evidence. The current
manual batch records are useful diagnostics, not a reusable held-out harness.
No general release accuracy or production-readiness claim follows from them.

## Limits and next evaluation work

These tests establish controlled pipeline and scorer behavior. They do not show
that VeriSight detects bad SQL semantics autonomously, handles unfamiliar
schemas reliably, or generates useful follow-up investigations.

Next work includes unscripted multi-step evaluations, held-out fixtures,
insufficient-evidence cases, a defined model or system comparison, and
reproducible live runs. Report all attempted cases and distinguish provider
availability, completion, correctness, and latency. The live runner's five
default fixtures and the schema challenge suite remain separate from this
ten-question offline increment.

See [Development](development.md) for the full gate and live evaluation controls,
and [Architecture](architecture.md) for verification boundaries.