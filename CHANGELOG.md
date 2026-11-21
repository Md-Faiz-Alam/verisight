# Changelog

Notable changes to VeriSight. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/). Every live evaluation, including the
failures, is in [Live results](docs/results.md).

## [0.5.0] - 2026-11-21

### Added

- **Live demo** on Azure Container Apps. After CI passes on `main`, GitHub Actions
  builds the image, publishes it to GitHub Container Registry and deploys it. A
  deploy counts as done only when `/api/health` reports the new build, and is
  rolled back otherwise.
- `/api/health` names the running build (`"build": "sha-<commit>"`).
- **Held-out set v4:** 30 questions over five new domains, with data and expected
  answers in the repository.
- **Public benchmark:** 30 questions anyone can rerun.
- **Recorded replays:** real model responses, replayed through the whole pipeline
  in CI without a key.
- **Clearer notes for two-column numbers:** when a number built from two columns
  can't be checked independently, the answer says so in plain words.
- **Diagnostics:** an optional local folder for answers that failed the claim
  checks, and per-call timing in the comparison runner.
- **Security and maintenance:** CodeQL scanning, Dependabot, `SECURITY.md` and this
  changelog.

### Changed

- Upgraded to pandas 3, DuckDB 2, sqlglot 30 and mypy 2. The frontend is on React
  19, Vite 8, Vitest 5 and TypeScript 7.
- Development uses Python 3.13; Python 3.11 remains supported and tested.
- Modules, folders and views were renamed to match what they do.
- The documentation was rewritten to match the code, with real screenshots and a
  settings reference.

### Removed

- The old `verisight.service` import path. Import `VeriSight` from `verisight`.
- The AWS deployment guide; the project deploys to Azure.

## 0.4.0 and earlier

The website, trust levels, the SQL audit, the blind second query and the first
ten comparisons with plain Gemini. See the [roadmap](docs/roadmap.md) and
[Live results](docs/results.md).

[0.5.0]: https://github.com/Md-Faiz-Alam/verisight/releases/tag/v0.5.0
