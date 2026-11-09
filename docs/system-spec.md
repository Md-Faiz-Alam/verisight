# VeriSight system specification

This page defines what VeriSight is built to do and how each claim is checked.
A capability not listed here is not promised.

## Scope

VeriSight runs on one computer for one person at a time. There is no public
deployment and no user accounts. Files stay on that computer, apart from what is
sent to Gemini to answer an AI question.

## Supported input

| Limit | Value |
| --- | --- |
| Formats | CSV, TSV, JSON, JSONL, XLS, XLSX |
| Website upload | 20 MB, up to 5 files |
| Upload retention | Deleted when removed, or after 60 minutes |
| Datasets held at once | 100 |

## Supported questions

| Supported | Not supported |
| --- | --- |
| Counts and counts of different values | Forecasts and predictions |
| Totals, averages, medians, highest and lowest | Opinions and recommendations |
| Filters on values, dates and ranges | Answers from outside the uploaded data |
| Joins between uploaded files | Questions that need more than one number in one claim |
| Differences and percentages | |

A question VeriSight cannot support with evidence gets no number. It says so
instead of guessing.

## Usage limits

| Limit | Value |
| --- | --- |
| Questions running at once | 2 |
| Questions per hour | 30 |
| Time limit per question | 180 seconds |
| Result rows shown to the model per query | 20 |
| Main model | `gemini-3.1-flash-lite` |
| Second-query model | `gemini-3.5-flash-lite` |
| Free daily limit | 500 calls per model, about 125 questions |

## Data rule

Use non-sensitive data only. On the Gemini free tier, Google can use prompts and
responses to improve its products, and reviewers may read them. VeriSight sends
column names and types, row counts, quality findings, summary figures, some column
values and up to 20 result rows per query. It never sends the whole file.

## Trust checks

| Entry point | Number matched to SQL | SQL audit and second query |
| --- | --- | --- |
| Website and its API | Always | Always |
| Command line | Always | With `--cross-check` |
| Python API | Always | With `cross_check=True` |

When the audit and second query do not run, the command line reports the trust
level as `not_run` and gives the reason.

## Pass marks

Each target was set before its result was known.

| Area | Target |
| --- | --- |
| Damaged files | At least 42 of the 43 damage types repaired, and no value read wrongly |
| SQL audit | No warning on correct SQL, and at least 75% of deliberately wrong SQL caught |
| Comparison with plain Gemini | Fewer wrong answers shown than plain Gemini, at most 10 percentage points fewer correct answers delivered, and false warnings on at most 10% of correct answers |
| Reliability | Every concurrency, expiry, restart and provider-failure test passes, and a provider failure never produces a number |
| Memory | Under 1 GB when handling a 20 MB upload, measured on the local computer |
| Website | Browser tests pass for upload, asking, results, errors, keyboard use and mobile layout, with exact numbers and trust labels |

## What these checks do not prove

A matched number shows that the number came from an executed query, not that the
query means what the question asked. A second query can share a mistake with the
first. All testing so far was done by the project's own side, and no outside user
has tried the system.
