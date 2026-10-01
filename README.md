# VeriSight

VeriSight is an autonomous, evidence-backed AI data analyst.

The project is being built as a layered data-analysis system that can ingest structured data, infer schemas, profile datasets, detect deterministic data-quality issues, and produce structured analytical summaries and insights.

The current implementation focuses on a reliable deterministic analysis foundation. Higher-level querying, verification, reporting, and AI-assisted analysis will build on top of this foundation.

## Current Status

VeriSight currently provides the core deterministic data-analysis pipeline:

- structured file ingestion
- dataset normalization
- schema inference
- column and table profiling
- missing-value analysis
- duplicate-row analysis
- deterministic data-quality rules
- deterministic analytical summaries
- deterministic analytical insights
- immutable structured evidence
- unified analysis results

The project is under active development and does not yet expose a public CLI, HTTP API, or user interface.

## Requirements

- Python 3.11 or newer

## Installation

Clone the repository and create a virtual environment.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

The development dependencies include:

- pytest
- pytest-cov
- Ruff
- mypy
- pandas type stubs

## Supported Data Sources

### CSV

VeriSight supports CSV ingestion with:

- comma, semicolon, tab, and pipe delimiter detection
- quoted fields
- UTF-8
- UTF-8 with BOM
- UTF-16 with little-endian BOM
- UTF-16 with big-endian BOM
- Windows-1252 fallback
- preservation of empty fields as missing values
- preservation of significant leading zeros
- protection against unsafe conversion of long integer identifiers
- deterministic inference of numeric and boolean values

### Excel

Excel workbooks are supported through the Excel ingestion subsystem.

Workbook sheets are normalized into individual VeriSight tables.

The project includes support for Excel formats handled by the configured `openpyxl` and `xlrd` dependencies.

### JSON

JSON files are supported through the JSON ingestion subsystem and normalized into VeriSight table structures.

## Dataset Normalization

Files are normalized into a common dataset representation.

Each table maintains both:

- a display name
- a deterministic relation name

Relation names are sanitized for downstream analytical use and made unique within a dataset.

For example, duplicate table names are assigned deterministic relation identities such as:

```text
sales
sales_2
sales_3
```

Reserved relation names and names that cannot safely be used as identifiers are normalized automatically.

## Schema Inference

VeriSight infers logical schemas from loaded tables.

The inferred schema is used by the profiling layer rather than allowing each profiler to independently reinterpret the source data.

This provides a consistent contract between ingestion, profiling, quality analysis, and later analytical layers.

## Data Profiling

VeriSight generates deterministic profiles for datasets, tables, and columns.

Column profiling includes structural measurements such as:

- row count
- non-missing count
- missing count
- missing ratio
- distinct count
- distinct ratio

Type-specific profiling is available for supported logical types.

### Numeric Profiling

Numeric columns can include statistics such as:

- minimum
- maximum
- mean
- median
- standard deviation

### Text Profiling

Text columns can include statistics such as:

- minimum length
- maximum length
- mean length
- empty-string count
- empty-string ratio
- most frequent value
- most frequent value count
- most frequent value ratio

### Datetime Profiling

Datetime columns can include statistics such as:

- earliest value
- latest value
- time span
- timezone information

### Missing-Value Analysis

Table-level missing-value statistics include:

- total cell count
- missing cell count
- missing cell ratio
- rows containing missing values
- fully missing rows
- columns containing missing values

### Duplicate Analysis

Table-level duplicate statistics include:

- duplicate row count
- duplicate row ratio
- duplicate-group row count
- duplicate-group row ratio

These statistics are represented canonically in the table profile and reused by downstream analysis.

## Data-Quality Analysis

VeriSight currently detects deterministic data-quality findings including:

- missing values
- entirely missing columns
- fully missing rows
- duplicate rows
- empty strings
- constant columns
- high-cardinality columns

Quality findings include structured metadata such as:

- issue type
- severity
- scope
- table identity
- relation identity
- optional column identity
- affected count
- affected ratio
- human-readable message
- structured evidence

