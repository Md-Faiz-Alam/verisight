# VeriSight

An evidence-verifying autonomous investigator for structured tabular datasets.

VeriSight loads and profiles data, executes analytical SQL, and supports
Gemini-driven investigations. Its default synthesizer produces structured
numerical claims that application code checks against collected query results.

A supported number does not establish that the SQL, interpretation, or narrative
is correct. Narrative verification remains explicitly false.

## Current capabilities

| Capability | Status |
| --- | --- |
| CSV, JSON, and Excel ingestion | Implemented |
| Schema inference, profiling, and data-quality analysis | Implemented |
| Validated DuckDB queries with configured resource limits | Implemented |
| Gemini planning, query repair, and bounded investigations | Implemented |
| Structured synthesis and numerical claim verification | Implemented |
| Application-rendered statements linked to claims | Implemented |
| Limited narrative token audit and Unicode digit coverage | Implemented |
| Evidence recovery for tested expected workflow failures | Implemented |
| Safe failure metadata and generation telemetry | Implemented |
| Deterministic tests and five synthetic live evaluation cases | Implemented |
| Python 3.11 CI on Windows and Linux | Implemented |
| Narrative meaning and analytical correctness on unfamiliar data | Not established |
| End-user application and production deployment | Remaining work |

## Installation

Python 3.11 or newer is required. CI currently exercises Python 3.11.

Windows PowerShell, from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Local analysis and SQL

This example uses temporary synthetic data and requires no Gemini API key.

```python
from pathlib import Path
from tempfile import TemporaryDirectory

from verisight import VeriSight
from verisight.config import Settings

with TemporaryDirectory() as directory:
    path = Path(directory) / "transactions.csv"
    path.write_text(
        "amount,state\n100,posted\n-20,posted\n50,pending\n",
        encoding="utf-8",
    )
    app = VeriSight(settings=Settings(allow_llm_data_disclosure=False))
    analysis = app.analyze(path)
    result = app.execute(
        path,
        "SELECT SUM(amount) AS net_amount FROM transactions WHERE state = 'posted'",
    )
    print(result.columns)
    print(result.rows)
```

Expected query result: column `net_amount`, row `(80,)`.

| Method | Purpose | Return type |
| --- | --- | --- |
| `analyze(paths)` | Profile data and assess quality | `DatasetAnalysisResult` |
| `execute(paths, query)` | Execute supplied analytical SQL | `QueryResult` |
| `ask(paths, question)` | Plan and execute a question | `QueryResult` |
| `investigate(paths, question, max_steps=5)` | Investigate and synthesize | `InvestigationResult` |

Inputs accept a string path, a `Path`, or an iterable of either. Empty inputs
and invalid entries are rejected. `ask()` does not expose planning or repair
history in its return value.

## Gemini investigations

Configure a local `.env` file or environment variables:

```dotenv
VERISIGHT_GEMINI_API_KEY=replace-with-your-key
VERISIGHT_ALLOW_LLM_DATA_DISCLOSURE=true
```

Set `VERISIGHT_GEMINI_MODEL` to override the configured model. Check available
models and quotas for your provider project. Disclosure permission defaults to
false. Enabling it permits built-in generation to send analytical context,
including schema, profiles, questions, and query observations.

The API key is excluded from normal Settings serialization and representation.
It remains a string accessible to application code. Never commit credentials
or private datasets.

With Gemini configured and a supported dataset available:

```python
from verisight import VeriSight
from verisight.config import Settings

app = VeriSight(settings=Settings())
result = app.investigate(
    "transactions.csv",
    "What is the net posted amount? Exclude pending transactions.",
    max_steps=3,
)
print(result.status.value)
print(result.conclusion)
print(result.narrative_digit_coverage)
for statement in result.quantitative_statements:
    print(statement.text)
```

`max_steps` limits analytical attempts, including failed attempts. It does not
limit provider calls: decisions, planning, repair, and synthesis may each
require generation. `StructuredInvestigationSynthesizer` is the default for
configured Gemini investigations. Custom components can be injected.

## Verification and narrative audit

Claims reference observation rows and named columns. Supported operations are
`value` and `difference` (left minus right). Verdicts are `supported`,
`contradicted`, or `unverifiable`.

Structured model-generated claims require decimal strings and use zero
tolerance. The model cannot choose a tolerance. A rounded presentation can
therefore be contradicted. An application-controlled rounding policy remains
future work.

Results expose `generated_claims`, `verified_claims`, and application-rendered
`quantitative_statements`. The fixed scope is
`verification_scope="referenced_numeric_values_only"`; `narrative_verified`
remains false. A `complete` workflow does not certify answer correctness.

The conclusion has two supplementary diagnostics:

