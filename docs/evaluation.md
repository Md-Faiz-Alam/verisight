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

The synthesis-only replay established successful synthesis from retained
development evidence. A subsequent full workflow through
`verisight.cli.main()` at revision
`58e22433eb5a0805a4a6cfacb8f19678e3b9b39a` completed successfully on
October 28, 2026. The exported request matched the offline preview, and the
CLI returned exit 0 after `75.753` seconds. Original reports and logs remain
in the existing temporary validation root's `full-cli-58e2243` directory.

Manual SQL review confirmed two separate queries in the requested order.
Accepted before readings summed to `100`; accepted after readings summed
to `150`. Both queries excluded rejected readings and other periods.
Neither query required SQL repair.

Exactly one supported DIFFERENCE claim referenced the after cell at
observation index 1, column `sum(litres)`, minus the before cell at
observation index 0, column `total_accepted_litres_before`. Actual and
expected were `50` at zero tolerance. The conclusion contained only the
final numerical difference in the context of accepted litres. Workflow
status was complete, the output assessment had no violations, and both
failure fields were null. The automatic assessment retained
`task_semantics_verified=false`; task acceptance here also relies on
manual review and independent fixture arithmetic.

Telemetry recorded seven generation calls: three investigator calls, two
generic text-generation calls, and two structured-synthesis calls. Every
call returned text using one provider attempt. The synthesis calls lasted
`3.328` and `2.754` seconds, consistent with successful completion through
the existing bounded format-repair path. The rejected response and its
validation category were not retained in the reviewed output, so the
specific repair reason is unknown. The second generic text-generation
call took `57.011` seconds and dominated elapsed time; this does not
identify a transport or provider cause.

This full run satisfies the requested task for one known synthetic
development fixture. It does not establish repeatable compliance,
unfamiliar-data accuracy, general semantic verification, or a causal
effect of an implementation change. Preserve all preceding failures;
do not pool different revisions and invocation paths into a success
rate. This successful validation alone does not justify another runtime
correction.

## Reviewed October 29 development checks

The following results come from reviewed PowerShell output. Original JSON
records and logs remain in the existing temporary validation directories.
They are not new committed reports or a single comparable benchmark. Repeated
read-only displays of the same saved record are not additional attempts.

### Learner population and bounded synthesis repair

At `9d1aa8c`, a full learner investigation generated the active-only query and
the independently correct `37.5` result, but synthesis remained incomplete.
Two diagnostic synthesis responses repeated the contextual year `2026`
without a corresponding claim and failed `unlinked_narrative_number`.
Correct SQL evidence therefore did not establish a completed answer.

Revision `33b8d4e` added bounded feedback identifying unlinked numeric values
during the existing single synthesis format-repair attempt. It did not change
SQL execution, numerical tolerance, or the validator's acceptance rules.

A separate full learner investigation at `33b8d4e` completed in `20.085`
seconds. It used `gemini-3.1-flash-lite`, a 30-second request limit, zero
provider retries, a 120-second shared budget, one analytical attempt, no
caller-selected population, and a one-VALUE output contract. Manual SQL review
confirmed cohort `2026`, explicit active-only inclusion, known outcomes, and
distinct learner identities. Independent arithmetic was `100 * 3 / 8 = 37.5`.

The final VALUE claim referenced the single `percentage completed` cell at
zero tolerance and was supported; the output assessment was accepted. Both
failure fields were null. Four generation calls returned text on their first
provider attempt: investigator, SQL planning, and two structured-synthesis
calls. The second synthesis call used the bounded format-repair path; the
first rejected response's validation category was not retained in this run.

The conclusion expressed the percentage in words. Its agreement with `37.5`
was manually reviewed; the numeric-token audit does not verify number words.
This is one successful unscoped development fixture, not proof that autonomous
population interpretation is generally corrected. The original supported
`40.0` population failures and the later synthesis failures remain failures.

### Three separate transfer fixtures

Offline preparation froze independent answers and discriminating incorrect
SQL controls before generation. The manifest and original batch remain under
the temporary directory `verisight-transfer-checks-33b8d4e`.

