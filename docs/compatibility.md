# Compatibility: how the SDKs track the API

The SDKs are clients of one public contract, the ApexAPI that every Scrawl server serves under `/v1`. Three
gates keep the server and the SDKs from drifting apart.

## The contract bundle

[`contracts/`](../contracts) holds the server's public contract, exported by the backend:

| File | What it is |
| --- | --- |
| `apexapi_openapi.json` | The OpenAPI 3.1 document of the HTTP API |
| `apexapi_errors.json` | The error catalogue: every error code with its HTTP status, whether it is retryable, its description and where it appears |
| `apexapi_scopes.json` | The API key scopes and the scope each route and MCP tool needs (for reference) |
| `mcp_tools.json`, `mcp_resources.json` | The server's MCP tools and resources (for reference; the SDKs do not use MCP) |
| `MANIFEST.json` | SHA-256 and size of every file, the backend version it came from, and the **contract digest** |

The contract digest is the SHA-256 of the `sha256sum` listing of the files, sorted by name, so anyone can
recompute it:

```bash
cd contracts && LC_ALL=C sh -c 'sha256sum $(ls | grep -v MANIFEST.json | sort) | sha256sum'
```

Each SDK records the digest it was built against: `scrawl.__contract__` in Python and `CONTRACT_DIGEST` in
TypeScript. Both test suites fail if it differs from `MANIFEST.json`, and if any vendored file differs from
its recorded hash. Files in `contracts/` change only through `tools/sync_contracts.py` (below).

## coverage.json

[`coverage.json`](../coverage.json) is one table for both SDKs and the CLI. For every operation in the OpenAPI
document it says either

- `excluded`, with a reason (operator routes and the legacy job API), or
- the Python method, the TypeScript method and the CLI command, plus `sends`: what a call with every option set
  puts on the wire: query parameters, JSON body fields, the enum values the SDK may send, whether it sends an
  `Idempotency-Key`, and whether it authenticates.

`error_codes` lists every code the SDKs expose as `ErrorCode`: each code of the error catalogue with its HTTP
`status` and `retryable` flag, plus SDK-only codes marked `"source": "sdk"`. [errors.md](errors.md) is generated
from it and the catalogue.

## Gate 1: this repository's tests

[`tools/check_contracts.py`](../tools/check_contracts.py) is the one checker; both test suites use it.

- **Coverage.** A new operation in the contract fails both suites until `coverage.json` covers it (a method in
  each SDK and a CLI command) or excludes it with a reason. An operation that disappeared fails too.
- **Requests.** Each SDK calls every covered method with every option set against a fake transport. The
  checker then verifies the exact path, that every query parameter and body field exists in the contract, that
  enum values are allowed, that required fields are sent, that `Idempotency-Key` goes only where the contract
  accepts it, and that the request is exactly what `coverage.json` declares (Python runs it in-process,
  TypeScript runs the same script).
- **The CLI.** Every covered operation has a CLI command that reaches it, checked against an in-memory fake API
  (`tools/fake_apexapi.py`) that validates each request against the contract and each of its own answers
  against the response schemas.
- **Examples.** Every example in both languages runs to completion against that fake API.
- **Error catalogue.** `contracts/apexapi_errors.json` is read strictly: `schema_version` 1, the `fields` and
  `surfaces` glossaries, and an `errors` list of `{code, http_status, retryable, description, surfaces}`. Any
  other shape (a missing or extra key, a wrong type, a duplicate code, an unknown surface) fails the gate, and
  `sync_contracts.py` refuses such a bundle. Every code in it must be in `coverage.json` with the same status
  and `retryable` flag, and in both SDKs' `ErrorCode` and retry table (each suite also compares the two SDKs).
  Neither SDK ever retries automatically on a code the catalogue marks not retryable.

```bash
python tools/check_contracts.py coverage
python tools/check_contracts.py manifest
```

## Gate 2: the backend's CI

Before the server ships a contract change, its CI runs the compatibility checker of each **released** SDK
version it supports against the new OpenAPI document:

```bash
git clone --depth 1 --branch py-v0.1.0 https://github.com/ApexAiOfficial/scrawl-sdk.git sdk
python sdk/tools/check_contracts.py compat --openapi path/to/new/apexapi_openapi.json
```

It fails (exit 1) when anything that SDK version sends would break: a removed operation, a removed query
parameter or body field, a removed enum value, a new required field the SDK does not send, or a route that no
longer accepts `Idempotency-Key`. New operations are reported as notes only. The checker needs nothing but
Python 3.10+.

## Gate 3: the live suite

`python/tests/live/` and `typescript/test/live/` exercise every covered operation against a real server,
including a refused key (401, `AuthenticationError`) and an unknown id (404, `NotFoundError`). They are
skipped unless `SCRAWL_LIVE_BASE_URL` and `SCRAWL_LIVE_API_KEY` are set, and use deterministic targets from the
environment:

| Variable | Enables |
| --- | --- |
| `SCRAWL_LIVE_TARGET_URL` | everything that fetches: scrape, map, batch, artifacts, cancel |
| `SCRAWL_LIVE_CRAWL_TARGET` | crawl, datasets, versions, diff, query, search, documents, quarantine |
| `SCRAWL_LIVE_AI_PROVIDER`, `SCRAWL_LIVE_AI_API_KEY` (+ optional `_MODEL`, `_BASE_URL`) | AI profiles, JSON scrape, extract, ask, dataset extraction |
| `SCRAWL_LIVE_ASSETS=1` | asset extraction (needs a key with usable egress) |
| `SCRAWL_LIVE_BROWSER=1` | browser rendering |

```bash
SCRAWL_LIVE_BASE_URL=... SCRAWL_LIVE_API_KEY=... SCRAWL_LIVE_TARGET_URL=... python -m pytest python/tests/live
SCRAWL_LIVE_BASE_URL=... SCRAWL_LIVE_API_KEY=... SCRAWL_LIVE_TARGET_URL=... node --test typescript/test/live/live.test.js
```

A unit test checks that the live tests together name every covered operation, so the suite cannot fall
behind the SDK.

## Updating the contracts

When the backend exports a new bundle (a directory with the contract files and its own `MANIFEST.json`):

```bash
python tools/sync_contracts.py path/to/bundle --check     # verify only
python tools/sync_contracts.py path/to/bundle             # verify, replace contracts/, rewrite MANIFEST.json,
                                                          # and update the digest both SDKs record
```

The bundle's manifest lists each file with its SHA-256 (`{"files": {"name": {"sha256": "..."}}}` or
`{"files": {"name": "..."}}`), optionally with `source` (copied as-is) and a `digest` (verified when it uses the
`sha256sum-listing-v1` algorithm). Unlisted files, names with directories, a missing `apexapi_openapi.json` or
any hash mismatch are refused, and nothing is changed. Then:

1. Run both test suites. Cover or exclude every new operation in `coverage.json`; add the method to both
   SDKs, the CLI command, the type declarations, a live test and the `CALLS` tables of the contract tests.
2. Add any new error code to `coverage.json` (with the catalogue's `status` and `retryable`), to both
   `ErrorCode`s and both retry tables (`RETRYABLE` in `python/src/scrawl/_errors.py` and
   `typescript/src/errors.js`) and to the type declarations, then run `python tools/gen_error_docs.py`.
3. Note the new digest in `CHANGELOG.md` and release (see [versioning](versioning.md)).
