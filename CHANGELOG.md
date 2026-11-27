# Changelog

All notable changes to the Scrawl SDKs. The format follows [Keep a Changelog](https://keepachangelog.com/), and
versions follow [Semantic Versioning](https://semver.org/) (before 1.0, a minor version may change the API).
The Python package (`scrawl-sdk`) and the npm package (`@apexaiofficial/scrawl`) are released separately; each
entry says which one it covers.

## Python 0.1.5 and TypeScript 0.1.5 (2026-11-27)

Built against contract digest
`sha256:82f0f7c18a3c44d38ff7c74594fa73af898dfedde04933921f3dec7b6cdfdde5`.

### Added
- Site crawls: `crawl_site` / `crawlSite` crawls a site from a URL into a new dataset version. It stays on the URL's
  host, goes breadth first within `max_pages` and `max_depth`, and reads robots.txt first (a page it disallows is
  never fetched). Each page is a scrape and is charged as one, so `max_pages` is the most a crawl can cost.
  `site_crawl_status` / `siteCrawlStatus` and `wait_for_site_crawl` / `waitForSiteCrawl` follow it, `cancel_job`
  stops it, and `resume_from` continues an ended crawl. CLI: `scrawl site-crawl`, `scrawl site-crawl-status`.
- Curation: `curate_dataset` / `curateDataset` makes a new version of a dataset without a crawl, so nothing is
  fetched and nothing is charged. It can `remove` records, `dedupe` by a field, or `reextract` each page's markdown
  with new content options. `list_curations` / `listCurations` lists a dataset's curations. CLI: `scrawl datasets
  curate`, `scrawl datasets curations`.
- Local fetch: `local_fetch` / `localFetch` fetches a page from your own machine, then has Scrawl render it, so
  Scrawl itself fetches nothing.
  - robots.txt is honoured by default, and redirects and size are bounded.
  - The fetch never uses the client that carries your Scrawl key.
  - `scrape_local` / `scrapeLocal` sends a page you already have.
  - The result says `origin: client_fetched` and `url_verified: false`: the URL, status and type are your claims.
  - CLI: `scrawl local-fetch` (`--file` sends a saved page).
- Content options on `scrape`, `batch_scrape`, `crawl_site` and `reextract`: `only_main_content` /
  `onlyMainContent`, `include_tags` / `includeTags` and `exclude_tags` / `excludeTags`. CLI: `--full-page`,
  `--include-tag`, `--exclude-tag`. They are sent only when set, and the server validates the selectors.
- A stored document's text: `download_asset_text` / `downloadAssetText` returns its Markdown. CLI: `scrawl
  assets-result JOB --text ASSET_ID`.
- TypeScript: the next-step fields (`next_call`, `poll_after_seconds`, `docs_url`, `next_actions`) on job,
  extraction and crawl results, and types for site crawls and curations.

### Changed
- A job's status has one spelling, the lower case (`pending`, `running`, `completed`, `failed`, `cancelled`,
  `orphaned`), on every job, crawl, cancel and dataset-version response; current servers send it that way. The SDK
  also reads the upper case older servers sent and gives it to you in the lower case. This release and the next
  minor release still read the upper case. The TypeScript `JobStatus` type is now the lower-case union, and a status
  filter (`list_jobs`, `list_versions`) accepts either case.

## Python 0.1.4 and TypeScript 0.1.4 (2026-11-16)

Built against contract digest
`sha256:4ee1ab0125fcd4df1396abb77dd5c6a8360680be5aee5b434b0f78a8a9faf7c9`.

### Added
- `Job.warnings`: a list of strings about a run that still succeeded, for example a crawl that made zero requests.
  It is filled when one job is read (`get_job` / `getJob`, and the jobs `wait` returns). It is empty in listings,
  and empty when an older server omits it. `scrawl jobs get` shows it.

### Changed
- `Retry-After` in HTTP-date form (RFC 9110) is now understood, in both clients. It was treated as absent before.
- A retryable 502, 503 or 504 whose `Retry-After` is above 60 seconds is raised at once, with the value on the
  error's `retry_after` / `retryAfter`. Before, the client slept 60 seconds and retried sooner than the server
  asked. Delays up to 60 seconds are still retried, as for 429.
- `retry_after` / `retryAfter` is available on every Scrawl error, not only on rate-limit errors.
- `scrawl map` exits 1, and says why on stderr, when the start page itself was blocked (`outcome:
  target_blocked`). It exited 0 before.

## Python 0.1.3 and TypeScript 0.1.3 (2026-11-16)

Built against contract digest
`sha256:050c240215bf1710f7f9b460dcec1be6b7245667d971ceae0ac9ac518163c1b7`. TypeScript skips 0.1.2 so the
two SDK versions line up again.

### Added
- Proxy-pool management (`list`, `add`, `test`, `enable`, `disable`, `remove`, `mode`) and the free advisory
  proxy-health report in both clients and under `scrawl proxy pool ...` / `scrawl proxy health`. Pool proxy URLs
  are read from an environment variable or stdin, never argv, and the CLI defensively masks proxy passwords.
- Hosted API-key listing and revocation in both clients and under `scrawl keys list|revoke`. Keys are created in
  Telegram with `/api_keys create`; there is deliberately no create method in either SDK.
- Scrape and map outcomes (`ok`, `target_blocked`, `target_error`, `cancelled`, `pipeline_failed`) with block
  reasons and hints, target `retry_after_s` on scrapes, and per-outcome batch counts. Refunds cover only
  Scrawl's own failures (a job that never started, or `pipeline_failed`); target blocks/errors, customer-proxy
  failures and cancellations after work starts remain charged.

### Changed
- A 429 with `Retry-After` above 60 seconds is raised immediately with the full value on `RateLimitError`, instead
  of being capped to 60 seconds and retried. Short delays retain the existing automatic retry behavior.
- `scrawl doctor` follows the account's proxy mode: `direct` still requires the single proxy to have passed its
  test; `pool` and `required_pool` require at least one active pool entry that passed its test.

## Python 0.1.2 (2026-11-15)

### Changed
- `scrawl doctor` says "not ready" and exits 3 until your proxy has passed its test (no proxy, or one that is
  untested or failed), since every job is refused without one. It used to warn and still say "ready". A key without
  the `scrape:write` scope still gets a warning only (the last line then reads "ready, with warnings", as for any
  warning); an error reading the proxy exits 5. If a script runs `scrawl doctor` as a gate, register and test the
  proxy first: `scrawl proxy set && scrawl proxy test`.

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
