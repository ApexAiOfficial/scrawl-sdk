# Changelog

All notable changes to the Scrawl SDKs. The format follows [Keep a Changelog](https://keepachangelog.com/), and
versions follow [Semantic Versioning](https://semver.org/) (before 1.0, a minor version may change the API).
The Python package (`scrawl-sdk`) and the npm package (`@apexaiofficial/scrawl`) are released separately; each
entry says which one it covers.

## Python 0.1.0 and TypeScript 0.1.0 (2026-10-31)

First public version of both SDKs and the CLI, built against contract digest
`sha256:0891fc76af9dc410312deca74c985aa42d7fce8ae593e2d9c4e7f1aec4e82163` (ApexAPI 0.8.0).

### Added
- Python (`scrawl`) and TypeScript clients for every public ApexAPI operation: scrape, map, batch, crawl,
  jobs, artifacts, assets, datasets (versions, diffs, fields, typed queries, extraction, quarantine), search,
  documents, bring-your-own AI (profiles, extract, ask, usage), credits and health. Python has a sync and an
  async client.
- Helpers: `wait_for_scrape`, `wait_for_batch`, `wait_for_assets`, `wait_for_job` (and their camelCase
  TypeScript forms) using server-side waits; `paginate` for every cursor-paged list.
- Safe retries with automatic `Idempotency-Key`s, never on an error code the backend's catalogue marks not
  retryable (`submission_failed`, `settlement_failed`, `internal_error`, `unavailable`...); base-URL rules that
  keep the API key off plain HTTP.
- Browser rendering options (`engine`, `wait_for_ms`) with a downgrade guard (`render_not_supported`), for
  servers that enable it.
- Typed errors in both SDKs, including `BadRequestError` (400) and `ConfigurationError`; `ErrorCode` constants
  for every code in the backend's error catalogue; the request id is read from the `X-Request-ID` header or the
  error body.
- `scrawl` CLI: `scrape`, `result`, `map`, `batch`, `batch-status`, `extract`, `ask`, `crawl`, `job`, `jobs`,
  `cancel`, `artifacts list|download`, `datasets list|get|versions|activate|diff|fields|query|extract|
  quarantine|release`, `search`, `document`, `ai providers list|set|default|test|remove|usage`, `assets`,
  `assets-quote`, `assets-result`, `balance` and `doctor`; exit codes 0-5; downloads verified and never
  overwriting; AI provider keys only from the environment or stdin.
- `ScrawlObject.to_dict()` for plain data (a batch's `items` field shadows `dict.items`, which `json.dumps`
  calls).
- The vendored contract bundle (OpenAPI document, error catalogue, scopes, MCP tools and resources) with
  `MANIFEST.json`, `coverage.json`, `tools/check_contracts.py` (SDK and backend compatibility gate), `tools/sync_contracts.py`, `tools/fake_apexapi.py` and live compatibility
  suites for both SDKs.
