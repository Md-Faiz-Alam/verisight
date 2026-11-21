# Security policy

## Supported versions

Only the latest commit on `main` is supported. It is what the
[live demo](https://verisight.gentleglacier-2ae961c6.uaenorth.azurecontainerapps.io)
runs: each push to `main` that passes CI is deployed automatically.

## Reporting a vulnerability

Please report privately, not in a public issue. Open the repository's
**Security** tab and choose **Report a vulnerability**. Include what you found,
how to reproduce it, and what an attacker could do with it.

You can expect an acknowledgement within a week. Please allow time for a fix to
be deployed before you disclose the issue publicly.

## In scope

- **SQL that escapes its limits:** model-written SQL that reads files, the network
  or settings, writes anything, or runs more than one statement.
- **Access to someone else's upload:** reading, querying or deleting an upload
  without the private token returned to whoever uploaded it.
- **Getting around the website's limits:** rate limits, upload size and count
  caps, or the time budget for a question.
- **Leaking a Gemini key:** a visitor's key, or the server's if one is
  configured, appearing in logs, responses or stored files.
- **Injection into the web page:** script injection or similar attacks.

## Out of scope

- **Wrong answers to questions.** VeriSight's checks reduce wrong numbers, but
  they do not prove an answer is right; the [README](README.md#limits) explains
  why. Report a wrong answer as an ordinary issue.
- **What Gemini does with the data sent to it.** That is governed by Google's
  terms. The demo is for non-sensitive data only.
- **Denial of service by sheer volume** against the free demo.

## How the demo is protected

- **SQL safety:** model-written SQL must be one read-only `SELECT` over the
  loaded tables, with time, memory and result-size limits.
- **Private uploads:** each upload is reachable only with its owner's token, and
  is deleted after an hour.
- **Rate limits:** questions, uploads and dashboard requests are limited per
  visitor address, and request bodies are size-capped before they are read.
- **Gemini keys:** a visitor's key is used for one question and never stored or
  logged.
- **Container:** the app runs as a non-root user, and is rolled back
  automatically if a new version fails its health check.
- **Dependencies and code:** Dependabot keeps them current, and CodeQL scans the
  code on every push.
