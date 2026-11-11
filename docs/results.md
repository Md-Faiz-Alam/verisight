# Live results

VeriSight answers questions about tabular data from any domain by writing SQL,
running it, and accepting a number only when that number is found in the SQL
result. This page reports every live run of its evaluations, including
failures. No run was repeated to replace a worse one. One comparison restarted
after a crash, as described below.

## At a glance

| | Development | Held-out v1 | Held-out v2 |
| --- | --- | --- | --- |
| Questions | 37 | 15 | 15 |
| Live attempts | 150 | 45 | 45 |
| Correct accepted answers | **85** | 22 | **39** |
| Wrong accepted answers | **0** | **3** | **0** |
| No accepted number | 13 | 5 | 5 |
| Lost to the model provider | 52 | 15 | 1 |
| Domains | 7 | 5 | 5 |

- **Development** evaluations were used while building VeriSight; gaps they
  found were fixed between runs.
- **Held-out** questions use public datasets that played no part in
  development and were committed to the repository before their first run.
  Held-out v1 exposed two bugs and two semantic errors; after the fixes,
  held-out v2 measured the engine on five more unseen datasets.
- Model: `gemini-3.1-flash-lite` (free tier), Python 3.11.9, `google-genai`
  2.27.0. File formats: CSV, JSON, Excel.

"Wrong" means a number VeriSight accepted that differs from an expected answer
computed independently, from the source data, without VeriSight, pandas or
DuckDB. Attempts lost to the provider are listed but are not counted for or
against VeriSight.

## How an answer is produced and checked

```mermaid
flowchart LR
    A[CSV / JSON / Excel] --> B[Load, clean and report<br/>messy values]
    B --> C[Profile schema<br/>and quality]
    C --> D[Gemini plans SQL]
    D --> E[Validate SQL<br/>read-only, limits]
    E --> F[DuckDB runs SQL]
    F --> G[Gemini states the answer<br/>as a claim on a result cell]
    G --> H{Claim equals<br/>the cell?}
    H -- yes --> I[Accepted answer<br/>with its SQL]
    H -- no --> J[Recovery query,<br/>or reported as incomplete]
```