| Case | Independent answer | Deliberately incorrect control |
| --- | --- | --- |
| Latest version, then eligible | `60 + 60 - 15 = 105` units | Filtering eligibility before selecting latest versions gives `145` |
| Posted remittances with a clearance | `(1200 + 1200 - 325) / 100 = 20.75` | Multiplying repeated clearances gives `32.75`; deduplicating amounts gives `8.75` |
| Positive-mass weighted mean with known readings | `(2 * 10 + 3 * 20 + 1 * 40) / (2 + 3 + 1) = 20` | An unweighted mean gives about `23.3333`; including missing readings' mass gives about `8.5714` |

The original batch at `33b8d4e` used SDK `2.27.0`,
`gemini-3.1-flash-lite`, a 30-second request limit, zero provider retries,
a 120-second shared budget per case, one analytical attempt, no supplied
population, and exactly one final VALUE claim. Each case had one whole-case
attempt. Oracle values and control SQL were not sent to the model.

| Original batch case | Retained evidence and outcome | Elapsed seconds |
| --- | --- | --- |
| Latest version, then eligible | Correct SQL result `105`; incomplete after synthesis HTTP `500`, with no final claims | `35.554` |
| Membership without multiplication | Investigator provider failure before any SQL observation was retained; HTTP status unavailable | `30.430` |
| Weighted mean with missing readings | Investigator returned text; SQL-planning provider failure, with no SQL observation retained; HTTP status unavailable | `42.232` |

None of the three original cases completed. This is not a measurement of
zero analytical accuracy: two produced no SQL evidence, and the third had
correct SQL evidence but no completed synthesis.

Later checks are separate records, not replacements for that batch:

| Revision and check | Reviewed outcome | Elapsed seconds |
| --- | --- | --- |
| `33b8d4e`, separate full membership investigation | Complete; membership subquery avoided clearance multiplication, preserved equal-valued remittances and the negative amount, excluded missing amounts, and converted cents in SQL. One supported VALUE `20.75`; output accepted | `8.377` |
| `33b8d4e`, separate weighted diagnostic | SQL-planning HTTP `503` after the investigator returned text; no SQL observation or final answer | `30.898` |
| `7a91a83`, full weighted investigation with one configured provider retry | Complete; identical eligibility in numerator and denominator, supported final VALUE `20.0`, output accepted | `46.988` |
| `7a91a83`, latest-version synthesis-only recheck | Retained `105` evidence produced one supported VALUE and accepted output; SQL was not rerun | `7.118` |

The membership success used the original 30-second request limit and zero
provider retries. Its three generation calls each returned text on the first
attempt; neither SQL repair nor synthesis format repair was needed.

The two `7a91a83` checks used a 30-second request limit, one configured
provider retry with a one-second base delay, and a 120-second shared budget.
The weighted run's three generation calls all succeeded on their first
attempt. It therefore demonstrates no observed retry recovery or causal
benefit from enabling retries.

The latest-version recheck used one structured-synthesis call with two
provider attempts and no format repair. The initial attempt's failure
category was not retained. This was a production-synthesizer replay from
retained evidence, with SQL execution blocked; it is not a new full
investigation. The original latest-version batch outcome remains incomplete.

For the successful checks, numerical references and output shape passed,
while `task_semantics_verified` remained false. Task-specific acceptance also
relied on manual SQL review and independent fixture arithmetic. These known
development cases do not establish repeatability, held-out accuracy, or a
controlled effect of any implementation change. Do not pool their outcomes
across revisions, settings, or invocation paths into one success rate.

### Engineering checks are a separate kind of evidence

Revision `5317295` preserved datetime profiles when subtracting valid
endpoints overflows pandas' duration range. Earliest and latest values remain
available; the unavailable span is marked explicitly. Revision `7a91a83`
added allowlisted provider diagnostics to early public/CLI error exports
without changing retry policy or exposing raw provider messages.

