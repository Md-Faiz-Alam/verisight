# Controlled analytical correctness evaluation

## Scope and commands

`tests/test_analytical_correctness_benchmark.py` adds ten synthetic question
fixtures across five domains. Each has a control query and an intentionally
incorrect query, producing twenty pipeline tests.

```powershell
python -m pytest tests/test_analytical_correctness_benchmark.py -q
python -m pytest tests/test_verification_benchmark.py tests/test_analytical_correctness_benchmark.py -q
```

The tests use real CSV ingestion, schema/profiling, SQL validation, DuckDB
execution, structured synthesis parsing, numerical verification, serialization,
and evaluation scoring. Planning and investigator decisions are scripted, and
the synthesis provider is replaced with deterministic text. No API calls occur.

These are known development fixtures, not a held-out benchmark or a measurement
of a model's ability to generate SQL.

## Independent answers

Expected answers are fixed with each fixture. They are not calculated from the
query output or generated claim. The following arithmetic explains the oracle
in the metric's stated units.

| Fixture | Independent calculation | Correct answer | Wrong-query answer |
| --- | --- | --- | --- |
| Signed posted transaction mean | `(0.5 - 0.25 + 1.25) / 3` | `0.5` | `0.875` |
| Principal-weighted annual rate | `(1000 * 1.5 + 3000 * 2.5) / 4000` | `2.25` | `2` |
| Recorded completed wait mean | `(1.25 + 2.5) / 2` | `1.875` | `1.25` |
| Patients with a readmission | `100 * 3 / 8` distinct patients | `37.5` | `50` |
| Order totals counted once | `10.5 + 10.5 + 20.25` | `41.25` | `62.25` |
| Selling price per unit | `(1 * 10.5 + 3 * 20.5) / 4` | `18` | `15.5` |
| Known inspection defect rate | `100 * 3 / 8` known outcomes | `37.5` | `30` |
| Pooled batch defect rate | `100 * 1 / (2 + 6)` | `12.5` | `25` |
| Mean signed delivered delay | `(0.5 + 1.5 - 0.25 + 0.25) / 4` | `0.5` | `0.625` |
| Pooled route on-time rate | `100 * (1 + 1 + 1 + 0) / (1 + 1 + 2 + 4)` | `37.5` | `62.5` |

The errors deliberately change analytical meaning: dropping refunds, ignoring
weights, imputing missing waits as zero, counting encounters instead of patients,
multiplying order totals through joins, including unknown outcomes, averaging
batch/route percentages without weights, and losing the sign of early arrivals.

The repeated `10.5` order totals are intentional. Equal values belong to distinct
orders; deduplicating amounts is not equivalent to deduplicating order identities.

All expected answers in this increment have finite decimal representations.
No comparison tolerance, presentation-rounding policy, or SQL rounding is used
to hide discrepancies.

## Control baseline and acceptance

The baseline is explicitly supplied control SQL for each question. The alternate
SQL is an injected semantic error. This is not a comparison against another AI
system or an independently implemented analyst.

Both synthesis responses accurately repeat their respective query cells. The
numerical verifier must therefore return `supported` for both paths. The
independent oracle and evaluator must distinguish them:

| Path | Evidence verdict | Ground-truth agreement | Evaluation outcome |
| --- | --- | --- | --- |
| Control query | `supported` | Yes | `correct_numeric` |
| Incorrect query | `supported` | No | `incorrect_numeric` |

Both paths can have zero unlinked tokens and `all_digits_parsed`. Neither
condition establishes analytical correctness. Narrative verification remains
false. Original SQL, numerical evidence, and verdicts survive serialization.

The tests fail if either SQL path produces a value other than its independently
specified fixture value, if an incorrect answer is scored as correct, or if
claim/evidence checks stop reflecting the executed result.

## Limits and next evaluation work

These tests establish controlled pipeline and scorer behavior. They do not show
that VeriSight detects bad SQL semantics autonomously, handles unfamiliar
schemas reliably, or generates useful follow-up investigations.

Next work includes independently labeled multi-step questions, held-out
fixtures, insufficient-evidence cases, a defined model or system comparison,
and reproducible live runs. Report all attempted cases and distinguish provider
availability, completion, correctness, and latency. The live runner's five
fixtures remain separate from this ten-question offline increment.

See [Development](development.md) for the full gate and live evaluation controls,
and [Architecture](architecture.md) for verification boundaries.