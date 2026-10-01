# VeriSight Development Guide

## Overview

This document describes the current development workflow and quality requirements for VeriSight.

VeriSight uses:

- Python 3.11+
- Ruff for formatting and linting
- mypy in strict mode for static type checking
- pytest for testing
- pytest-cov for coverage measurement

The repository currently requires complete test coverage for the configured source and branch coverage measurements.

---

## Environment Setup

### Windows PowerShell

Create a virtual environment from the repository root:

```powershell
python -m venv .venv
```

Activate it:

```powershell
.\.venv\Scripts\Activate.ps1
```

Upgrade pip:

```powershell
python -m pip install --upgrade pip
```

Install VeriSight and its development dependencies:

```powershell
pip install -e ".[dev]"
```

After activation, the PowerShell prompt should normally show the active environment:

```text
(.venv) PS F:\verisight>
```

---

## Project Layout

The primary implementation lives under:

```text
src/verisight/
```

Tests live under:

```text
tests/
```

Project documentation lives under:

```text
docs/
```

The root `README.md` provides the repository overview while the `docs/` directory contains deeper engineering documentation.

---

## Formatting

VeriSight uses Ruff's formatter.

Format the complete repository with:

```powershell
ruff format .
```

Check formatting without modifying files:

```powershell
ruff format --check .
```

The formatting check must pass before a change is considered complete.

---

## Linting

Run Ruff linting with:

```powershell
ruff check .
```

The current Ruff configuration checks:

- `E`
- `F`
- `I`
- `UP`
- `B`
- `SIM`

The configured Python target is Python 3.11.

The configured maximum line length is 88 characters.

Where appropriate, Ruff can automatically repair supported violations:

```powershell
ruff check . --fix
```

After automatic fixes, run formatting and linting again.

---

## Static Type Checking

VeriSight uses mypy in strict mode.

Run the complete type check with:

```powershell
mypy src tests
```

Both production code and tests are included in static type checking.

A change is not complete while mypy reports errors.

---

## Testing

Run the complete test suite with:

```powershell
pytest
```

For more detailed test output:

```powershell
pytest -v
```

A specific test file can be run independently during development.

For example:

```powershell
pytest tests/test_csv_loader.py -v
```

Multiple related test files can also be executed together:

```powershell
pytest `
    tests/test_quality_models.py `
    tests/test_quality_rules.py `
    tests/test_analysis_insights.py `
    -v
```

Focused tests are useful while implementing a change, but the complete test suite must still be run before the change is finalized.

---

## Coverage

The repository uses branch coverage.

Run the complete suite with the required coverage threshold using:

```powershell
pytest --cov=verisight --cov-report=term-missing --cov-fail-under=100
```

The configured development standard requires 100% coverage.

This means new branches and failure paths should normally receive explicit tests rather than being left untested.

Coverage should not be increased by weakening meaningful behavior or excluding ordinary production paths merely to satisfy the metric.

---

## Complete Quality Gate

Before committing a completed change, run:

```powershell
ruff format .

ruff format --check .
ruff check .
mypy src tests

pytest --cov=verisight --cov-report=term-missing --cov-fail-under=100
```

All commands must pass.

The current deterministic foundation has been validated with:

```text
343 passed
100% test coverage
```

This number will naturally increase as functionality and tests are added.

The important invariant is that the complete suite passes and the configured coverage requirement remains satisfied.

---

## Recommended Development Workflow

For most changes, use the following sequence.

### 1. Inspect the Existing Contract

Before modifying a subsystem, inspect:

- the implementation
- its domain models
- related tests
- downstream consumers

Avoid introducing a second representation of information that already has an established canonical model.

### 2. Make the Smallest Coherent Change

Changes should preserve existing functionality unless intentionally changing a documented contract.

Avoid unrelated refactoring inside feature or bug-fix changes.

### 3. Add or Update Tests

Tests should cover:

- expected behavior
- relevant edge cases
- failure paths
- regressions being fixed

When changing a shared contract, update all affected consumers and tests together.

### 4. Run Focused Validation

During implementation, run formatting, linting, typing, and tests against the affected files.

Example:

```powershell
ruff format `
    src/verisight/ingestion/loaders/csv.py `
    tests/test_csv_loader.py

ruff check `
    src/verisight/ingestion/loaders/csv.py `
    tests/test_csv_loader.py

mypy `
    src/verisight/ingestion/loaders/csv.py `
    tests/test_csv_loader.py

pytest tests/test_csv_loader.py -v
```

Focused validation provides faster feedback while developing.

### 5. Run the Complete Quality Gate

Once focused tests pass, run the complete repository validation:

```powershell
ruff format .
ruff format --check .
ruff check .
mypy src tests
pytest --cov=verisight --cov-report=term-missing --cov-fail-under=100
```

Do not rely only on focused tests before committing.

### 6. Inspect the Git Diff

Before staging changes:

```powershell
git status --short
git --no-pager diff --stat
git --no-pager diff
```

For a specific file:

```powershell
git --no-pager diff -- path/to/file.py
```

