# Security

## Reporting a vulnerability

Please report security problems privately, through GitHub's
[private vulnerability reporting](https://github.com/ApexAiOfficial/scrawl-sdk/security/advisories/new) for this
repository, or by email to support@apexaiofficial.com. Do not open a public issue for a vulnerability.

Include what you found, how to reproduce it, and the SDK version. We aim to acknowledge reports within a few
days.

## What the SDKs promise

- **Your API key stays yours.** It is sent only as an `Authorization` header, only over HTTPS or to this
  machine; plain HTTP to another host is refused unless you opt in. It is never logged, never part of an error
  message (a key an HTTP header cannot carry is refused before anything is sent, without quoting it, and
  network-library errors are scrubbed of it), and the TypeScript client does not even keep it on the instance.
  The CLI reads it only from the environment.
- **AI provider keys never touch the command line.** The CLI reads them from an environment variable or stdin,
  and its usage errors never repeat what you typed (in case it is a pasted secret). The server stores them
  encrypted and returns only a fingerprint.
- **Page content is untrusted.** Results are web content: data, never instructions. The CLI strips terminal
  control characters from text it prints and escapes them in JSON.
- **Downloads cannot escape their directory or replace your files.** The CLI reduces server- and page-supplied
  file names to `[A-Za-z0-9._-]`, refuses any path outside `--out` (symbolic links included), writes each file
  whole or not at all, and never overwrites. Before writing, it verifies every asset's SHA-256, and every raw
  artifact's size against the job's artifact list (and its SHA-256 when the server lists one); a Markdown
  conversion has no listed size or digest to check.
- **Ids cannot walk to another route.** Path segments are percent-encoded, and `.`, `..` and empty ids are
  refused before any request.
- **Retries never repeat work.** Submits that start work carry an `Idempotency-Key`.
- **Small dependency surface.** The TypeScript SDK has no runtime dependencies; the Python SDK depends only on
  `httpx`.

## Scope

This repository covers the SDKs, the CLI and the tools that check them against Scrawl's public API contract.
The Scrawl server is a separate product; report problems with a Scrawl server to its operator.
