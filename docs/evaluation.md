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
cancelled enrolment, an unknown outcome, and another cohort.

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
`synthetic_evidence`: ordered observations with SQL and result rows, plus the
claims, their evidence references, and verification values/verdicts/reasons.
Decimal values remain strings. The report's top-level `expected` is the fixture
oracle; a verification's `expected` is the model's claimed value. Inspect both
before deciding whether a failure concerns query semantics, references, or
synthesis. Incomplete results retain whatever evidence and claims are available.
Escaping exceptions before a result exists cannot supply this evidence.

This content-bearing evidence is confined to the synthetic runner; the reusable
`score_result()` stays a summary without SQL or claim details. No raw conclusion,
observation question, full analysis, prompt, or credential is copied into the
evidence field. Generated SQL and result cells still require review before
publication. Do not repurpose this reporting path for private datasets without
an explicit disclosure policy. Older saved reports cannot recover omitted values.

The live path uses default planning, investigation, and structured synthesis.
It still allows one analytical attempt and asks for one final VALUE claim.
These cases test generated analytical SQL, not autonomous multi-step reasoning.
No rounding tolerance is used; all three answers have finite decimal forms.

After offline gates pass, commit the fixture definitions before live execution.
Confirm no tracked changes with `git status --short`. Run one case at a time if
provider limits make a combined run impractical:

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
No live outcome is claimed until reports from the implemented revision exist.

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