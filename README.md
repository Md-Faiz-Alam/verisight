# VeriSight

An evidence-verifying autonomous investigator for structured tabular datasets.

VeriSight loads data, profiles its structure and quality, executes analytical SQL,
and supports Gemini-driven investigations. Its default investigation synthesizer
produces structured numerical claims that are checked against collected query
results.

Numerical support does not establish that a narrative, SQL query, or analytical
interpretation is correct.

## Current capabilities

| Capability | Status |
| --- | --- |
| CSV, JSON, and Excel ingestion | Implemented |
| Schema inference, profiling, and data-quality analysis | Implemented |
| Validated analytical SQL execution with DuckDB | Implemented |
| Gemini-driven query planning and repair | Implemented |
| Bounded multi-step investigations | Implemented |
| Structured synthesis with automatic numerical verification | Implemented |
| Safe public error reports and provider diagnostics | Implemented |
| Deterministic verification benchmark | Implemented |
| Opt-in synthetic live evaluation | Implemented |
| Verification of narrative meaning and claim completeness | Not established |
| General analytical correctness across unfamiliar domains | Not established |
| Consistent preservation of observations after synthesis failures | Incomplete |
| End-user application and production deployment | Remaining work |

## Requirements and installation

Python 3.11 or newer is required.

From the repository root, using Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

On macOS or Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

## Local analysis and SQL

This example creates temporary synthetic data and requires no Gemini API key.

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

The public methods accept a file path or an iterable of file paths. Empty inputs
and invalid entries are rejected.

| Method | Purpose | Return type |
| --- | --- | --- |
| `analyze(paths)` | Deterministic profiling and quality analysis | `DatasetAnalysisResult` |
| `execute(paths, query)` | Execute supplied analytical SQL | `QueryResult` |
| `ask(paths, question)` | Plan and execute a natural-language query | `QueryResult` |
| `investigate(paths, question, max_steps=5)` | Investigate and synthesize findings | `InvestigationResult` |

`ask()` currently returns query data without a public planning or repair history.

## Gemini configuration

Settings load from environment variables and an optional `.env` file using the
`VERISIGHT_` prefix.

For the default Gemini components, configure:

```dotenv
VERISIGHT_GEMINI_API_KEY=replace-with-your-key
VERISIGHT_ALLOW_LLM_DATA_DISCLOSURE=true
```

Set `VERISIGHT_GEMINI_MODEL` when overriding the model configured in
`src/verisight/config.py`.

Disclosure permission defaults to false. Enabling it permits the built-in
generative workflow to send analytical context to Gemini. This context can
include schema, profiling information, questions, and query observations.

The API key is excluded from Settings representations and normal model
serialization. It remains available to application code as a string.

Never commit credentials or private datasets.

## Autonomous investigations

With Gemini configured and an existing supported dataset:

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
print(result.verification_scope)
print(result.narrative_verified)

for item in result.verified_claims:
    print(
        item.verification.status.value,
        item.verification.expected,
        item.verification.actual,
    )
