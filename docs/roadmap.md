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
- Declining questions the data cannot answer or that need a definition, before any
  query. In the third comparison no answer showed a bad number, and no answerable
  question was declined.

## Next, in order

1. **Fewer false warnings.** In the eighth comparison VeriSight warned on 4 of 20
   correct answers (20%). Three came from missing-value readings, fixed since; on the
   saved answers 1 warning of 20 remains. The fourth, a repeated distinct count, has
   now come up twice. A ninth comparison must confirm C3. A second query that reaches
   a wrong number still warns on a correct answer, which is kept on purpose: the same
   disagreement has kept 8 bad numbers from being verified.
2. **Names and words with more than one meaning.** In the seventh comparison "the
   Vips branch" averaged several restaurants of that name and was shown as verified,
   "average score" picked one of three score columns, and "low price category" was
   read as a question about money (fixed since). In the eighth, "how many courses?"
   counted offerings, not modules, and was shown as verified.
3. **Ask about vague questions.** A question such as "how many count as high
   quality?" should get a clarifying question, not an assumption or an empty result.
4. **Read which row a grouped answer cites,** so that a correct answer read from one
   row of a result grouped by year is not flagged.
5. **Answer more plain questions without AI.** In user testing every question needed
   Gemini.
6. **Outside users.** No one outside the project has used VeriSight yet.
7. **Deployment.** Measure memory on the target container, then add accounts,
   monitoring and storage shared between server copies.
8. **Confidential data** needs a paid or private model, because the free tier may
   use what is sent.

## How this work is done

Questions for an evaluation are frozen with their answers before any run, nothing
is tuned on them afterwards, and every attempt is published, including misses and
cases where the simpler approach wins.
