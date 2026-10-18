
# VeriSight Development Roadmap

**Project:** VeriSight — Autonomous AI Data Analyst  
**Language:** Python  
**Roadmap baseline:** October 18, 2026  
**Repository:** https://github.com/Md-Faiz-Alam/verisight  
**Baseline commit:** `f7685a8`  
**Development status:** Advanced engineering prototype

---

## 1. Purpose

This document is the canonical development roadmap for VeriSight.

It identifies:

- Implemented capabilities
- Verified engineering milestones
- Remaining product gaps
- Current development priorities
- Proposed future milestones
- Acceptance criteria
- Dependencies between milestones
- Conditions for advancing toward production readiness

The roadmap must reflect the actual implementation rather than relying on outdated historical plans.

No new official phase numbers are assigned by this document.

Historical milestone identifiers are retained only when they are supported by the established project record.

The objective is to develop VeriSight into a reliable autonomous analytical system that can produce accurate, traceable, evidence-supported conclusions from structured datasets.

---

## 2. Product Vision

VeriSight aims to become an autonomous AI data analyst capable of:

1. Ingesting supported structured datasets.
2. Understanding dataset schemas.
3. Assessing data quality.
4. Identifying meaningful analytical questions.
5. Generating analytical queries.
6. Validating and executing queries safely.
7. Recovering from supported execution failures.
8. Investigating questions through multiple analytical steps.
9. Preserving analytical evidence.
10. Verifying factual claims against available evidence.
11. Producing trustworthy analytical conclusions.
12. Presenting results through useful product interfaces.

The central architectural principle is:

> AI proposes analytical reasoning and interpretation. Deterministic components validate, execute, and verify the measurable parts of that reasoning.

The long-term product goal is not merely to answer questions about CSV files.

It is to produce analytical conclusions that can be independently inspected and, where supported, verified against actual computed measurements.

---

## 3. Current Development Position

As of the roadmap baseline, VeriSight has implemented substantial functionality across:

- Data ingestion
- Schema inference
- Profiling
- Data-quality analysis
- Evidence representation
- Analytical SQL execution
- SQL security validation
- AI-assisted query planning
- Query repair
- Autonomous investigation
- Prompt budgeting
- Generative synthesis
- Public Python workflows

The project has completed several engineering-hardening increments.

The latest committed increment enables Gemini structured JSON output for autonomous investigation decisions.

However, implementation completeness does not establish analytical correctness.

The largest remaining product gap is the absence of systematic deterministic claim verification and a representative analytical-accuracy benchmark.

### Current Classification

**Advanced engineering prototype / pre-product analytical engine**

This classification reflects the existence of substantial working software alongside unresolved analytical reliability and product-interface requirements.

It is not a claim of production readiness.

---

## 4. Status Definitions

Every roadmap item must use one of the following statuses.

| Status | Meaning |
| --- | --- |
| COMPLETE | Implemented and supported by identified verification evidence |
| IMPLEMENTED — NEEDS EVALUATION | Functionality exists, but important product-level reliability has not been established |
| IN PROGRESS | Work has begun but completion criteria have not been satisfied |
| PLANNED | Approved direction or proposed implementation not yet started |
| PROPOSED | Candidate capability requiring further scoping |
| DEFERRED | Intentionally postponed |
| BLOCKED | Cannot proceed without resolving a specified dependency |

A capability must not be labeled COMPLETE solely because its module exists.

A successful unit test does not establish that a generated analytical conclusion is correct.

---

# Part I — Completed Engineering Foundation

## 5. Data Ingestion

**Status: COMPLETE for the implemented and tested scope**

### Implemented Capabilities

- CSV loading
- Excel loading
- JSON loading
- Input validation
- Unsupported-format handling
- Dataset and table construction
- Relation-name normalization
- Conservative type inference
- Source-value preservation
- Nullable integer handling
- Nullable boolean handling
- Large-integer precision protection
- Explicit handling of supported missing values

### Engineering Requirements

Ingestion must preserve source meaning wherever possible.

Important regression cases include:

