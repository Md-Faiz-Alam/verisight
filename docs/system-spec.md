# VeriSight system specification

Specification version 2, written against the code at commit `4690564`. It defines
what VeriSight is built to do and how each claim is checked. A capability not
listed here is not promised.

## Scope

VeriSight is a local analytical application for one person on one computer. There
is no deployment and there are no user accounts. Your original files stay yours
and are never changed.

## Supported input

| Limit | Value |
| --- | --- |
| Formats | CSV, TSV, JSON, JSONL, XLS, XLSX |
| Website upload | 20 MB per file, up to 5 files per upload |
| Temporary copies held at once | 100 uploads; beyond that the oldest is removed |
| Copies kept loaded for fast charts | 4 uploads, within 60 MB of files |

File size alone does not bound memory, because rows and columns vary. The largest
files tested live are 42,049 rows by 6 columns and 10,000 rows by 14 columns. Files
near the 20 MB limit were tested only for memory, with scripted replies (see target
M1).

### Temporary uploaded copies

The website works on a temporary copy of each upload. A copy is deleted when you
remove it or 60 minutes after upload. Expired copies are removed on a check that
runs every 60 seconds. A normal shutdown removes all copies. After a crash or power
loss, copies older than the 60 minutes are removed the next time the website starts.

## Supported questions

| Supported | Not supported |
| --- | --- |
| Counts and counts of different values | Forecasts and predictions |
| Totals, averages, medians, highest and lowest | Opinions and recommendations |
| Filters on values, dates and ranges | Answers from outside the uploaded data |
| Joins between uploaded files | Several separate answers in one question |
| Differences and percentages | |

A question VeriSight cannot support with evidence gets no number. It says so
instead of guessing.

## Usage limits

| Limit | Value |
| --- | --- |
| Questions running at once | 2 |
| Questions per hour | 30 |
| Investigation budget | 180 seconds on the website |

The investigation budget covers the analysis steps. Loading and profiling happen
before it starts, so it is not a guarantee of total response time.

### Tested model configuration

| Role | Model |
| --- | --- |
| Main work | `gemini-3.1-flash-lite` |
| Second query | `gemini-3.5-flash-lite` |

These are settings, not fixed parts of the system. If no second-query model is
set, the main model writes the second query. Quotas depend on the project, model
and usage tier, and capacity can vary. Retries, repairs and second queries make the
number of calls per question variable, so no number of questions per day is
promised.

## Data disclosure

VeriSight does not upload the source file as an attachment. AI-assisted analysis
sends dataset-derived context and query results to Gemini. These may include raw
values. Up to 20 result rows may be disclosed per query, and multiple queries may
disclose more. For small datasets, this can include all records. Use non-sensitive
data only.

How Google may use submitted data depends on the service and account conditions.
See the [Gemini API terms](https://ai.google.dev/gemini-api/terms).

## Trust checks

| Entry point | Number matched to SQL | SQL audit and second query |
| --- | --- | --- |
| Website and its API | Attempted on every model answer | Attempted on every model answer |
| Command line | Attempted on every model answer | Attempted with `--cross-check` |
| Python API | Attempted on every model answer | Attempted with `cross_check=True` |

A check attempted is not always a check completed:

| State | Meaning | Effect on the answer |
| --- | --- | --- |
| Completed | The check ran and passed | Counts toward "Verified" |
| Failed | The check ran and found a problem | "Needs review" at best |
| Skipped | The check could not run, for example after a provider failure or deadline, or it only repeated the first query | "Number matches SQL only" at best |
| Not requested | The command line ran without `--cross-check` | Trust level is `not_run`, with the reason |

An exact question answered by fixed rules uses no model, so it has no second query
and is labelled "Computed without AI".

## Targets

**Kind:** a *predeclared* target was first stated at commit `4690564`, before its
result existed. A *regression* target protects a result that was already known.

**Status:** `planned`, `passed` or `failed`, with its evidence.

| ID | Kind | Target | Status | Evidence |
| --- | --- | --- | --- | --- |
| D1 | Regression | Supported damage types are repaired to the intended values: at least 42 of the 43 in the frozen list, with no value read wrongly | passed | [`test_damaged_files.py`](../tests/test_damaged_files.py) |
| D2 | Regression | Ambiguous damage is rejected or flagged, never guessed | passed | [`test_damaged_files.py`](../tests/test_damaged_files.py) |
| A1 | Regression | Missed mistakes: of the 31 frozen wrong queries, at least 75% are caught | passed | [`test_audit_corpus.py`](../tests/test_audit_corpus.py) |
| A2 | Regression | False warnings: none on the 31 frozen correct queries | passed | [`test_audit_corpus.py`](../tests/test_audit_corpus.py) |
| C1 | Predeclared | Fewer wrong answers shown prominently than plain Gemini | passed | [`results.md`](results.md#comparison-with-plain-gemini-30-questions-4-unseen-datasets) |
| C2 | Predeclared | At most 10 percentage points fewer correct answers delivered than plain Gemini, across all submitted questions | failed | [`results.md`](results.md#comparison-with-plain-gemini-30-questions-4-unseen-datasets) |
| C3 | Predeclared | False warnings on at most 10% of correct answers | failed | [`results.md`](results.md#comparison-with-plain-gemini-30-questions-4-unseen-datasets) |
| C4 | Predeclared | Wrong numbers visible anywhere, including with a warning, are reported separately from prominent ones | passed | [`results.md`](results.md#comparison-with-plain-gemini-30-questions-4-unseen-datasets) |
| R1 | Predeclared | Concurrency, expiry, eviction, restart and crash-recovery tests pass | passed | [`test_web_reliability.py`](../tests/test_web_reliability.py) |
| R2 | Predeclared | A failed mandatory check can never produce "Verified"; evidence already computed stays visible with its incomplete status | passed | [`test_web_reliability.py`](../tests/test_web_reliability.py) |
| R3 | Predeclared | A provider failure never produces a number that was not computed | passed | [`test_web_reliability.py`](../tests/test_web_reliability.py) |
| M1 | Predeclared | Peak process memory under 1 GB across a full local workload: loaded datasets, profiling, two questions at once and second queries | passed | 781 MiB, [`measure_memory.py`](../evaluation/measure_memory.py) |
| W1 | Predeclared | Browser tests pass in Chromium at 1280×800 and 375×812 for upload, asking, reading results, errors and keyboard use, with exact numbers and trust labels | planned | |

C1 to C4 were measured at commit `ea707d4`. Fixes for the failures in C2 and C3
were made afterwards and need new questions to be measured.

M1 was measured on this computer with scripted replies and generated data: five
uploads of one 19.5 MB file with charts, two questions at once with second queries,
then one upload of five such files. It first reached 1,442 MiB and failed. After
freeing unused memory promptly, it reached 781 MiB. Real files can differ, and the
measurement on a deployed container is still to be done.

**Definitions.** *Caught* means the audit or the population review reports at least
one problem for that query. *Shown prominently* means the large answer on the
website, which appears only for "Verified" and "Computed without AI". *Review-only*
means the answer appears as text beside a warning.

## What these checks do not prove

A matched number shows that the number came from an executed query, not that the
query means what the question asked. A second query can share a mistake with the
first. No warnings on a finite test set does not mean there are no false warnings
in general. The audit test set was written with the audit in view. All testing so
far was done by the project's own side, and no outside user has tried the system.
