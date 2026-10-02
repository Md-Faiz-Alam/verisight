# VeriSight Architecture

## Overview

VeriSight is an autonomous, evidence-backed AI data analyst.

The system is designed as a layered analytical pipeline in which deterministic components establish reliable data structures, statistics, quality findings, and evidence before higher-level analytical or AI capabilities consume them.

The current architecture provides the deterministic foundation for:

- structured data ingestion
- dataset normalization
- schema inference
- dataset profiling
- data-quality analysis
- analytical summaries
- analytical insights
- immutable structured evidence
- unified analysis results

Future analytical execution, verification, reporting, API, and AI-assisted capabilities are intended to build on these contracts rather than bypass them.

---

## Architectural Principles

### Deterministic Before Generative

Structural analysis, schema inference, profiling, quality detection, and evidence generation are deterministic.

Future AI components should consume deterministic analytical results instead of independently interpreting raw source data when an established system contract already exists.

This keeps generated analysis grounded in reproducible measurements.

### Stable Domain Contracts

Each major layer exposes explicit domain models.

These models form contracts between subsystems and reduce coupling between implementation details.

Important contracts currently include:

- loaded tables and datasets
- inferred schemas
- column and table profiles
- missing-value statistics
- duplicate statistics
- quality issues
- analytical insights
- analytical summaries
- structured evidence
- unified analysis results

### Evidence-Backed Analysis

Analytical findings should carry structured evidence whenever appropriate.

Evidence is intended to support future:

- verification
- serialization
- reporting
- APIs
- analytical execution
- AI-assisted reasoning

Consumers should not need to parse human-readable messages to recover the underlying measurements.

### Preserve Source Meaning

Ingestion should avoid transformations that silently change the meaning of source data.

Examples include:

- preserving significant leading zeros
- preserving large identifier-like integers when numeric conversion could lose precision
- treating only intended empty fields as missing
- supporting common source encodings
- preserving display names independently from analytical relation identities

### Deterministic Identity

Human-readable table names and analytical relation names are separate concepts.

A table retains its display name while receiving a deterministic, dataset-unique relation name suitable for downstream analytical operations.

This prevents duplicate, reserved, or unsafe source names from introducing ambiguity.

### Immutable Analytical Results

Evidence associated with quality findings and analytical insights is recursively snapshotted into immutable structures.

This prevents downstream consumers from silently changing previously generated analytical evidence.

---

## System Pipeline

The current VeriSight pipeline is:

```text
Files
  |
  v
Ingestion
  |
  v
Normalized Dataset
  |
  v
Schema Inference
  |
  v
Profiling
  |
  v
Data-Quality Rules
  |
  v
Dataset Analysis
  |
  +--> Summary
  |
  +--> Insights
  |
  v
Unified Analysis Result
```

---

## Layer Responsibilities

### Ingestion

The ingestion layer converts supported source files into normalized VeriSight dataset structures.

Its responsibilities include:

- validating source files
- dispatching files to format-specific loaders
- loading CSV, Excel, and JSON data
- preserving source meaning where safe inference is ambiguous
- assigning deterministic relation identities
- rejecting duplicate table columns
- constructing normalized loaded datasets

The ingestion layer should not perform analytical interpretation. Its responsibility is to produce reliable dataset structures for downstream components.

### Schema Inference

Schema inference describes the structural shape of normalized tables.

Its responsibilities include:

- identifying columns
- recording physical and logical types
- identifying nullable columns
- preserving table and relation identity
- constructing dataset-level schema models

Schema inference provides structural metadata without replacing profiling or quality analysis.

### Profiling

The profiling layer computes deterministic descriptive statistics from normalized data.

Its responsibilities include:

- column profiling
- numeric statistics
- text statistics
- datetime statistics for supported datetime-typed data
- missing-value statistics
- duplicate-row statistics
- table-level statistics
- dataset-level profile aggregation

Profiles describe observed data. They do not themselves determine whether an observation constitutes a quality problem.

### Data-Quality Analysis

The quality layer evaluates deterministic rules against profiles and dataset structure.

Its responsibilities include detecting supported conditions such as:

- missing values
- entirely missing columns
- fully missing rows
- duplicate rows
- empty strings
- constant columns
- high-cardinality string columns

Quality findings are represented as structured `QualityIssue` objects containing scope, severity, identity, human-readable context, and machine-readable evidence.

### Dataset Analysis

Dataset analysis orchestrates schema inference, profiling, and quality evaluation into a single deterministic analytical model.

`DatasetAnalysis` is the central deterministic analysis contract containing:

- the inferred dataset schema
- the dataset profile
- generated quality issues

Higher-level deterministic components consume this contract rather than independently recomputing lower-level analysis.

### Summary Generation

The summary layer derives compact aggregate information from `DatasetAnalysis`.

`AnalysisSummary` includes information such as:

- table count
- total row count
- total column count
- issue counts by severity
- issue counts by scope
- affected relation identities

Summaries are derived views of an existing analysis and do not mutate or reinterpret the source analysis.

### Insight Generation

The insight layer converts supported deterministic findings into structured analytical insights.

`AnalysisInsight` preserves relevant dataset identity and evidence so downstream consumers can work with structured findings rather than parsing prose.

Insight generation is deterministic. Generative AI is not required to create the current insight models.

### Unified Analysis Result

