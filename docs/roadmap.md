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
- A [public benchmark](development.md#public-benchmark) and
  [held-out set v4](development.md#held-out-set-v4), 60 questions with data and
  answers in the repository. Across both, VeriSight showed no bad number against
  plain Gemini's 12, and passed targets C1, C2 and C4.
- Recorded model responses replayed through the whole pipeline in CI, private owner
  tokens for website uploads, a per-visitor upload cap, a local folder for answers
  that failed the claim checks, per-call timing in the comparison runner, and a
  plain-words note when a two-column number cannot be checked independently.
- A [live demo](https://verisight.gentleglacier-2ae961c6.uaenorth.azurecontainerapps.io)
  on Azure Container Apps. Each push to `main` that passes CI is built, published to
  `ghcr.io` and deployed, and rolled back if it does not start healthy.

## Next, in order

1. **Fewer warnings on correct answers (target C3).** Held-out v4 warned on 22% of
   correct answers, all repeats of numbers built from two columns. The rule refusing
   them stays, because two models can share a wrong definition of such a number; the
   way forward is a second query that takes another route more often. A second query
   that reaches a wrong number still warns on a correct answer, which is kept on
   purpose: the same disagreement has kept 9 bad numbers from being verified.
2. **Names and words with more than one meaning.** In the seventh comparison "the
   Vips branch" averaged several restaurants of that name and was shown as verified,
   "average score" picked one of three score columns, and "low price category" was
   read as a question about money (fixed since). In the eighth, "how many courses?"
   counted offerings, not modules, and was shown as verified. In the ninth, "the
   highest reported CO2 emissions value" took the World row from a file that mixes
   countries with World and regions, and was shown as verified.
3. **Ask about vague questions.** A question such as "how many count as high
   quality?" should get a clarifying question, not an assumption or an empty result.
4. **Read which row a grouped answer cites,** so that a correct answer read from one
   row of a result grouped by year is not flagged.
5. **Answer more plain questions without AI.** In user testing every question needed
   Gemini.
6. **Outside users.** Let people outside the project try the live demo, and
   measure memory on its container. Accounts, monitoring and storage shared
   between server copies come after.
7. **Questions in other languages.** Eight SQL audit checks read only the SQL and
   the data; the rest read English wording.
8. **Confidential data** needs a paid or private model, because the free tier may
   use what is sent.

## How this work is done

Questions for an evaluation are frozen with their answers before any run, nothing
is tuned on them afterwards, and every attempt is published, including misses and
cases where the simpler approach wins.
