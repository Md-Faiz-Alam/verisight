# VeriSight roadmap

## Objective

A local analyst for tabular files that shows how each answer was reached and how far
it can be trusted, and gives no number rather than a misleading one. The
[system specification](system-spec.md) defines the supported scope and the targets.

## Done

- Ingestion and reported cleaning of messy files, profiling, quality findings and
  automatic dashboards, all without AI.
- Guarded DuckDB SQL, Gemini investigations, numbers matched to SQL cells, the SQL
  audit, a second query by another route, and trust levels on the website and the
  command line.
- Offline test suites for damaged files, audit mistakes and plain questions;
  reliability tests for concurrency, expiry, crashes and provider failures; a
  memory measurement; and browser tests at desktop and phone sizes.
- A frozen comparison with Gemini writing SQL alone, and a round of testing as
  different kinds of user. Both are in [Live results](results.md).

## Next, in order

1. **Fewer numbers where none should exist, and fewer false warnings.** In the
   second comparison VeriSight gave a number on 6 of 10 questions with no valid
   answer, and warned on 6 of 18 correct answers. The model can now decline a
   question the data cannot answer, or one that needs a definition, before any
   query is written, and the second query can refuse too. Neither has been
   measured on new questions, so how often they decline wrongly is unknown.
2. **Ask about vague questions.** A question such as "how many count as high
   quality?" should get a clarifying question, not an assumption or an empty result.
3. **Read which row a grouped answer cites,** so that a correct answer read from one
   row of a result grouped by year is not flagged.
4. **Answer more plain questions without AI.** In user testing every question needed
   Gemini.
5. **Outside users.** No one outside the project has used VeriSight yet.
6. **Deployment.** Measure memory on the target container, then add accounts,
   monitoring and storage shared between server copies.
7. **Confidential data** needs a paid or private model, because the free tier may
   use what is sent.

## How this work is done

Questions for an evaluation are frozen with their answers before any run, nothing
is tuned on them afterwards, and every attempt is published, including misses and
cases where the simpler approach wins.
