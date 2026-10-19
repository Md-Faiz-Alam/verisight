# VeriSight roadmap

## Product objective

Build an autonomous investigator for unfamiliar structured tabular datasets that
produces useful findings with inspectable evidence and explicit uncertainty.

Progress is measured through observable acceptance criteria, not a percentage
of implementation completed.

## Implemented foundation

- CSV, JSON, and Excel ingestion.
- Schema inference, profiling, and data-quality analysis.
- Validated SQL execution with configured resource limits.
- Gemini-driven planning and query repair.
- Bounded autonomous investigations.
- Structured synthesis enabled by default for configured Gemini investigations.
- Deterministic numerical claim verification.
- Per-claim verdicts in investigation results.
- Explicitly unverified narrative status.
- Safe public error classification and provider diagnostics.
- Deterministic verification benchmarks.
- Opt-in live evaluation on three synthetic fixtures.

These milestones establish implementation capability. They do not establish
general analytical accuracy or production readiness.

## Milestone 1: Preserve partial investigation evidence

Current gap:

Some synthesis and provider failures raise without returning the observations
already collected.

Required work:

- Preserve observations when synthesis cannot complete.
- Report incomplete status and a structured failure category.
- Retain safe diagnostic context.
- Define separate policies for provider retries and response-format repair.
- Accept only explicitly supported response wrappers, if fence support is added.
- Keep repair feedback sanitized and within prompt budgets.

Acceptance criteria:

- A failure after a successful query returns inspectable partial evidence.
- Invalid synthesis cannot produce a complete, apparently verified report.
- Retry behavior is bounded and tested.
- Raw provider messages and private data do not leak into public reports.

## Milestone 2: Link report statements to claims

Current gap:

A conclusion can contain a false number while its separate claim list contains
a supported number. Empty claims also do not establish a trustworthy narrative.

Required work:

- Introduce structured findings with explicit claim references.
- Render quantitative statements from verified values where practical.
- Distinguish verified quantities from interpretations and unresolved questions.
- Report missing or invalid claim links.

Number extraction may provide supplementary warnings. Matching numerical tokens
alone must not certify narrative meaning.

Acceptance criteria:

- Report consumers can identify the evidence behind each quantitative finding.
- Contradicted and unverifiable claims remain visibly distinct.
- An unlinked narrative is not presented as verified.
- Changes in direction, units, scope, or denominator cannot be certified merely
  because the same number appears in both text and evidence.

## Milestone 3: Define controlled rounding

Current gap:

Structured claims use exact comparison, so legitimate rounded presentations can
receive `contradicted`.

Required work:

- Define an application-controlled rounding policy.
- Specify supported precision, units, and rounding mode.
- Preserve exact evidence alongside displayed values.
- Distinguish exact support from rounded support.
- Prevent model-selected decimal precision from silently widening acceptance.

Acceptance criteria:

- Correct rounded values are distinguished from exact matches.
- Incorrect values remain rejected.
- Boundary, negative, percentage, and large-number cases are tested.
- The policy does not broadly excuse differences as floating-point noise.

## Milestone 4: Expand and record evaluation

Current position:

The deterministic benchmark covers numerical and semantic-limit scenarios.
The live evaluator has three known development fixtures and one analytical step
per case.

Required work:

- Expand to independently specified questions across multiple domains.
- Add joins, filters, nulls, duplicates, rates, dates, and insufficient evidence.
- Add multi-step investigations.
- Separate development fixtures from held-out cases.
- Record model, settings, source revision, fixture identity, and outcomes.
- Retain failed runs.
- Add a defined baseline.
- Store reviewed synthetic evaluation reports in version control.

Bank Marketing questions may supplement evaluation, but one dataset does not
establish domain generality.

Measure separately:

| Metric | Proposed denominator |
| --- | --- |
| Ground-truth numerical success | All attempted cases |
| Successful investigation completion | All attempted cases |
| Provider failure rate | All attempted cases |
| Contradicted-claim rate | All submitted numerical claims |
| Unverifiable-claim rate | All submitted numerical claims |
| No-claims rate | All attempted cases |

Also report conditional accuracy among scored answers, with its denominator.
Do not hide missing answers or provider failures by reporting only that metric.

Narrative hallucination requires its own labeled evaluation. Unmatched numerical
tokens alone are not a sufficient definition.

Acceptance criteria:

- Expected answers are independent of generated SQL.
- Reports identify every attempted case and outcome.
- No-claims responses are not automatically counted as justified abstentions.
- Reproduction instructions and baseline definitions are committed.
- Release thresholds are agreed before evaluating held-out cases.

## Milestone 5: Improve provenance and data handling

Remaining work:

- Return failed investigation attempts and query repair history.
- Decide whether `ask()` needs a richer result contract.
- Correct nullable Excel boolean inference.
- Add identifier-quoting guidance to planning and repair prompts.
- Replace private cross-object configuration in legacy synthesis.
- Evaluate schema ambiguity, relationship discovery, and units.

Acceptance criteria:

- Each change has a targeted regression.
- Existing ingestion precision guarantees remain intact.
- New provenance does not disclose private exception contents.
- Ambiguity is reported rather than silently resolved without evidence.

## Milestone 6: Deliver a usable investigation product

Required work:

- Dataset onboarding.
- Investigation progress.
- Evidence navigation.
- Clear partial-failure presentation.
- Accessible report export.
- Explicit separation of facts, interpretations, and unanswered questions.

Acceptance criteria:

- A user can investigate a supported dataset without editing Python code.
- A user can inspect the SQL and evidence behind a finding.
- Workflow completion cannot be confused with verified correctness.
- Empty or failed investigations remain understandable.

## Milestone 7: Establish operational readiness

Required work:

- Continuous integration for formatting, linting, types, and tests.
- Repeatable installation and deployment.
- Resource and cancellation testing.
- Isolation and upload-security assessment.
- Operational diagnostics without sensitive content.
- Documented limits and recovery behavior.

Acceptance criteria:

- CI reproduces the required offline gate.
- Deployment can be reproduced from documented inputs.
- Resource exhaustion and provider failures have tested outcomes.
- Supported workload limits are explicit.

## Release criteria

An end-to-end release requires evidence that:

- Supported unfamiliar datasets can be analyzed through the intended user flow.
- Analytical queries are executed within documented controls.
- Material quantitative findings have inspectable verification status.
- Narrative and semantic limitations remain explicit.
- Independent benchmarks meet predefined targets.
- Failures preserve useful evidence where available.
- Reports and deployment are reproducible.

No current test count or coverage percentage independently satisfies these
criteria.

## Engineering standards

- Strict type checking.
- Formatting and lint gates.
- Statement and branch coverage requirements.
- Synthetic regression tests.
- Explicit file staging.
- No accidental dataset or credential commits.
- Small, reviewable milestones.
- Documentation updated alongside behavior changes.

The next runtime milestone is preservation of partial investigation evidence
when synthesis or provider generation fails.