`DatasetAnalysisResult` combines:

- the complete `DatasetAnalysis`
- its deterministic `AnalysisSummary`
- generated `AnalysisInsight` objects

`AnalysisResultBuilder` constructs this result from an existing dataset analysis.

The unified result is the primary deterministic result boundary exposed by the high-level VeriSight facade and is designed for consumption by reporting systems, APIs, analytical execution, persistence layers, and AI-assisted components.

### Public Analysis Facade

`VeriSight` provides the high-level Python entry point for dataset analysis.

```python
from verisight import VeriSight

result = VeriSight().analyze(["data/customers.csv"])
```
The facade coordinates existing deterministic components rather than duplicating their responsibilities:

```text
VeriSight
   |
   v
DatasetLoader
   |
   v
LoadedDataset
   |
   v
DatasetAnalyzer
   |
   v
DatasetAnalysis
   |
   v
AnalysisResultBuilder
   |
   v
DatasetAnalysisResult
```

---

## Key Contracts

### Loaded Data

Loaded data models represent normalized source data before analytical processing.

A loaded table maintains both:

- a human-readable display name
- a deterministic analytical relation name

These identities serve different purposes and should not be conflated.

### Schema

Schema models describe dataset structure independently from observed statistical profiles.

This separation allows structural metadata and statistical observations to evolve without forcing them into a single model.

### Profiles

Profile models contain deterministic measurements derived from loaded data.

Table-level statistics are canonical within table profiles, while dataset profiles aggregate table profiles without maintaining competing copies of the same measurements.

### Quality Issues

A `QualityIssue` represents one deterministic data-quality finding.

It records:

- issue type
- severity
- scope
- table identity
- relation identity
- optional column identity
- affected counts or ratios when applicable
- a human-readable message
- structured evidence

### Evidence

Evidence is a shared cross-layer contract.

Evidence values are recursively validated and frozen when attached to analytical findings. Nested mappings become immutable mappings and nested sequences become tuples.

Supported evidence is restricted to JSON-compatible scalar meaning plus recursively nested mappings and sequences. NumPy scalar values are normalized to their corresponding Python scalar values before freezing.

Evidence rejects unsupported binary values, non-string mapping keys, and non-finite floating-point values.

Frozen evidence can be converted into an independent JSON-safe mutable representation through `evidence_to_jsonable()`. Evidence serialization delegates to the shared domain serializer so JSON conversion behavior is defined in one place.

### Serialization

`verisight.serialization` defines the shared JSON serialization boundary for VeriSight domain objects.

`to_jsonable()` recursively converts supported domain values into ordinary JSON-compatible Python values. It supports dataclasses, enums, paths, mappings, sequences, NumPy scalar values, temporal values, decimal values, and supported missing-value representations.

Datetime and date values are serialized using ISO 8601 strings. Timedeltas use ISO 8601 duration strings. Finite `Decimal` values are serialized as strings to preserve their exact decimal representation.

Pandas missing values and non-finite numeric values that reach the serialization boundary are represented as `None`, allowing the resulting structure to be serialized with strict JSON settings such as `json.dumps(..., allow_nan=False)`.

Mappings must use string keys, and binary or otherwise unsupported values are rejected explicitly.

This serializer is intentionally separate from the analytical models themselves. Domain models preserve deterministic analytical meaning, while `to_jsonable()` defines how those models cross JSON, API, reporting, or persistence boundaries.

### Analysis Results

Analysis results compose existing deterministic contracts instead of duplicating them.

This keeps schema, profile, issue, summary, insight, and evidence semantics explicit and independently testable.

---

## Dependency Direction

The intended dependency direction is:

```text
Ingestion
   |
   v
Schema / Profiling
   |
   v
Quality
   |
   v
Dataset Analysis
   |
   +--> Summary
   |
   +--> Insights
   |
   v
Unified Result
   |
   v
Future Facade / Reporting / APIs / AI
```

Higher-level layers may depend on lower-level contracts.

Lower-level deterministic layers should not depend on future presentation, API, database-query, or generative-AI layers.

This keeps the deterministic analytical core independently testable and reusable.

---

## Current Boundary

The current architecture exposes the unified deterministic analysis result through the high-level `VeriSight` Python facade.

The repository does not yet provide the planned DuckDB analytical execution layer, reporting interface, external API, or generative-AI orchestration layer.

Those capabilities should be introduced above the existing deterministic contracts and public analysis facade rather than embedded into ingestion, profiling, or quality-rule implementations.

This boundary is intentional: VeriSight first establishes reproducible analytical facts and structured evidence, exposes them through a stable high-level analysis entry point, and allows future higher-level systems to consume those results.

---

## Testing and Contract Stability

The deterministic core is protected by automated tests covering ingestion, schema inference, profiling, quality rules, evidence, summaries, insights, and unified results.

Changes to shared models should be treated as contract changes.

In particular:

- source fidelity should not be weakened silently
- relation identities should remain deterministic
- canonical statistics should not be duplicated across competing models
- evidence should remain immutable after construction
- serialization boundaries should use explicit JSON-safe conversion
- summaries and insights should remain derived from deterministic analysis
- higher-level capabilities should reuse existing contracts rather than bypass them

This structure allows future analytical and AI capabilities to evolve while keeping the underlying measurements reproducible and testable.
