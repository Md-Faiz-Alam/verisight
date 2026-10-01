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
