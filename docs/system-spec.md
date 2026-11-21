# VeriSight system specification

Specification version 3, written against the code at commit `42d7ce2`. It defines
what VeriSight is built to do and how each claim is checked. A capability not
listed here is not promised.

## Scope

VeriSight is an analytical application that runs on one computer: a command line,
a Python API and a website. There are no user accounts; each website upload can
be used only with the private token returned to whoever uploaded it. A
[deployment guide](deploy-azure.md) publishes it on Azure Container Apps, deployed
automatically after CI passes. Your original files stay yours and are never changed.

## Supported input

| Limit | Value |
| --- | --- |
| Formats | CSV, TSV, JSON, JSONL, XLS, XLSX |
| Website upload | 20 MB per file, up to 5 files per upload |
| Temporary copies held at once | 100 uploads; when full, new uploads are refused |
| Copies per visitor address | 5; a sixth replaces that visitor's own oldest |
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
| Uploads read at once | 2 |
| Questions per hour, per visitor address | 30 |
| Uploads per hour, per visitor address | 60 |
| Investigation budget | 180 seconds on the website |

The investigation budget covers the analysis steps. Loading and profiling happen
before it starts, so it is not a guarantee of total response time. Every limit is
a setting; the [guide](guide.md#settings) lists them all with their defaults.

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
values. On the website, up to 20 result rows may be disclosed per query; a longer
result keeps its first 20 rows and is marked `truncated`. The command
line and Python API disclose whole query results, within a limit of 60,000
characters per prompt. Multiple queries may disclose more. For small datasets, this can include all records. Use non-sensitive
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
| Skipped | The check could not run, for example after a provider failure or deadline, or it only repeated the first query on a query with another possible route, or one model wrote both | "Number matches SQL only" at best |
| Not requested | The command line ran without `--cross-check` | Trust level is `not_run`, with the reason |

Before writing any query, the model may decline a question: because the data does
not hold what was asked, or because the question depends on a word or comparison it
does not define. A declined question runs no query and gets "Not verified" with no
number. The model's reason is shown only when it states no number.

A second query that repeats the first one's choices counts as a completed check
only for a single-route query, and only when a different model wrote it. A
single-route query reads one table, with no join, grouping, subquery, window,
order or limit. Its values are aggregates of one column, a distinct count and a
`WITHIN GROUP` median included, or one column looked up in the single row its
conditions pick. A number built from two columns together, such as draws
(`home = away`) or total goals (`home + away`), never has one route; its repeat is
recorded as `relates_columns` and explained in plain words. See the
[guide](guide.md#independent-cross-check).

The second query may refuse in the same two cases. A refusal counts as a failed
check, so the answer is "Needs review" and keeps its number with a warning. On the
public benchmark and held-out v4, VeriSight gave no number for all 20 questions
without a valid answer and declined no answerable one. The second query has not
refused in a live run, so that step is still unmeasured.

An exact question answered by fixed rules uses no model, so it has no second query
and is labelled "Computed without AI". When the SQL audit finds that the data does
not hold what was asked, such as a price taken from a column holding no money, the
answer is "Not verified" and the website shows no number. The same applies when the
query had to define a vague word itself, such as "large", or when the question asks
"how much higher" without saying than what.

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
| C1 | Predeclared | Fewer wrong answers shown prominently than plain Gemini | passed | [`results.md`](results.md#held-out-v4-first-live-run-30-questions-5-new-domains) |
| C2 | Predeclared | At most 10 percentage points fewer correct answers delivered than plain Gemini, across all submitted questions | passed | [`results.md`](results.md#held-out-v4-first-live-run-30-questions-5-new-domains) |
| C3 | Predeclared | False warnings on at most 10% of correct answers | failed | [`results.md`](results.md#held-out-v4-first-live-run-30-questions-5-new-domains) |
| C4 | Predeclared | Wrong numbers visible anywhere, including with a warning, are reported separately from prominent ones | passed | [`results.md`](results.md#held-out-v4-first-live-run-30-questions-5-new-domains) |
| R1 | Predeclared | Concurrency, expiry, eviction, restart and crash-recovery tests pass | passed | [`test_web_reliability.py`](../tests/test_web_reliability.py) |
| R2 | Predeclared | A failed mandatory check can never produce "Verified"; evidence already computed stays visible with its incomplete status | passed | [`test_web_reliability.py`](../tests/test_web_reliability.py) |
| R3 | Predeclared | A provider failure never produces a number that was not computed | passed | [`test_web_reliability.py`](../tests/test_web_reliability.py) |
| M1 | Predeclared | Peak process memory under 1 GB across a full local workload: loaded datasets, profiling, two questions at once and second queries | passed | 781 MiB, [`measure_memory.py`](../evaluation/measure_memory.py) |
| W1 | Predeclared | Browser tests pass in Chromium at 1280×800 and 375×812 for upload, asking, reading results, errors and keyboard use, with exact numbers and trust labels | passed | [`app.spec.ts`](../frontend/tests/e2e/app.spec.ts), [`lib.test.ts`](../frontend/tests/unit/lib.test.ts) |

C1 to C4 were first measured at commit `ea707d4`, where C2 and C3 failed. After
fixes, a second comparison on new questions at `a335001` passed C2 at exactly the
10-point limit, and C3 failed again at 33%. A third comparison on new questions at
`5e9f76a` showed no bad number at all, passed C2 at exactly the limit again, and
failed C3 at 35%. A fourth comparison at `2608f9b`, which added the single-route
rule, again showed no bad number prominently and passed C2 at exactly the limit, and
failed C3 at 44%. A fifth comparison at `3cf71e1`, with two audit fixes, showed no bad
number at all, delivered as many correct answers as plain Gemini, and failed C3 at
32%. A sixth comparison at `f1bc439`, with the unit conversion fix, showed 1 bad number
against plain Gemini's 10, delivered every answerable question, and failed C3 at 20%.
A seventh comparison at `69043af`, with three audit fixes, showed 1 bad number
prominently against plain Gemini's 9, delivered 85% of answerable questions against
90%, and failed C3 at 24%, most of it from one false total-row detection. An eighth
comparison at `799ffc9` showed 1 bad number prominently against plain Gemini's 10,
delivered every answerable question, and failed C3 at 20%. A ninth comparison at
`12cf29e`, with the missing-value fixes, showed 1 bad number prominently against
plain Gemini's 8, delivered 80% of answerable questions against 85%, and failed C3
at 12.5%. A tenth comparison at `31f5894` showed no bad number prominently against
plain Gemini's 6, but delivered 80% of answerable questions against 100%, failing C2
for the first time since the first comparison, and failed C3 at 19%. All four missed
answers came from one workbook whose columns are named by academic year.

The first public benchmark run, at `d7b065c`, showed no bad number against plain
Gemini's 6, passed C2 at 95% of answerable questions against 100%, and failed C3 at
26%. Held-out v4, at `a723c13`, on questions nothing was tuned against, showed no
bad number against plain Gemini's 6, passed C2 at exactly the limit (90% against
100%), and failed C3 at 22%. All four of its warnings were repeats of numbers built
from two columns, which the single-route rule refuses on purpose. The status column
shows held-out v4.

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