- Leading-zero identifiers
- Large integers
- Mixed-type columns
- Missing values
- Excel numeric cells
- Nullable integer columns
- Nullable boolean columns
- Unsupported data structures
- Invalid file inputs

### Remaining Limitations

Not every possible source representation can be interpreted without ambiguity.

Some formats, particularly Excel, may already contain precision loss before ingestion.

Additional source formats and very large datasets remain potential future work.

### Completion Boundary

The existing ingestion implementation is considered complete for its currently supported contract.

Future changes should be driven by reproducible defects, confirmed format requirements, or measured performance limitations.

---

## 6. Profiling and Data Quality

**Status: COMPLETE for the implemented and tested scope**

### Implemented Capabilities

- Column profiling
- Table profiling
- Dataset profiling
- Numeric statistics
- Text statistics
- Datetime statistics
- Missing-value analysis
- Duplicate detection
- Deterministic data-quality findings
- Structured issue representation

### Purpose

Provide a deterministic understanding of the dataset before AI-assisted analytical reasoning.

### Remaining Work

Additional statistical methods or quality rules should be introduced only when required by the product or supported by evaluation findings.

There is no current requirement to replace the existing profiling architecture.

---

## 7. Deterministic Analysis and Evidence

**Status: COMPLETE for the implemented contracts**

### Implemented Capabilities

- Dataset analysis
- Analysis summaries
- Structured insights
- Shared immutable evidence
- Dataset analysis results
- JSON-compatible serialization
- Public result construction

### Architectural Requirement

Analytical measurements must remain separate from generative interpretations.

Evidence structures should preserve their source meaning and prevent unintended mutation.

### Important Limitation

The existence of structured evidence does not automatically establish a relationship between a free-text conclusion and the measurements that support it.

Explicit claim-to-evidence verification remains future work.

---

## 8. DuckDB Analytical Execution

**Status: COMPLETE for the implemented and tested scope**

### Implemented Capabilities

- Dataset table registration
- Analytical SQL execution
- Structured query results
- Query plans
- Query execution contracts
- Read-only query validation
- Registered-dataset relation restrictions
- Controlled execution resources
- Result-row limits
- Execution timeout handling
- SQL execution error translation

### Purpose

Provide deterministic analytical execution independent of the LLM.

### Remaining Limitations

- Execution success does not prove SQL semantic correctness.
- Query resource limits do not establish complete process isolation.
- Large datasets and concurrent workloads require further evaluation.
- Hostile multi-user deployments require additional security controls.

Performance and isolation improvements should be driven by benchmarks or a defined deployment threat model.

---

## 9. SQL Security Hardening

**Status: COMPLETE for the established A7.6.8 milestone**

### Historical Milestone

**A7.6.8 — Security Enforcement Validation**

Confirmed commit:

`d6f8931 — security: enforce dataset-only SQL access`

### Implemented Controls

- SQLGlot-based relation validation
- Registered-dataset relation allowlisting
- Rejection of unauthorized relations
- Restrictions on schema-qualified relations
- Rejection of unsupported SQL table sources
- Restrictions on internal metadata access
- Disabled DuckDB external access
- Disabled automatic extension installation and loading
- Execution resource limits

### Completion Rule

Do not reopen this milestone without:

1. A reproducible vulnerability.
2. A clearly defined missing security requirement.
3. A changed deployment threat model.
4. A verified compatibility or correctness defect.

Additional speculative SQL edge-case investigations are not a standing roadmap priority.

### Security Qualification

The implemented controls provide defense in depth.

They are not proof of complete isolation from all malicious SQL or resource-exhaustion attacks.

---

## 10. AI-Assisted Query Planning and Repair

**Status: IMPLEMENTED — NEEDS EVALUATION**

### Implemented Capabilities

- Gemini-backed generation
- Natural-language question handling
- SQL query planning
- SQL output parsing
- Controlled query execution
- Bounded SQL repair
- Failed-query recovery
- Provider failure handling
- Configurable retries and timeouts
- Explicit LLM data-disclosure permission