Quality rules operate on the canonical profiling results rather than independently recomputing dataset statistics.

## Evidence Model

VeriSight uses a shared evidence contract for structured analytical evidence.

Evidence supports:

- strings
- integers
- floating-point values
- booleans
- `None`
- nested mappings
- nested sequences

Evidence is recursively snapshotted into immutable structures.

This prevents downstream consumers from accidentally modifying evidence after an issue or insight has been created and provides a stable contract for future verification, reporting, API, and AI layers.

## Analysis Pipeline

The current deterministic pipeline can be represented conceptually as:

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

The analysis layer preserves deterministic ordering and relation identities throughout the pipeline.

## Analytical Summaries and Insights

VeriSight can build a unified deterministic result from a dataset analysis.

A `DatasetAnalysisResult` contains:

- the underlying dataset analysis
- an analytical summary
- generated analytical insights

Current insight categories include:

- dataset structure
- table structure
- data quality

Insights preserve structured evidence and table/relation identity so that later consumers can reason about findings without parsing human-readable messages.

## Project Structure

```text
src/verisight/
├── analysis/
│   ├── insights.py
│   ├── models.py
│   ├── result.py
│   ├── service.py
│   └── summary.py
├── ingestion/
│   ├── loaders/
│   │   ├── base.py
│   │   ├── csv.py
│   │   ├── excel.py
│   │   └── json.py
│   ├── dispatcher.py
│   ├── exceptions.py
│   ├── models.py
│   ├── schema.py
│   ├── service.py
│   └── validation.py
├── profiling/
│   ├── column.py
│   ├── dataset.py
│   ├── duplicates.py
│   ├── missing.py
│   ├── models.py
│   └── table.py
├── quality/
│   ├── models.py
│   └── rules.py
├── config.py
├── evidence.py
├── exceptions.py
└── logging.py
```

## Development Quality Gates

The project uses Ruff for formatting and linting, mypy in strict mode for static type checking, and pytest for testing.

Run the complete development quality gate with:

```powershell
ruff format .

ruff format --check .
ruff check .
mypy src tests

pytest --cov=verisight --cov-report=term-missing --cov-fail-under=100
```

The current Phase 3 baseline passes:

```text
343 passed
100% test coverage
```

The coverage configuration includes branch coverage.

## Design Principles

VeriSight is being developed around several core principles:

### Deterministic Before Generative

Structural analysis, profiling, quality detection, and evidence generation are deterministic.

Future AI capabilities should consume these verified structures rather than replace them with ungrounded inference.

### Evidence-Backed Analysis

Analytical findings should carry structured evidence that downstream systems can inspect, verify, serialize, and present.

### Stable Domain Contracts

Core models such as dataset profiles, quality findings, and evidence are designed as explicit contracts between system layers.

### Preserve Source Meaning

Ingestion avoids unsafe type conversion when doing so could change the meaning of source data, including significant leading zeros and large identifier-like integers.

### Immutable Analytical Results

Core analytical models use immutable representations where appropriate so downstream processing cannot silently alter previously generated findings.

### Deterministic Identity

Display names and analytical relation identities are kept separate so duplicate or unsafe source names do not create ambiguity downstream.

## Testing

The test suite covers the ingestion, schema, profiling, quality, evidence, and analysis layers.

It includes robustness and integration tests for areas such as:

- CSV parsing and encoding
- schema inference
- ingestion normalization
- numeric profiling
- datetime profiling
- text profiling
- missing values
- duplicate rows
- messy datasets
- data-quality rules
- immutable evidence
- deterministic analysis
- analytical summaries and insights

The project currently maintains a 100% coverage requirement for both statements and configured branches.

## Roadmap

The deterministic analysis foundation is complete through the current Phase 3 milestone.

Future development will build additional capabilities on top of these contracts, including analytical execution, verification, reporting, and AI-assisted workflows.

Features described as future work are not part of the current public implementation.

## License

VeriSight is licensed under the MIT License.
