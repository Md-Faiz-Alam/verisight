# VeriSight roadmap

## Objective and current position

Deliver a local analyst for unfamiliar supported tabular datasets, with
inspectable SQL evidence, bounded investigations, and explicit uncertainty.
Domain-independent processing does not guarantee understanding of arbitrary
business definitions, file formats, data sizes, or analytical questions.

The implemented foundation includes ingestion, deterministic profiling and
quality rules, guarded DuckDB execution, planning and one-query repair,
structured synthesis, numerical claim verification, narrative token and digit
audits, expected-failure evidence recovery, query repair provenance, provider
telemetry, shared investigation deadlines, and configurable result byte limits.
It also includes a local CLI and optional caller-selected claim output contracts.
CI is configured for Python 3.11 on Windows and Linux. At revision `7a91a83`,
the reviewed Windows run reported 2,422 passing tests, 100% statement and branch
coverage, clean Ruff checks, and strict mypy over 177 files. The
[corresponding CI run](https://github.com/Md-Faiz-Alam/verisight/actions/runs/40900013243)
passed on Windows and Ubuntu. A passing run establishes the tested engineering
behavior, not analytical meaning or production readiness.

At the 2026-10-25 implementation checkpoint `da86f3a`, the supplied Windows
terminal run for those changes reported 2,274 passing tests, 100% statement and
branch coverage, clean Ruff checks, and strict mypy. This is a dated local
record, not a claim about that revision's remote CI. Those checks establish
tested behavior; they do not certify analytical meaning, security isolation,
narrative truth, or production readiness.

## Evidence checkpoint

The reviewed corrections now include finite platform-bounded SQL timeouts,
unusable-column rejection before registration, stable float summary arithmetic
with explicit deviation overflow, shared SDK cancellation classification, a
caller-selected claim output gate, and the `current_schemas` metadata restriction.
Later corrections include explicit CSV parsing choices and provenance, SQL
planning separate from execution, bounded categorical evidence for planning
and repair, targeted numeric feedback in synthesis repair, datetime-span
overflow handling, and safe provider diagnostics in public/CLI error exports.
These are focused engineering changes, not proof of general analytical
reliability. Passing offline gates is separate from live task acceptance.

Original-question propagation did not reliably correct autonomous population
selection. A live education case still selected non-cancelled learners rather
than active learners, returning 40% instead of 37.5%. Its claim was numerically
supported by the wrong population's SQL cell. This historical run remains an
analytical interpretation failure. A later unscoped full investigation at
`33b8d4e` used the correct active-only query and completed with one supported
`37.5` VALUE claim in `20.085` seconds. It also used the existing synthesis
format-repair path. That success applies to one known development fixture;
general autonomous population interpretation remains unproven. See
[Evaluation](evaluation.md#reviewed-october-29-development-checks).

Caller-selected population enforcement is implemented separately. The public
`execute`, `ask`, and `investigate` methods accept typed, immutable equality or
membership filters for named relations. The built-in executor restricts those
relations before generated or repaired queries read them. This does not check
whether the caller's constraints capture the question's business meaning.

The caller-scoped education validation at clean revision `34c3f30` returned
8 eligible learners, 3 completions, and 37.5%. The deliberately broad supplied
SQL control was restricted to that same population. The live investigation
returned a supported 37.5% claim and a matching conclusion in 13.298 seconds.
The report was retained in commit `529baf3`:

[Caller-scoped education validation](../reports/evaluations/education-caller-scoped-20261024-085546-292.json)

This is one successful known synthetic case. It is not a held-out benchmark,
a demonstration that autonomous population selection is corrected, or evidence
of general domain accuracy. Scoped and unscoped outcomes must remain separate.

## 1. Fix the product's acceptance rules

Use independent indicators rather than one overall verified or correct badge.

| Indicator | Existing evidence | Permitted meaning |
| --- | --- | --- |
| Workflow status | `InvestigationResult.status` and failure metadata | Complete or incomplete workflow; no correctness claim |
| Numerical support | Each `verified_claims` verdict and evidence reference | A claim matches its referenced numerical evidence under the stated policy |
| Caller-selected population | Submitted `population` and built-in execution path | Specified filters were applied to the named query relations |
| Optional output contract | `assess_output()` or CLI `--require-claim` assessment | Exact selected claim operations/count, support, completion, and limited numeric audits passed |
| Narrative audit | Tokens, unlinked numbers, digit coverage, and `narrative_verified` | Limited numerical diagnostics; no semantic certification |
| Analytical review | Not currently represented by a review record | Do not display an analytically reviewed label automatically |

An analytically reviewed label would require an explicit review record tied to
the question, scope, executed evidence, reviewer, and review time. A model's
self-assessment, workflow completion, or numerical support is not that record.
Do not add this label to the first workflow without implementing its provenance.

Apply these rules to presentation and export:

- Show original questions, analytical subquestions, executed SQL, result cells,
  and claim references together. Keep failed attempts separate from evidence.
- Show supplied population constraints explicitly. Mark row counts, profiling,
  insights, and quality findings as original-dataset information; they are not
  recomputed population statistics.
- Preserve contradicted and unverifiable verdicts. Do not present those claims
  as established answers. Keep generated prose visibly identified as unverified
  interpretation, even when every submitted numerical claim is supported.
- Do not interpret unlinked tokens as fabricated numbers automatically. Years,
  counts, and other contextual values may lack submitted claims. Zero unlinked
  tokens and complete digit coverage do not establish truth.
- Preserve partial observations and explain the stopping reason, failed stage,
  and available repair history. An incomplete result is not a completed answer.
- Show unsupported requirements and unresolved assumptions. Model-suggested
  ambiguity detection can miss ambiguities and is not a deterministic gate.
- Before execution, let the user inspect and correct the proposed population,
  unit of analysis, denominator, time period, and units. Request a decision when
  a material interpretation is known to be unresolved; never silently substitute
  a different population or metric.
- A population restriction applies only to its named relations. Comparisons
  needing excluded rows require deliberately available comparison data. Unsupported
  scope operators must not be silently dropped or described as enforced.

Acceptance: a reader can distinguish workflow completion, numerical support,
caller-supplied constraints, and unverified interpretation without reading
implementation documentation. No newly invented metadata or inferred review
status substitutes for evidence.

Implemented subset: the CLI separates workflow, population, numerical statements,
unverified prose, and SQL evidence. With `--require-claim`, it supplies the typed
contract to structured synthesis and rejects unmet requirements in the final
assessment. Nonempty claim-shape mismatches use the existing single format-repair
attempt; evidence is not deleted and queries are not rerun. The final assessment
itself makes no model calls. It is not inferred from the question and does not
certify the whole task. Remaining acceptance work concerns interpretation,
meaningful review of procedures, and unfamiliar-data evidence. See
[Output contracts](output-contracts.md).

At `33b8d4e`, the existing single synthesis repair attempt gained bounded
feedback identifying unlinked numeric values. Validators and numerical
tolerances were unchanged. This helps address demonstrated output failures;
it does not verify number words, units, populations, or narrative truth.

## 2. Validate the implemented local workflow

The local command-line workflow over the existing Python facade is implemented.
Known synthetic installed-CLI runs and JSON export checks are retained. Users
can run it without editing Python source. Hosted accounts, multi-user services,
dashboards, and extra providers are not required for this milestone.

| Step | Existing foundation | Work still required |
| --- | --- | --- |
| Load supported files | CLI paths and classified input failures | Validate usability on unfamiliar supported files and fresh installations |
| Inspect data | CLI profile with relations, types, findings, and original counts | Resolve demonstrated presentation gaps |
| Define question and scope | Question, population JSON, and offline preview | Validate user interpretation of grain, denominator, time, and units |
| Investigate | Step/time limits and terminal workflow reports | Measure availability, latency, cancellation, and partial recovery under realistic use |
| Inspect the answer | Separate evidence, claims, audits, and optional output acceptance | Evaluate whether users can identify supported but analytically wrong answers |
| Export | Explicit new-file JSON export | Assess portability, sensitive content, and consumer expectations |

`plan()` exposes proposed SQL without executing the analytical query. Reviewing
a plan does not bind later execution to an immutable snapshot of the input.
`execute()` and `ask()` currently return `QueryResult`, without investigation
provenance. Do not imply those values contain SQL repair history or a review
record. Use `investigate()` for the evidence-oriented workflow rather than
expanding every public return type in advance.

Exported questions, SQL literals, dataset evidence, and repair plans can contain
sensitive values. Local export must be an explicit user action. Population
filters are not privacy controls: original profiling context can include
information about excluded rows.

Acceptance: a user can load a small supported dataset, inspect its structure,
ask a question, inspect supplied scope, run a bounded investigation, examine
SQL-backed claims or useful partial evidence, and export a readable result.
Provide one short synthetic demonstration. A passing synthetic demo does not
establish unfamiliar-data accuracy.

That synthetic demonstration exists in the retained posted-transaction CLI
validation. The fixed CLI batch and later orchard/reservoir records show both
successes and limitations. The historical reservoir procedure recheck at
`5474cee` used two ordered queries but returned extra claims. A later full CLI
run at `58e2243` completed the same known task in `75.753` seconds with two
ordered queries and exactly one supported DIFFERENCE claim `50`. Both records
remain relevant; the later success does not replace the earlier failure.

October 29 checks separately recorded a successful full learner investigation
at `33b8d4e`, a successful full membership investigation at that revision,
and a successful full weighted-mean investigation at `7a91a83`. The original
three-case transfer batch had no completed cases. A later latest-version check
successfully synthesized retained evidence but did not rerun the full workflow.
These are development diagnostics across different invocation paths and
settings, not a combined accuracy rate. See [Evaluation](evaluation.md).

## 3. Establish independent release evaluation

Retain the existing strict scorer and every unsuccessful attempt. Do not supply
oracle answers or control SQL to model prompts. Supplied SQL controls are not
competing AI-system baselines.

Required work:

- Run the defined suite at one clean revision with recorded settings and
  dependency versions. Separate caller-scoped from unscoped cases.
- Include independent expectations for population, joins, duplicate identities,
  grain, missing values, weights, dates, units, percentages, and denominators.
- Add held-out and unscripted multi-step cases, including ambiguous questions
  and insufficient evidence. Known public fixtures are development evidence.
- Define a meaningful model or system baseline and release targets before
  inspecting held-out outcomes.
- Report availability, completion, numerical support, independent correctness,
  and latency separately, with explicit denominators. A supported wrong answer
  must remain visible. Do not select the best retry as the reported success rate.
- Assess whether clarification resolves ambiguity without asserting that all
  ambiguous requests are detected automatically.

Acceptance: results are reproducible, every attempt is accounted for, and
scoring is independent of generated SQL and claims. No-claims responses are not
automatically justified abstentions. Domain breadth requires varied schemas
and analytical tasks, not domain labels alone.

## 4. Integrate rounding only where the metric requires it

`DecimalRoundingPolicy` supports 0–12 places and nearest rounding with exact
ties away from zero (`ROUND_HALF_UP`), matching DuckDB `ROUND` for exact decimal
inputs. Explicit reverification retains evidence and distinguishes
`supported_rounded`. Structured investigations and the live scorer remain strict.

Select presentation precision from application-approved metric and unit policies.
Do not infer it from model output, perform implicit unit conversion, or weaken
comparison to make failed examples pass. A separate rounded report must not
mutate the original investigation or replace the strict evaluation baseline.

Acceptance: only justified metric policies are integrated into consumers;
wrong values, unsafe arithmetic, and unsupported conversions remain visible.

## 5. Establish operational and release readiness

Before release, verify installation in a fresh environment, actual remote CI
outcomes, supported workload limits, cancellation and cleanup behavior, and
expected recovery under provider failures. Document dependency and environment
inputs so results can be reproduced. Early public/CLI failures now retain
available allowlisted provider diagnostics. Missing HTTP status does not
identify a transport cause; a configured retry is not evidence that a retry
was needed or successful.

Choose deployment requirements explicitly. Hosted or multi-user deployment
requires its own isolation, authorization, upload, disclosure, and resource
assessment. SQL parsing and DuckDB configuration alone are not proof of a
complete security sandbox.

Acceptance: the selected local deployment is repeatable, its supported inputs
and limits are clear, failures preserve useful evidence, and users can complete
the defined workflow. Defer additional infrastructure until a deployment need
or observed failure justifies it.

## Engineering discipline

Prefer focused changes in existing modules. Add tests for consequential
behavior and failure paths, not to grow counts or mirror implementation.
Maintain strict typing, formatting/lint gates, and statement and branch coverage.
Do not add prompt variants, internal metadata, or abstractions without a concrete
failure or workflow requirement.

Keep private datasets and credentials out of routine commits. Stage exact paths
and retain unsuccessful evaluation reports as well as successful ones.

See [Architecture](architecture.md) for implemented boundaries,
[Evaluation](evaluation.md) for evaluation definitions, and
[Development](development.md) for commands.