### Verified Engineering Behavior

Deterministic tests cover planning interfaces, generation behavior, parsing, repair, provider errors, and execution integration.

### Remaining Product Question

Does the generated SQL consistently answer the intended analytical question?

A query may be syntactically valid, pass security validation, and execute successfully while computing the wrong metric.

This remains a key acceptance-evaluation requirement.

---

## 11. Autonomous Investigation

**Status: IMPLEMENTED — NEEDS EVALUATION**

### Implemented Capabilities

- Structured investigation decisions
- Bounded investigation steps
- Repeated-question detection
- Query observation tracking
- Failed-attempt tracking
- Controlled analytical execution
- Recovery behavior
- Prompt budgeting
- Evidence formatting and compaction
- Complete and incomplete investigation results
- Generative synthesis

### Existing Public Result

`InvestigationResult` provides:

- `question`
- `conclusion`
- `analysis`
- `observations`
- `status`

It also exposes the observation count.

### Known Limitations

- Final conclusions remain free-form text.
- Individual claims are not independently verified.
- Explicit claim-to-observation references are absent.
- Full internal failure and repair history is not exposed publicly.
- Real-world analytical reliability has not been measured systematically.

### Required Future Evidence

End-to-end evaluation must establish that investigation decisions, executed queries, evidence collection, and final conclusions work together correctly.

---

## 12. Gemini Structured JSON

**Status: COMPLETE for the structured-output integration scope**

### Commit

`f7685a8 — feat: enable structured JSON for Gemini investigation`

### Implementation

The Gemini text-generation client supports optional structured JSON response configuration.

The Gemini-backed investigator requests decisions with:

- `action`
- `reasoning`
- `question`

The response schema restricts supported action values and requires the expected fields.

The local investigation parser continues to enforce strict decision validation.

SQL planning, SQL repair, and natural-language synthesis continue using text generation.

### Automated Verification

The locally reported quality gate passed:

| Measurement | Result |
| --- | --- |
| Tests | 1,357 passed |
| Statements covered | 2,339 / 2,339 |
| Branches covered | 604 / 604 |
| Coverage | 100.00% |
| Ruff formatting | Passed |
| Ruff linting | Passed |
| Mypy | Passed |

### Live Provider Verification

A separate real Gemini API smoke test was completed using synthetic analytical information.

The test established that:

- Credentials loaded successfully.
- The configured model accepted the request.
- A structured response was returned.
- VeriSight parsed the response successfully.
- The investigation decision was valid.

The test used fictional order amounts of 10, 20, and 30.

### Verification Boundary

This milestone establishes basic structured-output compatibility.

It does not establish correctness of an entire autonomous investigation.

No additional structured-output hardening is currently required without a reproducible issue.

---

# Part II — Current Development Priorities

## 13. Documentation and Roadmap Reconciliation

**Status: IN PROGRESS**

**Priority: Immediate**

### Problem

The previous README and architecture documentation described implemented features as future work.

The historical testing baseline was also outdated.

The project lacked an authoritative standalone roadmap consistent with its source code.

### Scope

Reconcile:

1. `README.md`
2. `docs/architecture.md`
3. `docs/development.md`
4. `docs/roadmap.md`

### Required Content

Documentation must accurately describe:

- Ingestion
- Profiling
- Quality analysis
- Analytical SQL execution
- SQL security controls
- Gemini integration
- Autonomous investigation
- Prompt budgeting
- Structured JSON decisions
- Public Python workflows
- Evidence and synthesis
- Incomplete investigations
- Current limitations
- Verified quality-gate results
- Next development priorities

### Acceptance Criteria

- [ ] README describes the implemented public workflows.
- [ ] Architecture documentation matches actual source components.
- [ ] Development guide records the established quality gate.
- [ ] Historical results are clearly dated or linked to commits.
- [ ] A canonical roadmap exists.
- [ ] Implemented capabilities are not classified as planned.
- [ ] Planned verification functionality is not claimed as implemented.
- [ ] Dataset attribution is documented where appropriate.
- [ ] Documentation links and examples are checked.
- [ ] No credentials or private datasets are introduced.
- [ ] Git diff is reviewed.
- [ ] Documentation changes are committed and pushed.

