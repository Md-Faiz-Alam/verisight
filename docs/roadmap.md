# VeriSight roadmap

## Objective and current evidence

Build an investigator for unfamiliar structured tabular datasets that produces
useful findings with inspectable evidence and explicit uncertainty. Completion
is measured through acceptance criteria, not a percentage or an unsupported
delivery estimate.

The implemented foundation includes ingestion, profiling, quality analysis,
validated SQL, generation and repair, bounded investigation, structured synthesis,
numerical verification, application-rendered claim statements, token audits,
Unicode digit coverage, expected-failure evidence recovery, safe diagnostics,
generation telemetry, and offline CI on Windows and Linux.

Five synthetic live development fixtures and committed success/failure reports
exist. Reports span different revisions and settings. They establish examples
of working behavior and failures, not general accuracy or production readiness.
Narrative verification remains false.

## 1. Integrate per-metric rounding deliberately

An opt-in `DecimalRoundingPolicy` now supports 0–12 decimal places with fixed
half-even rounding. Explicit reverification retains original evidence and the
policy, distinguishing `supported_rounded` from ordinary support. Model-selected
precision and combinations with nonzero absolute tolerance are rejected.

Default structured investigations and live evaluation still use strict
comparison. A separate rounded report does not mutate the investigation.

Remaining work:

- Define which metrics and units permit which presentation precision.
- Integrate explicit application policies into report consumers where justified.
- Decide how a future evaluator scores rounded answers against independent
  ground truth while preserving the strict baseline.

Acceptance: metric policies are explicit; boundary, negative, percentage,
large-value, and incorrect-value cases remain covered. There is no implicit unit
conversion or general forgiveness of floating-point differences.

## 2. Expand independent correctness evaluation

Current live fixtures are easy single-metric development cases with one
analytical step each. They do not establish autonomous multi-step reasoning.

Required work:

- Add independently specified joins, filters, nulls, duplicates, grain, units,
  dates, rates, and insufficient-evidence questions.
- Add multi-step and held-out cases across multiple domains.
- Define a comparison baseline and release targets before held-out evaluation.
- Record fixture identities and sufficient environment information.
- Retain failures and report availability, correctness, completion, and latency
  with explicit denominators.

Bank Marketing questions can add depth but do not establish cross-domain
generality. A clean-revision multi-case run is a reproducibility checkpoint,
not proof of reliability. Pace provider calls based on actual limits; do not
infer optimal settings from selected successful attempts.

Acceptance: answers are independent of generated SQL, every attempt is
accounted for, and results can be reproduced and compared with a defined
baseline. Missing claims do not automatically count as justified abstention.

## 3. Strengthen report meaning and provenance

Claim-linked statements and token/digit diagnostics now exist. Semantic linkage
between narrative assertions, claim identities, and analytical intent remains
unestablished.

Required work:

- Represent findings with explicit claim references and analytical scope.
- Separate measurements, interpretations, hypotheses, and unanswered questions.
- Return bounded failed-attempt and repair history.
- Decide whether `ask()` needs a richer return contract.
- Evaluate unsupported formats and number words without silently guessing
  their meaning.

Acceptance: users can inspect the evidence and history behind findings;
contradictions and partial results remain visible. Equal numbers or complete
digit coverage cannot certify direction, units, causation, or denominator.
Narrative error rates require independently labeled semantic evaluation.

## 4. Improve unfamiliar-data handling and planning

Required work includes nullable Excel boolean inference, identifier-quoting
instructions, removal of private cross-object configuration in legacy synthesis,
relationship discovery, semantic roles, units, schema ambiguity, useful competing
hypotheses, and stopping rules for insufficient evidence.

Acceptance: targeted regressions preserve existing precision guarantees;
unfamiliar schemas and ambiguous questions are handled or explicitly reported.
Investigations avoid repeated or low-value queries and unsupported causal claims.

## 5. Deliver the end-user workflow

Build dataset onboarding, progress visibility, evidence navigation, partial
failure presentation, and accessible report export.

Acceptance: users can investigate supported datasets without editing Python,
inspect SQL and observations, understand incomplete outcomes, and export a
coherent report. Workflow completion is never presented as verified correctness.

## 6. Establish operational readiness

Offline CI is implemented. Remaining work includes reproducible dependency and
deployment inputs, workload limits, cancellation, resource exhaustion, upload
and isolation assessment, operational diagnostics, and recovery under realistic
provider conditions.

Acceptance: deployment is repeatable; supported limits and failure behavior are
documented and exercised. Local checks and CI do not replace operational tests.

## Release criteria and engineering standards

An end-to-end release requires demonstrated unfamiliar-data workflows,
inspectable material quantitative findings, independent benchmark targets,
explicit narrative limitations, useful partial evidence, report export, and
repeatable deployment.

Maintain strict typing, formatting/lint gates, statement and branch coverage,
synthetic regression inputs, small reviewable changes, explicit staging, and
documentation that matches implemented behavior. Keep local datasets and
credentials out of routine commits.

See [Architecture](architecture.md) for current boundaries and
[Development](development.md) for commands and evaluation practice.