```

`max_steps` limits analytical attempts. It is not a limit on the total number
of provider requests: investigation decisions, query planning, repair, and
synthesis can each require a request.

The default configured synthesizer is `StructuredInvestigationSynthesizer`.
Custom components can be injected for testing or alternative behavior.

## What numerical verification establishes

Generated claims refer to observation rows and named result columns.

The current supported operations are:

- `value`: compare an expected number with one evidence cell.
- `difference`: compare an expected number with left minus right evidence cells.

Each claim receives one verdict:

| Verdict | Meaning |
| --- | --- |
| `supported` | The referenced numerical evidence matches under the claim's comparison policy |
| `contradicted` | The numerical comparison could be performed and did not match |
| `unverifiable` | The evidence or required arithmetic could not be safely evaluated |

Structured model-generated claims use zero tolerance. The model cannot supply
its own tolerance. Rounded values can therefore be contradicted even when they
would be acceptable under a separate presentation-rounding policy.

Verification rejects unsuitable evidence such as booleans, numeric-looking
strings, non-finite values, ambiguous columns, and invalid references.

Every investigation result exposes:

- `generated_claims`
- `verified_claims`
- `verification_scope="referenced_numeric_values_only"`
- `narrative_verified=False`

A `complete` investigation means the workflow completed. It does not mean every
claim is supported or that the conclusion is correct.

The verifier does not establish:

- Whether the conclusion accurately expresses the submitted claims.
- Whether every material numerical statement has a submitted claim.
- Whether SQL uses the correct filters, joins, units, or denominator.
- Whether a relationship is causal.
- Whether the source data is accurate or representative.

A wrong query can produce a number that a claim correctly repeats.

## Evidence, errors, and serialization

Investigation observations retain analytical questions, SQL, and query results.
Use `verisight.serialization.to_jsonable` to prepare supported result objects
for JSON serialization.

`run_public_operation` in `verisight.public_api` converts exceptions into safe
public reports. Codes distinguish ingestion, query, configuration, prompt-budget,
and other failures. Retryable Gemini failures can map to `provider_unavailable`.

Unexpected internal failures are logged by exception type without raw exception
messages or tracebacks.

Provider exceptions can carry safe diagnostics: HTTP status, retryability,
attempt count, generation stage, and a per-client call number.

Some synthesis and provider failures still raise instead of returning an
incomplete investigation with accumulated observations.

## Evaluation

Run the deterministic benchmark:

```powershell
python -m pytest tests/test_verification_benchmark.py -q
```

It includes numerical verification scenarios across five domains and adversarial
cases demonstrating that numerical support does not establish analytical
correctness. These are development fixtures, not a held-out generalization test.

The opt-in live evaluator uses temporary synthetic data:

```powershell
python -m scripts.live_evaluation --live --case finance
python -m scripts.live_evaluation --live --case all
```

Live calls require a configured API key and may incur provider charges.
The evaluator explicitly enables disclosure for its synthetic fixtures.

Its three cases cover finance, retail, and manufacturing. Each permits one
analytical step and scores a single numerical answer against an independent
expected value.

Outcomes distinguish correct and incorrect numerical answers, unverified
answers, missing or ambiguous claims, incomplete investigations, and failures.
A `no_claims` response is not automatically a correct abstention.

The evaluator prints JSON. It does not automatically save a report.
Passing offline tests does not establish live-provider reliability.

## Development checks

Run from the repository root:

```powershell
ruff format --check .
ruff check .
mypy src tests scripts
python -m pytest --cov=verisight --cov=scripts --cov-report=term-missing --cov-fail-under=100
git diff --check
```

Coverage includes statements and branches. Full coverage measures exercised
code paths, not universal analytical correctness.

## Known limitations and next work

- Preserve observations and failure provenance when synthesis fails.
- Link report statements to structured claims.
- Introduce an application-controlled rounding policy.
- Expand independently scored evaluations and retain reproducible live results.
- Improve nullable Excel boolean inference.
- Expose investigation failure and repair history.
- Add identifier-quoting guidance to planning and repair prompts.
- Remove private cross-object configuration in the legacy synthesizer.
- Add continuous integration and establish deployment acceptance criteria.

See [Architecture](docs/architecture.md),
[Development](docs/development.md), and [Roadmap](docs/roadmap.md).

## Dataset attribution

Local development has used the Bank Marketing dataset associated with:

Moro, S., Cortez, P., and Rita, P. (2014).
*A Data-Driven Approach to Predict the Success of Bank Telemarketing.*
Decision Support Systems, 62, 22–31.

Dataset source:
[UCI Machine Learning Repository — Bank Marketing](https://archive.ics.uci.edu/dataset/222/bank+marketing).

Check applicable dataset licensing before redistribution. Local datasets are
not part of the standard source-code commit workflow.

## License

MIT. See [LICENSE](LICENSE).