### Completion Rule

This milestone is COMPLETE only after all documentation changes have been reviewed, committed, and pushed.

Drafting replacement documents alone does not complete the milestone.

---

## 14. Deterministic Evidence-Linked Claim Verification

**Status: PLANNED**

**Priority: Next major product milestone**

### Problem

VeriSight currently preserves executed analytical observations but does not independently verify individual claims in its generated conclusions.

A generated statement can be inaccurate even when the underlying SQL executed successfully.

For example:

> The North region generated 42.5% of total revenue.

The statement should not be considered verified merely because the model produced it.

### Objective

Introduce a verification mechanism that checks supported analytical claims against explicit observations and deterministic calculations.

### Architectural Principle

Verification should rely on the available evidence, not on another LLM's unsupported judgment.

Proposed flow:

```text
Investigation Observations
           |
           v
Structured Analytical Claims
           |
           v
Claim-to-Evidence References
           |
           v
Deterministic Verification
           |
     +-----+------+
     |     |      |
     v     v      v
 Supported Contradicted Unverifiable
           |
           v
Structured Verification Results
           |
           v
Evidence-Grounded Conclusion
```

This flow is proposed and does not yet exist in production code.

### Initial Scope

The first implementation should support a deliberately small set of numerical claim types.

Candidate types:

- Exact counts
- Sums
- Differences
- Ratios
- Percentages
- Simple comparisons

The exact first-version claim types must be finalized during implementation design.

### Required Verification Behavior

A structured claim should identify:

1. The claimed measurement.
2. The operation or comparison being asserted.
3. The expected value.
4. The relevant evidence reference.
5. The evidence fields required to verify it.

The verifier should:

1. Validate the claim structure.
2. Resolve its evidence references.
3. Reject unsupported references.
4. Read the referenced numerical values.
5. Perform the supported calculation.
6. Apply an explicit comparison policy.
7. Return a structured verification status.
8. Preserve a safe explanation of the result.

### Proposed Statuses

- `SUPPORTED`
- `CONTRADICTED`
- `UNVERIFIABLE`

These are proposed verification outcomes, not existing public enum values.

### Numerical Correctness

Verification must distinguish exact integer arithmetic from approximate floating-point arithmetic.

Potential rules include:

- Exact comparison for supported integer measurements.
- Explicit handling of decimal precision.
- Defined tolerances for eligible floating-point measurements.
- Explicit rejection of invalid numerical inputs.
- No arbitrary acceptance of materially different values.

Tolerance policy must be documented and tested.

### Evidence Requirements

Evidence references must identify existing analytical observations.

The implementation should not invent evidence when a reference cannot be resolved.

A claim should be unverifiable when the required supporting values are unavailable.

### Safety Requirements

- Do not execute arbitrary AI-generated Python expressions.
- Do not use unrestricted `eval()` or `exec()`.
- Do not bypass SQL validation.
- Do not invent missing measurements.
- Do not silently convert contradictory claims into supported claims.
- Do not expose private source rows unnecessarily.
- Do not treat a second LLM opinion as deterministic verification.

### Integration Requirements

Before changing `InvestigationResult`, inspect its existing contract and consumers.

Prefer additive integration where possible.

Determine how verified claims should be represented without breaking existing users of:

- `question`
- `conclusion`
- `analysis`
- `observations`
- `status`

Reuse existing evidence, observation, and serialization contracts where appropriate.

### Initial Acceptance Criteria

- [ ] Structured claim contract is defined.
- [ ] Evidence-reference contract is defined.
- [ ] Supported numerical operations are explicitly documented.
- [ ] Deterministic verification is implemented.
- [ ] Missing evidence produces an unverifiable result.
- [ ] Incorrect numerical claims are identified as contradicted.
- [ ] Correct numerical claims are identified as supported.
- [ ] Integer precision is preserved.
- [ ] Floating-point comparison policy is tested.
- [ ] Malformed claims are safely rejected.
- [ ] Verification results preserve evidence provenance.
- [ ] Existing public behavior remains compatible or has a documented migration.
- [ ] Relevant regression tests pass.
- [ ] The established full quality gate passes.
- [ ] A focused integration test demonstrates verification of investigation observations.