At `7a91a83`, the reviewed Windows run reported 2,422 passing tests,
100% statement and branch coverage, clean Ruff checks, and strict mypy over
177 files. The
[corresponding CI run](https://github.com/Md-Faiz-Alam/verisight/actions/runs/40900013243)
passed on Windows and Ubuntu. These checks establish tested engineering
behavior, not analytical or narrative correctness.

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

## Recorded repeatability batch at revision 17d31bb

On October 30, 2026, a fixed batch ran ten attempts each of the
education, weighted-assay, and energy-grain development fixtures.
The order was education, weighted assay, then energy in each round.
All 30 scheduled attempts are retained; none was replaced after failure.
The earlier education artifact-validation pilot is excluded.

| Case | Correct numerical result | Provider error | Median seconds, all attempts | Maximum seconds |
| --- | ---: | ---: | ---: | ---: |
| `education_entities` | 9/10 | 1/10 | 16.89 | 50.32 |
| `research_weighted` | 9/10 | 1/10 | 15.92 | 46.85 |
| `energy_grain` | 9/10 | 1/10 | 13.90 | 48.95 |

Overall numerical completion was 27/30 (90%). All three remaining
attempts failed with HTTP 429. No incorrect numerical result,
application error, or incomplete outcome was recorded in this batch.
This is an observed result on known development fixtures, not a
general accuracy estimate or a controlled implementation comparison.

### Recorded execution policy

The following allowlisted settings and installed versions were identical
across the 30 manifests. Recorded versions are not a dependency lock.

```json
{
  "runner_sha256": "f743868670877cf7b2dc61992f7459a5f6b9a7d0b248c30a99c5aedc875ea0ff",
  "python_version": "3.11.9",
  "dependencies": {
    "verisight": "0.1.0",
    "duckdb": "1.5.6",
    "sqlglot": "28.10.1",
    "pandas": "2.3.3",
    "numpy": "2.3.5",
    "google-genai": "2.27.0",
    "httpx": "0.28.1",
    "pydantic": "2.13.5",
    "pydantic-settings": "2.15.0",
    "openpyxl": "3.1.5",
    "xlrd": "2.0.2"
  },
  "model": "gemini-3.1-flash-lite",
  "provider_retries": 0,
  "run_settings": {
    "allow_llm_data_disclosure": true,
    "request_timeout_seconds": 30.0,
    "max_investigation_seconds": 300.0,
    "retry_base_delay_seconds": 1.0,
    "max_upload_size_mb": 100,
    "max_query_execution_seconds": 5.0,
    "max_query_result_rows": 20,
    "max_query_result_bytes": 1048576,
    "max_query_memory_mb": 512,
    "max_query_temp_storage_mb": 1024
  },
  "max_steps_per_case": 1,
  "claim_output_contract": null
}
```

### Manual review and qualifications

Review of the exported SQL found explicit active-learner filtering and
distinct identity counts in education, matching eligible numerator and
denominator rows in weighted assays, and membership queries that avoid
review-row multiplication in energy. The conclusions reported the
expected metrics without an evident numerical contradiction.

Round 5 energy used `record type != 'test'` rather than
`record type = 'production'`. These predicates agree on this fixture
but differ if another non-test record type is introduced. That result
is correct for the fixture and does not establish general population
selection correctness.

Some conclusions abbreviate eligibility descriptions. Numerical scoring
does not certify narrative semantics. The manifest's explicit output
contract is null; this batch does not test CLI claim-output acceptance.

### Preserved provider failures

- `round-03-energy_grain`: HTTP 429 at `text_generation`, 1 provider attempt.
- `round-04-education_entities`: HTTP 429 at `investigator`, 1 provider attempt.
- `round-04-research_weighted`: HTTP 429 at `investigator`, 1 provider attempt.

The batch introduced no deliberate pacing between investigations.
Rate or quota limiting may have been influenced by request cadence,
but the retained diagnostics do not establish the specific cause.

### Evidence location and fingerprints

Original artifacts remain outside the repository at
`F:\verisight-validation-artifacts\repeatability-17d31bb-first`.
Offline checks verified manifest links, fixture bytes, investigation
hashes, per-case results, and execution-policy consistency.
These fingerprints identify local evidence; they do not make the raw
reports publicly available or independently auditable from GitHub.

Each result record also contains the original investigation hash
when an investigation export exists.

| Attempt | Manifest SHA-256 | Result SHA-256 |
| --- | --- | --- |
| `round-01-education_entities` | `0866e5cdc09f09b8df8b3d553a6ed3aece6e04839f76279f13e604e6f39c8503` | `cad8cbfa56933e1ae240424a17900138073b032ad93af0f5709d0dba26bee2ed` |
| `round-01-research_weighted` | `83bd051cb7ddc161a751dcdc6b523433996bbe2f1f485245b98fd7677d9e838d` | `024ba9c4021a33aa022485d78feedd4d3a7ef4ccb78afe1ca4b897930e9bd4ee` |
| `round-01-energy_grain` | `a734f6e4c3721f1c49201fd7647f8d71e6687b5b9991faee922746d36033749f` | `68e274fad65fd54afdd73a9af7f31617e82a79d02a0e7c7b3ae33b55c3c6b6b9` |
| `round-02-education_entities` | `48f0ca1fcf3ad9e0025c39a340fc5cd0042bf8aa55e437845a4427d1c3b692f8` | `5566a91f1849b3ac52ee71d55704f93b5f80e568d7c6ebb2224a30b99a0db82a` |
| `round-02-research_weighted` | `f717b84861f0273d92a5385130a42ead16033ab7ab0941d7dbaad778c9eb58f2` | `6f7dd6be1e99df9db5163b5d12b1d4da13d9dde778283af0087bc626a1db5958` |
| `round-02-energy_grain` | `c4209a824907e0a45b34e93c94dc4dd7125e0df597fe334fbaad2a541bee3a79` | `220ff4a17877c6f5c68077898a1d4ea645dc0291c786d31d135ec3a0ba2befb5` |
| `round-03-education_entities` | `76f4e7ae3de7328411f2540787688e255ccb9820f42a160de6b9712ac1aa4ae4` | `b7e4833bcd8cb440461eccbecc96ad0872907bd82afc917c0ec8a65c6ef0a0f1` |
| `round-03-research_weighted` | `ae82dbbd8fd740702d868fb3ae92c56079a60e48f2bfdf85fd61842c8b925e94` | `bc089cfbeb4236b33d091b3cfbf8e6e61412451f2523b4c2d855ef7fabb6d3be` |
| `round-03-energy_grain` | `81e75c2adc4b8b7402a0dc13160015328b03a8366c6fb18947260e51a4cc7656` | `9427afa4b0454ee60e6d5d7ab1e7f2ce737ad23265bd21941e66ff7e1b67b45a` |
| `round-04-education_entities` | `bdb0a510d1053ecc5d915861a6b686e47ab1201f25a9393cf699ec54c84f4802` | `95b8f0c797f098f7f4864441669d1e2b8ad3e7aea8ed555bcb71fd7d8c1f1221` |
| `round-04-research_weighted` | `bda5f9075dd439804e6ae04d6e7ebd0bb10a52c56ef6d8b9b658e01e36175067` | `52a0e1681af41beee932c341f2994407311a6a8870bb28a4ee170834d0d2a05b` |
| `round-04-energy_grain` | `4e76682c713932109fc04238ed65c7ed132083ea5abd76da498aca5b9a4db0f7` | `e2b05c55205a141a384d9693a15afc10f3bd410a2be03ca79246476fe03f7a73` |
| `round-05-education_entities` | `eda1e32705d51f7859dd7b8440a63913704080f445bf5fb3180b923430fb13c9` | `77302ba0632b00c9420f12f6c2e3997e874dce0622c31524285831f78c1d9e31` |
| `round-05-research_weighted` | `73dd9a412a4e4208a3f6d99ed32ddb941916a6bcb44803a2c88ffd325338783b` | `aa56eb57cda14c30114e8542fe39b5deb19c94fae31584d2d609204360e40bd1` |
| `round-05-energy_grain` | `29d3c4c95b92176658e5a99da9d67b1b37c3d5cdd1aaa2fe530718066434345a` | `da48e2458ff8069fffe530c41a7a5eeff55ceb380ca3aab3a45e0d69cbf28609` |
| `round-06-education_entities` | `6b12280364682aa61c640cdf9c50b02fb40b6e6a79252cc2707047427301f913` | `901f6a64ff4f0ae8b6f7f9b14f82a4d77e922422923fccd793a74e05d202e32b` |
| `round-06-research_weighted` | `581ca4980b45489865e86eed06e04bbcdc370ccb8f36d2a98ea9cb520effc2ca` | `dd41390160a409d17e9bf82e1b0494f8204788b1584f1695b39eacdd58245a8d` |
| `round-06-energy_grain` | `0093444100b2430cfb50a52dfdda0d973654b5c41f35b2b122c287d34ccff4b7` | `7b256ee6d84c2eac2a40220c2ca9dc4be9c237072b5385d2662c21d8fda838ec` |
| `round-07-education_entities` | `39b008013a1e450be19718e69c39523124885d03e27816a67c8c1d2ac6dbbf3d` | `42b173358412a0556589561652b5f878632e37b75b28f69cafcef3eb1ee16d48` |
| `round-07-research_weighted` | `78bfe6a68fd9786a3d8b7734ee778c31c03d90e69f84fea505e05f8b93514ee8` | `02751faceebd8b8c4e987208d0246ca112f1c964dae57f3448b44fa1b017ca83` |
| `round-07-energy_grain` | `9d34d9f9b107261b9f12d80606481d5765812cfced5c3e37b204e60d1dcaa19f` | `9baddacd27753a55751d76bcbff94f70b58d60e4f045731275ae011aa67d7fdf` |
| `round-08-education_entities` | `b67442342bd7a09ca4f23ceb31cb4138550d00471a753ca49538dbc168b88b18` | `cb5379d6508ce53711e888d89e8673f2c60d91e66912a039fcbc41f16e527799` |
| `round-08-research_weighted` | `604644a4214ec94e766aaed9fde9a2b3fc83ae9247493fd8799166f2dbd841f1` | `5680f2b895e2419d7eb22c8cfd34fb9b2343cdd321be5f0c3edfd044ec2c8e86` |
| `round-08-energy_grain` | `1e5266bb0d7206418ed14e4f179f981787ddeb5372d6f52a753976005f1fde84` | `f18b1a3ba712fe7810bc5cc938948c52c4fb1f79e924e62182b6b69af72efc7e` |
| `round-09-education_entities` | `5351798743463c5e1f223e95b7f92c303a390ea2cd8b9b1ba0bf8ef83364da7e` | `6ee9f49caaf8290a56ff28ebd638a34f1b8c7b42c9da97b65ad0df453c620ac1` |
| `round-09-research_weighted` | `934810739f3643ccfdc22f633e577f3ccefb54db422f674898f417c21e67ff7e` | `2d82318f2d0ba97a76fd5fc706c753b7cf5260939f36985cccb8e275d2424fa1` |
| `round-09-energy_grain` | `557a0e7f4f1b0146e921e222c92d6469ffe9768580e321c7f95295253b7cc03e` | `de72bc79e33b25f937df00b4e492e61d4220e1a4525278b36c31459083de1b7b` |
| `round-10-education_entities` | `481218c89d6346e4bc1fba1b271740756daa4d1d7b2b2d80397ea390f6b1a889` | `bf3e3dd11b4da5ac3bbfcc6eb455a56c5283ef176fd4c6b71b994fee2fd962ea` |
| `round-10-research_weighted` | `de7de6a094aa9519ed7f5eddad250fc006fbffb420fe046c2bd63318ffc97c29` | `9f95a0d335252dab12c2efaf807a54d01fb1823c71504998061f219395e1ee58` |
| `round-10-energy_grain` | `4a94925bd3dc2cd6996ea3329cb5373499a02fe37402e8b0c24c2381e0d3c333` | `5c12658387895e83cfa9eaa41d6e2a7a7231d039f724abc09cce33f89a3495e3` |