- `narrative_numbers` and `unlinked_numbers` compare supported ASCII numerical
  tokens with submitted claim values. Equal values do not establish semantic
  linkage, and tokens can link to contradicted claims.
- `narrative_digit_coverage` counts Unicode digit characters inside and outside
  successfully parsed tokens. Its statuses are `no_digits`, `all_digits_parsed`,
  and `unparsed_digits`.

Neither diagnostic verifies narrative meaning. `all_digits_parsed` does not
validate signs, units, or truth. `no_digits` can include number words.
Unsupported formats such as `12k`, `3.5x`, Unicode minus, and ranges can produce
`unparsed_digits` even when `unlinked_numbers` is empty.

A wrong join, filter, or denominator can produce a number that a claim correctly
repeats. Numerical verification does not establish causation, source quality,
or completeness of generated claims.

## Partial results and safe diagnostics

Observations retain questions, SQL, and query results. Expected synthesis
failures return `incomplete` with observations and optional `synthesis_failure`.
After at least one successful observation, expected investigator failures and
provider failures during planning or repair return `incomplete` with
`investigation_failure`. Later query-attempt prompt-budget failures also
preserve observations.

Provider failures before evidence collection can still raise. Unexpected
programming errors propagate. Recovery is not a guarantee that every possible
failure returns a partial result.

`run_public_operation` converts raised exceptions into fixed public errors.
A returned incomplete investigation is a successful operation value: inspect
its workflow status and failure metadata. `to_jsonable` in
`verisight.serialization` prepares results for JSON, preserving Decimal values
as strings.

Safe provider diagnostics include HTTP status, retryability, attempts, a coarse
stage, and a per-client call number. Evaluation telemetry records generation
attempts, elapsed time, and whether text returned, without prompts or responses.
Returning text does not imply valid JSON or a correct answer.

## Evaluation

Run the deterministic development benchmark:

```powershell
python -m pytest tests/test_verification_benchmark.py -q
```

The opt-in live evaluator uses five temporary synthetic fixtures: finance,
retail, manufacturing, healthcare, and logistics. Each permits one analytical
step and scores one numerical answer against an independent expected value.

```powershell
python -m scripts.live_evaluation --live --case finance
New-Item -ItemType Directory -Force reports/evaluations | Out-Null
$evaluationStamp = Get-Date -Format "yyyyMMdd-HHmmss-fff"
python -m scripts.live_evaluation --live --case all --request-timeout-seconds 60 --provider-retries 1 --output "reports/evaluations/live-$evaluationStamp.json"
```

Live calls require a key and may incur charges. The evaluator enables disclosure
for its synthetic fixtures. Defaults remain 20 seconds per request and zero
additional provider retries; overrides are recorded.

JSON is printed and optionally saved with `--output`. The parent directory must
exist and an existing file is never overwritten. Reports retain revision,
tracked-change status, settings, timings, outcomes, audits, and available failure
and generation metadata. Older reports may lack newer fields.

`correct_numeric` scores the submitted metric; it does not certify prose or SQL
semantics. `no_claims` is not automatically a justified abstention. Retain failed
runs. These known fixtures are not a held-out generalization benchmark.

## Quality gates and CI

```powershell
ruff format --check .
ruff check .
mypy --strict src tests scripts
python -m pytest --cov=verisight --cov=scripts --cov-report=term-missing --cov-fail-under=100
git diff --check
```

[GitHub Actions](https://github.com/Md-Faiz-Alam/verisight/actions) runs these gates
on Windows and Linux with Python 3.11 for pushes to `main`, pull requests, and
manual dispatch. CI uses offline tests without provider credentials. Full
statement and branch coverage measures exercised paths, not universal accuracy.

## Remaining work

- Define controlled rounding and evaluate analytical semantics independently.
- Expand held-out questions, multi-step cases, and baseline comparisons.
- Expose failed-attempt and repair history.
- Improve nullable Excel boolean inference and identifier-quoting guidance.
- Remove private cross-object configuration in legacy synthesis.
- Build the user workflow, report export, and deployment acceptance evidence.

See [Architecture](docs/architecture.md), [Development](docs/development.md),
and [Roadmap](docs/roadmap.md).

## Dataset attribution

Local development has used Bank Marketing, associated with:

Moro, S., Cortez, P., and Rita, P. (2014).
*A Data-Driven Approach to Predict the Success of Bank Telemarketing.*
Decision Support Systems, 62, 22–31.

Source: [UCI Bank Marketing](https://archive.ics.uci.edu/dataset/222/bank+marketing).
Check applicable licensing before redistribution. Local datasets are not part
of the standard source-code commit workflow.

## License

MIT. See [LICENSE](LICENSE).