### Out of Scope for the First Version

- Arbitrary free-text mathematical reasoning
- Universal semantic fact-checking
- Unrestricted program execution
- External internet fact-checking
- Automatic verification of every possible business conclusion
- Complex causal inference
- Multi-agent verification architectures
- Distributed verification infrastructure
- A complete dashboard or reporting interface

### Completion Rule

The milestone is complete only when supported analytical claims can be deterministically verified against explicit evidence and the behavior is demonstrated through tests and integration scenarios.

It is not complete merely because new claim models exist.

---

## 15. Analytical Acceptance Evaluation

**Status: PLANNED**

**Priority: High — develop alongside claim verification**

### Problem

Existing automated tests primarily validate application behavior and component contracts.

They do not establish the accuracy of VeriSight's complete analytical workflow across realistic questions.

### Objective

Create a reproducible benchmark that measures analytical correctness and evidence-grounding reliability.

### Initial Size

Begin with approximately 20–30 controlled analytical scenarios.

This is an initial scope target, not a required permanent benchmark size.

### Dataset Requirements

Use small, representative datasets with known analytical answers.

Initial datasets should be synthetic or explicitly approved for evaluation use.

Include cases involving:

- Normal tabular data
- Missing values
- Duplicate records
- Mixed categorical and numerical fields
- Time-based measurements
- Multiple related tables
- Ambiguous analytical questions
- Insufficient evidence

### Scenario Categories

#### Basic Aggregation

- Row counts
- Sums
- Averages
- Minimums and maximums

#### Grouped Analysis

- Category comparisons
- Group totals
- Ranked categories
- Filtered aggregation

#### Derived Measurements

- Percentages
- Ratios
- Differences
- Relative comparisons

#### Temporal Analysis

- Time-based grouping
- Period comparisons
- Trend summaries

#### Data Quality

- Missing-data effects
- Duplicate-data effects
- Interpretation of incomplete records

#### Multi-Step Analysis

- Follow-up analytical questions
- Evidence collection across several observations
- Recovery from a failed generated query

#### Insufficient Evidence

- Unsupported conclusions
- Ambiguous questions
- Missing required observations
- Correct incomplete-result behavior

### Evaluation Metrics

The initial benchmark should measure:

1. SQL semantic correctness
2. Analytical answer correctness
3. Numerical claim accuracy
4. Evidence-reference validity
5. Evidence coverage
6. Unsupported-claim rate
7. Correct incomplete-result behavior
8. Query repair success where applicable
9. End-to-end investigation success

### Expected Answers

Each scenario should define:

- Dataset
- Analytical question
- Expected numerical result
- Acceptable interpretation
- Required evidence
- Unsupported conclusions to reject
- Expected completion behavior

Correctness criteria should be defined before observing the model's answer.

### Evaluation Separation

Maintain two complementary evaluation paths.

#### Deterministic Evaluation

Uses controlled planners, investigators, and synthesizers.

Validates application contracts, verification behavior, and expected analytical outputs.

Should remain reproducible without network access.

#### Live Model Evaluation

Uses an explicitly configured Gemini model.

Measures the behavior of actual model-generated plans, decisions, and conclusions.

Results should record:

- Model identity
- Evaluation date
- Dataset and scenario identifiers
- Relevant execution configuration
- Outcome
- Failure category

Live evaluation should not be part of the ordinary deterministic coverage gate.

### Acceptance Criteria

- [ ] A versioned scenario set exists.
- [ ] Every scenario has a known expected outcome.
- [ ] Expected outcomes are independently established.
- [ ] A reproducible evaluation runner exists.
- [ ] Deterministic checks distinguish correct and incorrect answers.
- [ ] Failed or incomplete investigations are recorded.
- [ ] Evidence-grounding failures are measured.
- [ ] Aggregate metrics are generated.
- [ ] Individual failing scenarios can be inspected.
- [ ] Initial benchmark results are documented.
- [ ] The benchmark identifies actionable analytical weaknesses.

