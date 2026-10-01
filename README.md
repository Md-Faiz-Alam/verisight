# VeriSight

VeriSight is an autonomous, evidence-backed AI data analyst.

The project is being built as a layered data-analysis system that can ingest structured data, infer schemas, profile datasets, detect deterministic data-quality issues, and produce structured analytical summaries and insights.

The current implementation focuses on a reliable deterministic analysis foundation. Higher-level analytical execution, verification, reporting, APIs, and AI-assisted analysis will build on top of this foundation.

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
- JSON-safe evidence conversion
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

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

The development dependencies include:

- pytest
- pytest-cov
- Ruff
- mypy
- pandas type stubs

## Quick Start

VeriSight currently exposes its deterministic analysis pipeline through Python APIs.

```python
from verisight.analysis.result import AnalysisResultBuilder
from verisight.analysis.service import DatasetAnalyzer
from verisight.config import Settings
from verisight.ingestion.service import DatasetLoader

settings = Settings()

dataset = DatasetLoader(settings).load(["data/customers.csv"])
analysis = DatasetAnalyzer().analyze(dataset)
result = AnalysisResultBuilder().build(analysis)

print(result.summary)
print(result.insights)
```

The pipeline is intentionally explicit:

```text
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

This keeps ingestion, deterministic analysis, and result construction as separate contracts.

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
- Latin-1 fallback when Windows-1252 cannot decode the source
- preservation of empty fields as missing values
- preservation of significant leading zeros
- protection against unsafe conversion of long integer identifiers
- deterministic inference of numeric and boolean values

UTF-16 input is supported when a recognized UTF-16 BOM is present.

BOM-less input containing NUL bytes is rejected instead of being silently interpreted as ordinary CSV text. UTF-32 input with a recognized BOM is also rejected because UTF-32 is not currently a supported CSV encoding.

These checks prefer an explicit load failure over silently returning corrupted columns or values.

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

Relation-name normalization currently handles unsafe identifier characters, names beginning with digits, empty normalized names, duplicate relation identities, and the reserved names explicitly defined by the ingestion subsystem.

The reserved-name set is intentionally explicit rather than a claim to cover every keyword used by every possible downstream SQL engine.

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
- finite floating-point values
- booleans
- `None`
- nested mappings with string keys
- nested sequences
- NumPy scalar inputs that can be normalized to supported Python scalar values

Evidence is validated and recursively snapshotted into immutable structures.

Nested mappings become immutable mappings, while nested sequences become tuples. NumPy scalar values are normalized to their corresponding Python scalar values.

The evidence contract rejects unsupported values that could make downstream behavior ambiguous, including:

- binary `bytes` and `bytearray` values
- non-string mapping keys
- non-finite floating-point values such as `NaN` and positive or negative infinity
- unsupported object types

This prevents downstream consumers from accidentally modifying evidence after an issue or insight has been created.

### JSON-Safe Evidence

Immutable evidence is deliberately separate from its serialization representation.

Use `evidence_to_jsonable()` when evidence must cross a JSON serialization boundary:

```python
import json

from verisight.evidence import evidence_to_jsonable

jsonable_evidence = evidence_to_jsonable(issue.evidence)
payload = json.dumps(jsonable_evidence)
```

The conversion recursively creates ordinary dictionaries and lists while preserving supported scalar values.

The returned representation is independent from the frozen evidence, so modifying the serialization representation does not mutate the analytical evidence stored by VeriSight.

This provides an explicit boundary between immutable internal analytical state and mutable JSON-compatible output.

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

Additional architecture and development documentation is available under `docs/`.

```text
docs/
├── architecture.md
└── development.md
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

The current verified deterministic-foundation baseline passes:

```text
360 tests passed
894 statements
170 branches
100% test coverage
```

The coverage configuration enables branch coverage.

## Design Principles

VeriSight is being developed around several core principles.

### Deterministic Before Generative

Structural analysis, profiling, quality detection, and evidence generation are deterministic.

Future AI capabilities should consume these verified structures rather than replace them with ungrounded inference.

### Evidence-Backed Analysis

Analytical findings should carry structured evidence that downstream systems can inspect, verify, serialize, and present.

Immutable internal evidence and JSON-safe serialization representations are intentionally separate contracts.

### Stable Domain Contracts

Core models such as loaded datasets, schemas, profiles, quality findings, summaries, insights, and evidence are designed as explicit contracts between system layers.

### Preserve Source Meaning

Ingestion avoids unsafe type conversion when doing so could change the meaning of source data, including significant leading zeros and large identifier-like integers.

When an unsupported encoding pattern could otherwise result in silent corruption, ingestion prefers a clear failure.

### Immutable Analytical Results

Core analytical models use immutable representations where appropriate so downstream processing cannot silently alter previously generated findings.

### Deterministic Identity

Display names and analytical relation identities are kept separate so duplicate or unsafe source names do not create ambiguity downstream.

## Testing

The test suite covers the ingestion, schema, profiling, quality, evidence, and analysis layers.

It includes robustness and integration tests for areas such as:

- CSV parsing, delimiters, and encodings
- schema inference
- ingestion normalization
- numeric profiling
- datetime profiling
- text profiling
- missing values
- duplicate rows
- messy datasets
- data-quality rules
- immutable and serializable evidence
- deterministic analysis
- analytical summaries and insights

The project currently maintains a 100% coverage requirement for statements and configured branches.

## Known Limitations

VeriSight is still under active development. Several behaviors are intentionally deferred rather than being handled through aggressive inference.

### Datetime Strings

String columns containing datetime-like values are not automatically treated as datetime columns in every ingestion path.

Datetime profiling currently operates on data that has already been represented with an appropriate datetime type.

More aggressive datetime-string inference is deferred because ambiguous date formats can change source meaning.

### Currency and Percentage Columns

Text values such as currency amounts or percentages are not automatically normalized into numeric values.

Examples include values such as:

```text
$1,250.00
€99.50
42%
```

Automatic normalization of these formats requires explicit parsing rules for symbols, locale conventions, separators, and scaling semantics.

### Nullable Booleans in JSON and Excel

Boolean inference behavior is not yet fully normalized across CSV, JSON, and Excel ingestion.

In particular, nullable boolean columns originating from JSON or Excel may not receive the same inferred representation as equivalent CSV input.

### CSV Performance

CSV ingestion currently prioritizes source fidelity, defensive encoding handling, and deterministic type inference over maximum throughput.

The loader may perform multiple passes or full-content checks during encoding detection and type inference. This is acceptable for the current development stage but is not intended to represent the final large-file performance architecture.

These limitations are documented explicitly so future improvements can address them without weakening the current deterministic contracts.

## Roadmap

The deterministic analysis foundation is complete through the current Phase 3 milestone.

The next development phase is expected to build higher-level capabilities on top of these contracts, including:

- a public analysis facade
- analytical execution
- DuckDB-backed querying
- verification
- reporting
- future API integration
- AI-assisted analytical workflows

These capabilities are future work and are not part of the current public implementation.

The existing deterministic contracts are intended to remain the foundation beneath these higher-level layers rather than being replaced by them.

## License

VeriSight is licensed under the MIT License. See `LICENSE` for the full license text.