Gemini never supplies a final number on its own. Each number must cite a cell of
an executed query, and the verifier compares the two exactly (see
[Verification and narrative audit](guide.md#verification-and-narrative-audit)).

## Evaluations

Each question has an independently computed answer, a correct control SQL that
must reproduce it, and a plausible trap SQL that must give a different number.
An offline preflight checks all three before any model call. Questions were
frozen before their first live run. VeriSight's code contains nothing specific
to these datasets.

### Bank marketing (CSV, 10 questions)

The UCI bank marketing dataset (41,188 rows): subscription rates, shares among
known values, a minimum group size, and a difference of two rates.

| Run | Revision | Correct | No accepted number | Provider errors |
| --- | --- | --- | --- | --- |
| 1 | `0cd7d6f` | 6 | 4 (2 incomplete, 2 claims rejected) | 0 |
| 2 | `2bab3a7` | 7 | 3 (1 incomplete, 2 claims rejected) | 0 |
| 3 | `8b0ddf3` | **10** | 0 | 0 |

Runs 1 and 2 found gaps in population review (wording such as "as a single
number" was read as part of the question's population) and in claim checking
(a final value missing from the evidence). Both were fixed before run 3, in
`5feaffe` and `8b0ddf3`.

### Multidomain v1 (13 questions, 3 formats)

Public datasets from one pinned seaborn-data commit, each converted to a
different format: NYC taxi trips as JSON (6,433 rows, missing values as null),
Palmer penguins as Excel (344 rows, empty cells) and diamonds as CSV (53,940
rows). Questions cover subset means, null counts, medians with two filters,
differences of means and conditional shares.

| Run | Revision | Correct | No accepted number | Provider errors |
| --- | --- | --- | --- | --- |
| 1 | `97abd60` | 4 | 1 incomplete | 8 |
| 2 | `6b6e411` | 8 | 3 incomplete | 2 |
| 3 | `8594395` | **13** | 0 | 0 |
| 4 | — | — | stopped before the first question | — |
| 5 (×3) | `e80334b` | 10 | 0 | 29 |

Run 2 found that correct conclusions were refused when they mentioned labels
such as `VVS1` or rounded displays; this was fixed before run 3. Run 5 repeated
all questions three times during a provider outage: every attempt not lost to
the provider was correct.

### Evaluation v2: messy values, dates and joins (14 questions)

Three files generated from a fixed seed, identical on every machine:
`orders.csv` with `$1,234.50`, `N/A`, `-`, `10%`, `Shipped` / `shipped ` /
`SHIPPED` and a padded header; `customers.xlsx`, joined to orders, where region
`NA` means North America; and `sensors.json` with ISO date-times and kWh
numbers mixed with `"N/A"` text.

| Run | Revision | Correct | No accepted number | Provider errors |
| --- | --- | --- | --- | --- |
| 1 | `3a06716` | 4 | 0 | 10 |
| 2 | `3a06716` | 11 | 2 (1 incomplete, 1 claim rejected) | 1 |
| 3 | `2d599eb` | **12** | 0 | 2 |

Every one of the 14 questions has been answered correctly at least once. Run 2
found that a correct sum, `333819.64`, was refused because the SQL cell held
binary floating-point noise, `333819.64000000036`; this was fixed before run 3.

### Development totals

| Evaluation | Attempts | Correct | Wrong | No accepted number | Provider errors |
| --- | --- | --- | --- | --- | --- |
| Bank marketing | 30 | 23 | 0 | 7 | 0 |
| Multidomain v1 | 78 | 35 | 0 | 4 | 39 |
| Evaluation v2 | 42 | 27 | 0 | 2 | 13 |
| **All** | **150** | **85** | **0** | **13** | **52** |

### Held-out v1 (15 questions, 5 unseen datasets)

Movies (JSON), natural disaster deaths (CSV), barley yields (Excel), monthly
CO2 readings (CSV) and GLUE benchmark scores (CSV), pinned to exact commits.
Questions and answers were committed in `7c27755` before any run; the two runs
used the website's REST API.

| Run | Revision | Correct | Wrong | No accepted number | Provider errors |
| --- | --- | --- | --- | --- | --- |
| 1 | `7c27755` | 3 | 2 | 2 | 8 |
| 2 | `7c27755` | 4 | 1 | 3 | 7 |
| 3 | `242d4f0` | **15** | 0 | 0 | 0 |

All three wrong answers were accepted because each number did come from the
SQL, but the SQL answered a different question:

- *How many people died in natural disasters in 2010?* The table holds an
  `All natural disasters` row per year next to its parts. `SUM(Deaths) WHERE
  Year = 2010` counted every death twice: 659800 instead of 329900 (both runs).
- *How many earthquake deaths over all years?* Run 1's SQL had no earthquake
  filter and summed every row: 65214300 instead of 2576801. Run 2 was correct.

Four of the five missing answers had correct SQL blocked by two bugs: a
difference answer could not cite two cells, and labels such as `PG-13` were
read as stray numbers. All four problems were fixed in `fd543a9`: difference
operands are returned as separate columns, hyphenated labels are recognised,
total rows are detected and reported (`total_row`), and an answer whose SQL
skips a named value or adds total rows to their parts is marked for review.
Re-checked offline, the new reviews flag all three wrong answers and none of
the seven correct ones. Because the fixes were designed after these failures,
they were measured on a new set.

### Held-out v2 (15 questions, 5 more unseen datasets)

Historical US jobs by sex (JSON), household income by state (Excel), monthly
unemployment by industry (JSON), daily weather in two cities (CSV) and an
antibiotic study (Excel). Four questions ask for a difference; two are
counting-grain traps, because each state's total repeats on ten income-group
rows. Committed in `bb8310f` before any run, at the revision that includes the
fixes above.

| Run | Revision | Correct | Wrong | No accepted number | Provider errors |
| --- | --- | --- | --- | --- | --- |
| 1 | `bb8310f` | **13** | 0 | 2 | 0 |
| 2 | `bb8310f` | **13** | 0 | 1 | 1 |
| 3 | `242d4f0` | **13** | 0 | 2 | 0 |

- All 8 difference attempts and all 4 counting-grain traps were correct.
- *Texas's pct for the 200000+ group* failed in both runs: the SQL filtered
  `region = 'Texas'`, although Texas is in the `name` column. The query
  returned no rows, and VeriSight said so instead of reporting a number.
- One run stopped when the model's next investigation step could not be
  completed; VeriSight reported the investigation as incomplete.
- One correct answer was marked for review because an earlier query in the same
  investigation used `sex = 'Female'` (the data uses `women`); the final query
  and its number were right.
- Provider overload was much lower on this day than during held-out v1, and
  these datasets may simply be easier. Two runs of 15 questions show the fixes
  work on unseen data; they do not establish an accuracy rate.

### Held-out runs with the trust engine

Both held-out sets were run once more at `242d4f0`, through the website's API,
with the SQL audit, trust levels and second query switched on. An answer counted
as correct only if the website showed it as verified.

| Set | Attempts | Correct and verified | Wrong | No accepted number | Provider errors |
| --- | --- | --- | --- | --- | --- |
| Held-out v1 | 15 | 15 | 0 | 0 | 0 |
| Held-out v2 | 15 | 13 | 0 | 2 | 0 |
| **Both** | **30** | **28** | **0** | **2** | **0** |

Neither answer without an accepted number showed a wrong number:

- *Texas's pct for the 200000+ group.* The answer, 0.048, was right, but the
  second query filtered `region = 'Texas'` and returned no rows. The audit named
  the mistake and the answer was marked for review.
- *Construction unemployment, January 2010 minus January 2000.* The SQL was right
  (2194 minus 745 is 1449), but the written conclusion repeated the two years,
  which no claim covers, so VeriSight gave no answer.

A question took a median of 18 seconds and 5 model calls, and at most 44 seconds
and 11 calls.

Two limits apply:

- These questions were no longer unseen. Held-out v1's failures drove fixes, and
  both sets were used to measure the SQL audit. The runs test the whole engine on
  known questions; they do not estimate accuracy on new data.
- The second query was often not independent. In 17 of the 28 verified answers it
  repeated the first query apart from aliases, quoting or the order of filters.
  Such a repeat no longer counts as a second check. With that rule applied to
  these saved answers, 11 stay verified and 17 become "Number matches SQL only",
  with the same correct numbers.

### Held-out v3 (27 questions, 9 more unseen datasets)

Riot deaths, bird strikes, zip codes, flights joined to airports, population,
health spending, planets and US employment, in CSV, JSON and Excel. Questions,
independently calculated answers, control SQL and trap SQL were frozen by hash at
`2cecbbb` before one live run, and no case was repeated. Answers are scored by
the trust level the website showed.

| Trust level shown | Right number | Wrong number |
| --- | --- | --- |
| Verified | 12 | 0 |
| Number matches SQL only | 9 | 0 |
| Needs review | 4 | 1 |
| No number | 1 question | |

25 of 27 numbers were right, with no provider errors. One run of 27 questions
gives a wide range: the true rate could reasonably be about 77% to 98%. The wrong
answer counted the deaths *not* related to the riots, and the second query's
different number marked it for review. The run found two bugs, since fixed, that
caused 3 false warnings and the one missing number. These questions helped find
those bugs, so they no longer measure new code.

### Comparison with plain Gemini (30 questions, 4 unseen datasets)

Red wine quality, forest fires, daily bike rentals and concrete strength, in CSV
and Excel. The project owner wrote 20 answerable, 5 ambiguous and 5 unanswerable
questions, with answers worked out separately, before any setup saw them. The
runner, questions and data were frozen by hash at `ea707d4`, and each setup answered
each question once with `gemini-3.1-flash-lite`. The second query used
`gemini-3.5-flash-lite`.

- **Plain Gemini:** Gemini writes one SQL query and DuckDB runs it. It uses
  VeriSight's cleaned data and SQL prompt, so it is a strong baseline, not raw Gemini.
- **Number checks:** the investigation, with each number matched to a SQL result.
- **Full VeriSight:** the website's path, with the SQL audit and second query.

| Across 30 questions | Plain Gemini | Number checks | Full VeriSight |
| --- | --- | --- | --- |
| Correct, of 20 answerable | 19 | 14 | 15 |
| Wrong number, of 20 answerable | 1 | 1 | 0 |
| No number, of 20 answerable | 0 | 5 | 5 |
| Number given where none exists, of 10 | 9 | 5 | 6 |
| Correctly gave no number, of 10 | 1 | 5 | 4 |
| Bad numbers shown prominently | 10 | 6 | 1 |
| Bad numbers visible anywhere | 10 | 6 | 6 |
| Correct answers carrying a warning | 0 of 19 | 0 of 14 | 4 of 15 |
| Gemini calls | 30 | 150 | 172 |
| Median seconds per question | 3 | 15 | 14 |

Against the targets in the [system specification](system-spec.md), full VeriSight
showed far fewer bad numbers prominently (C1 passed). It delivered 75% of the
answerable questions against plain Gemini's 95%, a gap of 20 points where 10 was
allowed (C2 failed). It put a warning on 27% of its correct answers where 10% was
allowed (C3 failed). A warned number is still visible, so "safer" does not mean the
problem is gone.

- The second query confirmed 12 right answers and doubted 2. It disagreed on 4 of
  the 6 numbers given where none exists, which moved those answers to review.
- Plain Gemini's score was corrected after the run. The scorer read the last numeric
  column, so a correct difference held in the first column was marked wrong. The
  saved SQL was replayed with a rule that reads a difference column by name, and the
  original record is kept.
- The first attempt stopped at question 16 when blank Excel sheets crashed the query
  engine. That bug was fixed and the comparison restarted from question 1 at
  `ea707d4`, so all three setups ran the same code. The 15 attempts before the crash
  are kept and not counted.

These are one run of 30 questions written by the project's own side.

**Fixes made after this run.** Replaying the saved queries showed that VeriSight's SQL
held the right number on 4 of its 5 missed answers. Rounded differences were being
rejected, and that has been fixed. Re-asking those 4 questions gave 4 right numbers,
2 verified and 2 with a warning. Replaying the audit showed that 6 warnings on correct
answers had three general causes, also fixed: years stored as codes, "recorded" read
too broadly, and rounded numbers compared with unrounded ones. The table above is the
result before these fixes. These questions helped find the bugs, so a new score needs
new questions.

### Confirmation runs

Short live runs checked individual changes and are not accuracy scores. Across 10
questions for the second query's different route, 6 for simple questions and 10 for a
second model, every number was right or withheld: 25 right numbers and 1 question with
no number, which a later fix addressed. Other checks re-asked single questions after
a fix.

## Examples from live runs

**Label variants (v2 run 3).** *How many orders were shipped?* The status column
holds `Shipped`, `shipped`, `SHIPPED` and `Shipped `. Gemini first listed the
distinct values, then counted:

```sql
SELECT COUNT(*) AS "shipped_orders_count" FROM "orders"
WHERE LOWER(TRIM("status")) = 'shipped'
```

Answer **415**, correct. The trap, `status = 'Shipped'`, gives 238.

**A two-file join where `NA` is a label (v2 run 3).** *What is the total amount
of orders placed by customers in the NA region?* `Amount` arrived as text such
as `$1,234.50`; VeriSight converted it and reported the conversion as a
data-quality finding. `NA` stayed a region label, while blank regions became
missing.

```sql
SELECT SUM("T1"."Amount") FROM "orders" AS "T1"
JOIN "customers" AS "T2" ON "T1"."customer_id" = "T2"."customer_id"
WHERE "T2"."region" = 'NA'
```

Answer **333819.64**, correct. The trap, treating `NA` as missing, gives 60199.97.

**Recovery instead of a guess (v2 run 3).** *How many days passed between the
first and the last order date?* Gemini's first query returned only the two
dates. No claim could cite a cell holding the number of days, so VeriSight ran
one recovery query:

```sql
SELECT date_diff('day', MIN("order_date"), MAX("order_date"))
  AS "days_between_first_and_last_order" FROM "orders"
```

Answer **546**, correct. The trap, counting days that have orders, gives 379.

**Nulls (multidomain run 3).** *How many taxi trips have no recorded payment
method?* `SELECT COUNT(*) FROM "taxis" WHERE "payment" IS NULL` returned
**44**, correct. The trap, `payment NOT IN ('cash', 'credit card')`, gives 0
because `NOT IN` never matches null.

## What these results do and do not show

- Only the held-out runs at `242d4f0` used the SQL audit, trust levels and second
  query. Every earlier run predates them, and the development evaluations go
  through the command line, which does not run those checks.
- An accepted number is proven to come from an executed SQL result. The
  verifier does not prove that the SQL means what the question asked. The
  evaluations measure that separately, against independent answers and traps.
- Development evaluations used known questions, and gaps they found were fixed
  between runs. Held-out questions were committed before their first run; after
  held-out v1 found failures, a new held-out set measured the fixes.
- Accepted answers can still be wrong when the SQL answers a different question:
  held-out v1 recorded three such answers. Review flags now catch the patterns
  seen there, but not every possible mistake.
- v2 data is generated, not collected; it reproduces common real-world problems
  but not every one. Formats outside the documented cleaning rules stay as text.
- Provider errors depend on the free model tier's load and are excluded from the
  correct and wrong counts, not hidden: they appear in every table.
- 357 scored attempts across 124 questions is evidence, not a reliability guarantee.

## Reproduce

```powershell
python evaluation\bank\run_bank_eval.py --dataset datasets\bank_marketing\bank-additional-full.csv --preflight-only
python evaluation\multidomain\run_multidomain_eval.py --prepare --data-dir datasets\multidomain --preflight-only
python evaluation\v2\run_v2_eval.py --prepare --data-dir datasets\v2 --preflight-only
python evaluation\heldout\run_heldout_eval.py --prepare --data-dir <data folder> --preflight-only
python evaluation\heldout_v2\run_heldout_eval.py --prepare --data-dir <data folder> --preflight-only
```

Remove `--preflight-only` and add a new `--out` folder outside the repository to
run live. Each run writes a manifest (revision, packages, settings, questions,
expected and trap values), one JSON report per attempt and a summary.

Correct and wrong count only answers VeriSight accepted. A matching SQL cell
inside a rejected answer is scored `not_accepted`, never correct. To rescore a
saved run with the current scorer, without model calls and without changing the
run folder:

```powershell
python evaluation\rescore.py evaluation\v2\run_v2_eval.py <run folder> --out <new folder>
```