### Completion Rule

A first benchmark is complete when it reproducibly measures the system and produces inspectable results.

Passing every scenario is not required to establish the benchmark.

Analytical accuracy targets should be established using baseline results and the product's intended reliability requirements.

---

## 16. Evaluation-Driven Reliability Improvements

**Status: PLANNED**

**Dependency:** Initial acceptance benchmark

### Objective

Improve VeriSight based on observed analytical failures.

### Potential Failure Categories

- Incorrect question interpretation
- Incorrect aggregation
- Incorrect SQL filtering
- Incorrect grouping
- Incorrect joins
- Query generation failures
- Ineffective SQL repair
- Premature investigation termination
- Repeated or unproductive investigation questions
- Missing evidence
- Incorrect numerical synthesis
- Unsupported conclusion claims
- Incorrect incomplete-result classification

### Development Rule

Do not assume which subsystem needs modification before evaluating the failure.

Examples:

If SQL executes but computes the wrong metric, investigate planning.

If a valid query repeatedly fails to execute, investigate query generation and repair.

If numerical observations are correct but the conclusion is wrong, investigate synthesis and claim verification.

If evidence is missing from the final result, investigate observation and provenance handling.

### Acceptance Criteria

- [ ] Each accepted issue has a reproducible scenario.
- [ ] The responsible subsystem is identified.
- [ ] The fix is bounded.
- [ ] Regression tests cover the failure.
- [ ] Benchmark metrics are compared before and after the fix.
- [ ] Existing functionality remains intact.
- [ ] The full quality gate passes.

Do not expand the architecture solely to make the system appear more autonomous.

---

# Part III — Proposed Product Capabilities

## 17. Reporting and Visualization

**Status: PROPOSED**

### Potential Capabilities

- Summary reports
- Data-quality reports
- Tables of verified findings
- Analytical charts
- Evidence-reference displays
- Exportable analytical reports
- Comparison of verified and unsupported claims

### Dependency

The analytical-result and verification contracts should be sufficiently stable before designing a major reporting layer.

### Design Consideration

Visualizations must reflect actual analytical measurements.

Generated chart descriptions must not substitute for verified underlying data.

### Current Decision

Defer substantial visualization infrastructure until analytical evaluation establishes the relevant result and evidence contracts.

---

## 18. Command-Line Interface

**Status: PROPOSED**

A CLI could expose existing public workflows, including:

- Dataset analysis
- SQL execution
- Natural-language questions
- Autonomous investigation
- Report generation

A CLI may be a practical first user-facing interface because the current product is already a Python library.

### Requirements Before Implementation

- Stable public operations
- Consistent error reporting
- Appropriate output serialization
- Safe configuration and credential handling
- Clear command and argument contracts

No implementation milestone is assigned yet.

---

## 19. HTTP API

**Status: PROPOSED**

An HTTP API could expose VeriSight's analytical capabilities to other applications.

Potential requirements include:

- Request validation
- Dataset upload management
- Controlled execution
- Authentication
- Authorization
- Structured errors
- Concurrency management
- Resource isolation
- Request auditing
- Privacy controls

### Dependency

The existing Python facade and analytical reliability should be sufficiently established before exposing the system to broader users.

An HTTP interface must not be treated as a substitute for deployment isolation or authorization controls.

No framework has been selected.

---

## 20. Interactive User Interface

**Status: PROPOSED**

A future interface may support:

- Dataset selection and upload
- Schema inspection
- Profiling
- Data-quality exploration
- Natural-language analytical questions
- Investigation progress
- Executed SQL inspection
- Evidence review
- Verified and unverifiable claims
- Exportable conclusions

### Dependency

The underlying contracts for findings, observations, verification, and reporting should be stable.

Avoid committing to a UI framework before identifying the target users and usage requirements.

