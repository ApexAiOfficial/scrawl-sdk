# Changelog

All notable changes to the Scrawl SDKs. The format follows [Keep a Changelog](https://keepachangelog.com/), and
versions follow [Semantic Versioning](https://semver.org/) (before 1.0, a minor version may change the API).
The Python package (`scrawl-sdk`) and the npm package (`@apexaiofficial/scrawl`) are released separately; each
entry says which one it covers.

## Python 0.1.1 and TypeScript 0.1.1 (2026-11-12)

### Added
- Your proxy, which every job needs before anything is fetched: `set_proxy`, `get_proxy`, `test_proxy` and
  `remove_proxy` (TypeScript `setProxy`, `getProxy`, `testProxy`, `removeProxy`), and `scrawl proxy
  show|set|test|remove`. The CLI reads the proxy URL from an environment variable (`SCRAWL_PROXY_URL` by default)
  or stdin, never from argv. `scrawl doctor` reports whether your proxy has passed its test.
- `ErrorCode` gains `ai_daily_budget_exceeded`, `ai_kill_switch_engaged`, `ai_unsupported` and
  `robots_disallowed`, with the catalogue's retry flags.

### Changed
- Contracts re-synced to the backend's current bundle: the four proxy operations, the new error codes, and the
  error catalogue's `mcp_tool_error` block (`tools/check_contracts.py` now validates it; the SDKs do not use MCP).
- A request's JSON body no longer appears in its `repr` (it may carry a proxy URL or an AI provider key).

## Earlier unreleased changes, shipped in 0.1.1

### Changed
- Contracts re-synced to digest `sha256:36eed387f186c86e011df22ad9817507b299aedcbca4e2242b9a78b11f6b7e58`:
  description wording only. Scrawl's descriptions now call the deployment ApexAi runs for one customer a
  "dedicated deployment".
  No operation, schema, scope, error code or SDK behaviour changed; `scrawl.__contract__` and the
  TypeScript `CONTRACT_DIGEST` record the new digest.

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
  use where browser rendering is enabled.
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