Inspect the actual diff rather than assuming that only intended files changed.

### 7. Stage Explicit Files

Prefer staging the files belonging to the coherent change explicitly.

Example:

```powershell
git add `
    src/verisight/ingestion/loaders/csv.py `
    tests/test_csv_loader.py
```

Then inspect the staged state:

```powershell
git status --short
git --no-pager diff --cached --stat
git --no-pager diff --cached
```

### 8. Commit the Coherent Change

Use a descriptive commit message.

Examples of the style currently used by the repository include:

```text
fix(ingestion): support UTF-16 CSV encodings
refactor(evidence): add shared immutable evidence contract
refactor(profiling): make table statistics canonical
feat(quality): detect entirely missing columns
```

A commit should represent one understandable unit of work.

---

## Testing Philosophy

Tests should verify behavior and architectural contracts rather than implementation accidents.

Important areas currently covered include:

- file validation
- CSV parsing
- CSV delimiter detection
- CSV encoding handling
- Excel ingestion
- JSON ingestion
- dataset normalization
- relation-name generation
- schema inference
- column profiling
- numeric profiling
- text profiling
- datetime profiling
- missing-value analysis
- duplicate analysis
- messy-data behavior
- quality rules
- immutable evidence
- deterministic analysis
- summaries
- analytical insights
- integration between layers

Regression tests should be added when a defect reveals a previously uncovered behavior.

---

## Type Safety

The project uses strict mypy checking.

Avoid weakening types merely to silence a type checker error.

For example, shared structured evidence uses the explicit evidence contract rather than unrestricted structures such as:

```python
dict[str, object]
```

When a type error exposes disagreement between a producer and consumer, first determine whether the domain contract is incorrect before introducing casts or ignores.

Type ignores should be limited to cases where they are intentionally testing behavior that the type system correctly prevents, such as attempting to mutate an immutable structure.

---

## Canonical Data Contracts

Avoid maintaining duplicate representations of the same measurement.

For example, table-level missing-value and duplicate measurements belong to their canonical statistics structures in the table profile.

Downstream components should consume those structures instead of independently recomputing or duplicating the same values.

This principle reduces:

- inconsistent results
- synchronization bugs
- unnecessary state
- downstream migration cost

When introducing new analytical information, first determine which layer should own it.

---

## Evidence

Structured evidence should use the shared contract defined in:

```text
src/verisight/evidence.py
```

Evidence can contain supported scalar values, nested mappings, and nested sequences.

Evidence attached to analytical domain models is recursively frozen.

Do not introduce separate ad hoc evidence types in individual subsystems unless a future requirement demonstrates that a genuinely different contract is needed.

---

## Ingestion Safety

Ingestion should preserve source meaning whenever possible.

Be particularly careful with:

- encodings
- delimiters
- missing-value interpretation
- significant leading zeros
- identifier-like numeric strings
- large integers
- ambiguous boolean-like values
- duplicate table names
- reserved relation names

Silent corruption is more dangerous than an explicit loading failure.

When ingestion behavior changes, add regression tests demonstrating the source representation and the expected normalized result.

---

## Determinism

Core analysis should remain deterministic.

Given the same supported input and configuration, deterministic layers should produce the same:

- normalized identities
- schemas
- profiles
- statistics
- quality findings
- ordering
- evidence
- summaries
- deterministic insights

AI-assisted functionality added later should consume these deterministic results rather than changing the meaning of the underlying measurements.

---

## Adding New Functionality

When adding functionality, identify the correct architectural layer first.

Examples:

```text
Source parsing or normalization
    -> ingestion

Logical data interpretation
    -> schema

Statistical measurement
    -> profiling

Deterministic quality finding
    -> quality

Dataset-level analytical composition
    -> analysis

Cross-layer structured evidence
    -> shared evidence contract
```

Do not place functionality in a higher-level layer simply because it is convenient if a lower-level subsystem should own the underlying concept.

---

## Documentation

The root `README.md` should remain focused on:

- what VeriSight is
- current capabilities
- installation
- high-level architecture
- development entry points
- project status

Detailed engineering documentation belongs in `docs/`.

Current engineering documentation includes:

```text
docs/
├── architecture.md
└── development.md
```

Documentation should describe implemented behavior.

Avoid documenting speculative modules, APIs, classes, or workflows as though they already exist.

Future architecture can be discussed explicitly as future work when necessary, but it should remain clearly separated from implemented functionality.

---

## Before Every Commit

At minimum, verify:

```text
[ ] Intended implementation is complete
[ ] Relevant tests were added or updated
[ ] Ruff formatting passes
[ ] Ruff linting passes
[ ] mypy strict checking passes
[ ] Complete pytest suite passes
[ ] Coverage remains at the required threshold
[ ] git diff contains only intended changes
[ ] Staged diff contains the complete coherent change
[ ] Documentation is updated when a public or architectural contract changed
```

The goal is not only to keep the test suite green, but to keep VeriSight's contracts stable, deterministic, understandable, and safe for the layers that will be built on top of them.