---

## 21. Scalability and Deployment

**Status: DEFERRED**

Potential areas include:

- Larger dataset support
- Memory optimization
- Query performance benchmarks
- Concurrent analytical sessions
- Persistent dataset management
- Process isolation
- Deployment packaging
- Operational monitoring
- Observability
- Multi-user authorization

These capabilities require explicit deployment assumptions.

Do not introduce distributed infrastructure or complex persistence solely in anticipation of future scale.

### Trigger Conditions

Revisit when:

1. Representative datasets exceed current resource limits.
2. A supported deployment target is selected.
3. Concurrent users become a requirement.
4. A measurable performance or isolation problem is identified.

---

## 22. Continuous Integration

**Status: PROPOSED**

A future CI workflow should automatically run the established deterministic quality checks on supported repository changes.

Minimum candidate checks:

- Ruff format verification
- Ruff linting
- Mypy
- Pytest
- Coverage enforcement

CI must not require a real Gemini API key for ordinary pull requests.

Live provider evaluation should remain separate from deterministic checks.

### Decision

Add CI as a bounded engineering-infrastructure increment when the documentation and current product-evaluation milestones justify it.

---

# Part IV — Prioritization and Governance

## 23. Priority Order

The current development sequence is:

| Order | Workstream | Status |
| --- | --- | --- |
| 1 | Complete documentation reconciliation | IN PROGRESS |
| 2 | Define the initial claim-verification contract | PLANNED |
| 3 | Implement deterministic numerical claim verification | PLANNED |
| 4 | Build a small analytical acceptance benchmark | PLANNED |
| 5 | Evaluate complete analytical workflows | PLANNED |
| 6 | Fix measured analytical reliability failures | PLANNED |
| 7 | Choose the first product-facing interface | PROPOSED |
| 8 | Expand reporting, deployment, and scalability | DEFERRED |

Claim verification and benchmark development may proceed together where their contracts overlap.

This sequence is a recommended priority order, not an assertion of official numbered project phases.

---

## 24. Immediate Next Actions

### Current Task: Documentation Reconciliation

Finish the documentation milestone.

Required files:

```text
README.md
docs/architecture.md
docs/development.md
docs/roadmap.md
```

Verify their technical consistency against the current source.

Review Git changes.

Commit and push the completed documentation update.

### Following Task: Claim-Verification Design

Before writing production code:

1. Inspect existing evidence and observation models.
2. Inspect `InvestigationResult` and its consumers.
3. Define the first supported claim types.
4. Define explicit observation references.
5. Define deterministic verification operations.
6. Define comparison and precision rules.
7. Define verification outcomes.
8. Define backward-compatible integration behavior.
9. Select representative acceptance scenarios.

Only then begin the first bounded implementation increment.

---

## 25. Milestone Completion Standards

A code milestone is complete when:

1. The objective is satisfied.
2. Required behavior is implemented.
3. Relevant regression tests exist.
4. Ruff formatting passes.
5. Ruff linting passes.
6. Strict mypy passes.
7. The complete pytest suite passes.
8. The established coverage threshold is met.
9. No secrets or private datasets are staged.
10. The staged diff is reviewed.
11. Documentation is updated where required.
12. The commit succeeds.
13. The intended Git push succeeds.

A documentation-only milestone requires complete, internally consistent documentation and a reviewed commit, but does not require adding production tests.

A benchmark milestone requires reproducible evaluation results, not necessarily a perfect model score.

---

## 26. Established Engineering Quality Gate

The authoritative local verification commands are:

```powershell
ruff format .
ruff format --check .
ruff check .
mypy src tests
pytest --cov=verisight --cov-report=term-missing --cov-fail-under=100
```

The current reported baseline is:

```text
Commit: f7685a8
Date: 2026-10-18

Tests:              1,357 passed
Statements:         2,339
Missing statements: 0
Branches:           604
Partial branches:   0
Coverage:           100.00%

Ruff formatting:    PASS
Ruff linting:       PASS
Mypy:               PASS
```

This baseline should be updated only after a new verified run.

Never interpret coverage percentage alone as analytical reliability.

---

## 27. Security and Data-Protection Rules

All future development must respect the following requirements:

- Never commit actual API keys.
- Never publish `.env`.
- Never unintentionally commit local datasets.
- Preserve explicit external LLM data-disclosure permission.
- Preserve SQL validation and registered-relation restrictions.
- Do not allow arbitrary execution of model-generated code.
- Avoid exposing sensitive provider exception details.
- Avoid uncontrolled logging of dataset values or prompts.
- Validate evidence references before using them.
- Reject unsupported verification operations.
- Do not label unsupported claims as verified.

Security and privacy must remain part of the implementation process without replacing the product roadmap.

---

## 28. Roadmap Change Management

This roadmap is the canonical statement of development priorities after its documentation reconciliation is committed.

It should be updated when:

- A milestone is completed.
- A planned capability becomes implemented.
- Evaluation reveals a new priority.
- An architectural decision changes.
- A feature is explicitly deferred.
- New product requirements are established.

### Rules

1. Do not invent historical milestone numbers.
2. Do not classify a feature as complete based only on module names.
3. Record verification evidence for completed milestones.
4. Distinguish engineering completion from product reliability.
5. Avoid repeatedly expanding completed milestones without evidence.
6. Keep each implementation increment bounded.
7. Reconcile roadmap claims against current source before starting new work.

The source code, tests, and verified quality-gate results remain authoritative for implementation facts.

This roadmap governs planned direction; it does not override contradictory evidence from the current code.

---

## 29. Product Success Criteria

The long-term success of VeriSight should be measured primarily by analytical reliability.

Important criteria include:

### Correctness

Does VeriSight compute the correct answer?

### Evidence

Can the answer be traced to relevant executed observations?

### Verification

Can supported numerical claims be independently checked?

### Uncertainty

Does VeriSight avoid unsupported conclusions when evidence is missing?

### Robustness

Can the system recover from supported failures without compromising correctness?

### Safety

Does the system maintain controlled execution and explicit data-disclosure boundaries?

### Usability

Can users understand the results, inspect the evidence, and identify unverifiable claims?

### Reproducibility

Can analytical outcomes and failures be reproduced and evaluated?

The relative importance and target thresholds for these criteria should be established during product evaluation.

---

## 30. Current Roadmap Summary

### Completed

- Core ingestion
- Schema inference
- Profiling
- Data-quality analysis
- Deterministic analytical result models
- Shared structured evidence
- DuckDB execution
- SQL security enforcement
- Gemini query planning integration
- Bounded query repair implementation
- Autonomous investigation implementation
- Prompt budgeting implementation
- Generative synthesis implementation
- Public Python facade
- Public input and error hardening
- Gemini structured JSON integration
- Live structured JSON smoke test

Completion here refers to the identified implementation or integration scope. Some complete components still require product-level evaluation.

### Current

**Documentation and roadmap reconciliation**

### Next

**Deterministic evidence-linked claim verification**

Develop alongside a small analytical acceptance benchmark.

### Later

- Evaluation-driven reliability improvements
- Reporting and visualization
- CLI
- HTTP API
- User interface
- Deployment and scalability

These later capabilities require further scope and prioritization decisions.

---

## 31. Final Direction

VeriSight's fundamental analytical architecture is already implemented.

The next challenge is to establish trustworthy interpretation of analytical evidence.

The development path is:

```text
Deterministic Data Processing
              |
              v
Controlled Analytical Execution
              |
              v
AI-Assisted Investigation
              |
              v
Structured Query Observations
              |
              v
Deterministic Claim Verification
              |
              v
Measured Analytical Reliability
              |
              v
Reporting and Product Interfaces
              |
              v
Deployment and Scale
```

The first four areas have substantial implementations.

Deterministic claim verification and formal analytical accuracy evaluation are the next major product-development priorities.

**The project should now prioritize verifiable analytical correctness over adding further orchestration layers or repeatedly hardening already completed components without a demonstrated failure.**
