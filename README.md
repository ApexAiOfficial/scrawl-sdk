# Scrawl SDKs and CLI

[![CI](https://github.com/ApexAiOfficial/scrawl-sdk/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ApexAiOfficial/scrawl-sdk/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

The official Python and TypeScript client libraries, and the `scrawl` command-line tool, for the versioned HTTP
API (ApexAPI) of [Scrawl](https://apexaiofficial.com/scrawl), ApexAi's web-data product.

With them you can scrape a URL to clean Markdown or to JSON shaped by your schema, map a site, run batches and
crawls into versioned datasets, query and search those datasets, extract data and get cited answers with your own
AI provider, and, where the feature is enabled, extract a page's files and media.

## Status

| Area | Today |
| --- | --- |
| Source | Public in this repository, under the [Apache License 2.0](LICENSE) |
| Releases | Python SDK 0.1.0 (tag `py-v0.1.0`) and TypeScript SDK 0.1.0 (tag `ts-v0.1.0`), published as [GitHub Releases](https://github.com/ApexAiOfficial/scrawl-sdk/releases) with installable files |
| Package registries | **Not on PyPI or npm.** Install from a GitHub Release, a tag or a clone (see [Installation](#installation)) |
| Maturity | Pre-1.0 (alpha). Until 1.0, a minor version may change the SDK API (see [Versioning](#versioning-and-compatibility)) |
| What you need | Access to Scrawl: the endpoint and the API key ApexAi provides for your account. The SDKs cannot create keys and have no built-in remote endpoint |
| Scrawl itself | A proprietary service that ApexAi operates. Its public hosted access is not open yet: there is no public endpoint or sign-up. Scrawl is not part of this repository and is not distributed |
| More | [ApexSDK](https://apexaiofficial.com/apexsdk), the catalog of ApexAi's developer kits, and the [Scrawl product page](https://apexaiofficial.com/scrawl) |

Before you have access, you can still install the SDKs and run them against the repository's
[local fake API](#no-access-yet-use-the-local-fake), which answers with canned, contract-shaped data.

## Contents

- [What is in this repository](#what-is-in-this-repository)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Quickstart](#quickstart)
- [Usage](#usage): [results](#results), [waiting](#waiting-for-jobs), [pagination](#pagination),
  [idempotency and retries](#idempotency-and-retries), [datasets](#datasets),
  [your own AI provider](#extraction-and-answers-with-your-own-ai-provider), [files and media](#files-and-media)
- [Errors](#errors)
- [Command-line tool](#command-line-tool)
- [Troubleshooting](#troubleshooting)
- [Security and privacy](#security-and-privacy)
- [Versioning and compatibility](#versioning-and-compatibility)
- [Documentation](#documentation), [Support](#support), [Contributing](#contributing), [License](#license)

## What is in this repository

| Path | What it is |
| --- | --- |
| [`python/`](python) | The Python SDK (distribution `scrawl-sdk`, import `scrawl`) with sync and async clients, and the `scrawl` CLI |
| [`typescript/`](typescript) | The TypeScript / JavaScript SDK (package `@apexaiofficial/scrawl`) |
| [`contracts/`](contracts) | ApexAPI's public contract as exported by Scrawl: the OpenAPI document, error catalogue, scopes and `MANIFEST.json`, plus Scrawl's MCP tools and resources for reference (the SDKs do not use MCP) |
| [`coverage.json`](coverage.json) | Every API operation mapped to its Python method, TypeScript method and CLI command, or the reason it is left out |
| [`tools/`](tools) | The contract and compatibility checker, the contract sync tool, the error-table generator and a local fake API for tests and examples |
| [`docs/`](docs) | Guides: quickstart, Python, TypeScript, CLI, authentication, errors, compatibility, versioning |

Both SDKs and the CLI cover the same 37 of the API's 49 operations. The 12 left out are 2 administrative routes
(key issuance and metrics, which need an admin token that only ApexAi holds) and 10 legacy routes (the older job
API, its command catalogue and engine introspection) that the typed methods replace;
[`coverage.json`](coverage.json) gives the reason for each.

## Requirements

| To use | You need |
| --- | --- |
| Python SDK and `scrawl` CLI | Python 3.10 or later (CI tests 3.10 to 3.13). One runtime dependency, `httpx` (`>=0.27,<1`), installed by pip |
| TypeScript / JavaScript SDK | Node.js 20 or later (CI tests 20 and 22). ESM only, no runtime dependencies, type declarations included |
| Either, against real data | Access to Scrawl: the HTTPS endpoint and the API key ApexAi provides for your account (public hosted access is not open yet) |
| JSON extraction, `extract`, `ask` | A key with the `ai:use` scope and an account with an AI provider Scrawl supports |
| Files and media | File extraction enabled by ApexAi, and a usable proxy for your account |

The CLI ships only with the Python package. The TypeScript SDK relies on standard web APIs such as the global
`fetch`, but CI tests it only on Node.js.

## Installation

Neither package is on PyPI or npm. Install a released version from its GitHub Release, or build from a tag or a
clone. Use a virtual environment for Python (on Windows, activate it with `.venv\Scripts\activate`).

### Python SDK and the `scrawl` command

From the GitHub Release (the built wheel):

```bash
python -m venv .venv && . .venv/bin/activate
python -m pip install https://github.com/ApexAiOfficial/scrawl-sdk/releases/download/py-v0.1.0/scrawl_sdk-0.1.0-py3-none-any.whl
scrawl --version
```

From the release tag, built from source:

```bash
python -m pip install "git+https://github.com/ApexAiOfficial/scrawl-sdk.git@py-v0.1.0#subdirectory=python"
```

From a clone (the `main` branch, or `git checkout py-v0.1.0` for the release):

```bash
git clone https://github.com/ApexAiOfficial/scrawl-sdk.git
python -m pip install ./scrawl-sdk/python
```

pip downloads `httpx` from PyPI as usual, and, when it builds from source, the `setuptools` build backend.

### TypeScript / JavaScript SDK

In your project's directory, from the GitHub Release (the packed tarball):

```bash
npm install https://github.com/ApexAiOfficial/scrawl-sdk/releases/download/ts-v0.1.0/apexaiofficial-scrawl-0.1.0.tgz
```

Or from a clone (npm links the folder as a `file:` dependency, so keep the clone where it is):

```bash
npm install /path/to/scrawl-sdk/typescript
```

Either way the package is installed as `@apexaiofficial/scrawl`, the name you import.

### Checking a release file

Each release lists a SHA-256 digest for every file. To compare a file you downloaded (on macOS, use
`shasum -a 256`):

```bash
gh release view py-v0.1.0 --repo ApexAiOfficial/scrawl-sdk --json assets --jq '.assets[] | "\(.digest)  \(.name)"'
sha256sum scrawl_sdk-0.1.0-py3-none-any.whl
```

### Package registries (not yet)

| Registry | Command, once published |
| --- | --- |
| PyPI | `pip install scrawl-sdk` |
| npm | `npm install @apexaiofficial/scrawl` |

Neither name is on a registry today. Until this README lists them as published, treat any registry package with
either name as unofficial. The unscoped name `scrawl` on PyPI and on npm belongs to unrelated packages: never
install it in place of these SDKs.

## Configuration

Both SDKs and the CLI read the same environment variables:

| Variable | Used by | Meaning |
| --- | --- | --- |
| `SCRAWL_API_KEY` | SDKs, CLI | Your Scrawl API key, sent as `Authorization: Bearer <key>` |
| `SCRAWL_BASE_URL` | SDKs, CLI | The Scrawl endpoint ApexAi provides for your account, for example `https://scrawl.example`. Default: `http://127.0.0.1:8088`, a loopback address (there is no built-in remote default) |
| `SCRAWL_ALLOW_INSECURE_HTTP` | SDKs, CLI | `1` allows plain HTTP to a host that is not this machine (trusted networks only) |
| `SCRAWL_AI_API_KEY` | CLI | Default source of your AI provider key for `scrawl ai providers set` |

Or pass options to the client:

| Option | Python (`Scrawl`, `AsyncScrawl`) | TypeScript (`new Scrawl({...})`) | Default |
| --- | --- | --- | --- |
| API key | `api_key` | `apiKey` | `SCRAWL_API_KEY` |
| Endpoint | `base_url` | `baseUrl` | `SCRAWL_BASE_URL`, else `http://127.0.0.1:8088` |
| Per-request timeout | `timeout` (seconds) | `timeoutMs` | 90 seconds |
| Automatic retries | `max_retries` | `maxRetries` | 2 |
| Your own HTTP client | `http_client` (`httpx.Client` or `httpx.AsyncClient`) | `fetch` | built in |
| Plain HTTP to another host | `allow_insecure_http` | `allowInsecureHttp` | off |

The key never crosses a network in clear text. `https://` base URLs are always accepted, with the certificate
verified. `http://` is accepted only for this machine (`localhost`, `*.localhost`, `127.0.0.0/8`, `::1`); any
other plain-HTTP URL makes the client constructor raise `ConfigurationError` unless you opt in. The key itself is
checked lazily: a client without one can call `health()`, and any other call raises `ConfigurationError` before
anything is sent.

**Scopes.** Keys are issued with `scrape:write`, `jobs:read`, `artifacts:read` and `credits:read` unless ApexAi
issues one with other scopes. The AI scopes are never on by default: `ai:configure` manages your AI provider
profiles, and `ai:use` runs JSON scrapes, `extract`, `ask` and dataset extraction. A missing scope is a 403
`PermissionDeniedError` with code `forbidden`. The full table is in
[docs/authentication.md](docs/authentication.md#scopes).

Check a setup before writing code. `scrawl doctor` checks the base URL, TLS, reachability (`GET /v1/health`) and
the key, and never prints the key:

```bash
export SCRAWL_BASE_URL=https://scrawl.example    # the endpoint ApexAi provides for your account
export SCRAWL_API_KEY=...                        # the API key ApexAi issues for your account
scrawl doctor
```

## Quickstart

The examples below read `SCRAWL_API_KEY` and `SCRAWL_BASE_URL` from the environment.

### No access yet? Use the local fake

[`tools/fake_apexapi.py`](tools/fake_apexapi.py) serves canned, contract-shaped answers on `127.0.0.1` and checks
every request against the contract. It fetches nothing, stores nothing and accepts one key, `sk_test_fake`. Run it
from a clone, with nothing but Python 3.10 or later:

```bash
python scrawl-sdk/tools/fake_apexapi.py --port 8099 &     # prints "listening http://127.0.0.1:8099"
export SCRAWL_BASE_URL=http://127.0.0.1:8099
export SCRAWL_API_KEY=sk_test_fake
scrawl doctor
```

```text
ok    base_url   http://127.0.0.1:8099 (SCRAWL_BASE_URL)
ok    tls        plain HTTP to this machine (no TLS needed)
ok    reachable  GET /v1/health answered 'ok' in 2 ms
ok    auth       the API key is accepted (GET /v1/jobs)
ready
```

The code examples in the Quickstart, Usage, Errors and Command-line sections all run against it. Its scrapes
return the same synthetic page whatever the URL.

### Python

```python
from scrawl import Scrawl

with Scrawl() as client:                          # or Scrawl(api_key=..., base_url=...)
    page = client.scrape("https://example.com")   # the server waits up to 30 s for the result
    if page.status == "pending":                  # a slow page: the job keeps running
        page = client.wait_for_scrape(page.job_id)
    if page.status == "completed":
        print(page.title)
        print(page.markdown)
    else:
        print("failed:", page.get("error_code"), page.get("error"))
```

### Python, async

`AsyncScrawl` has the same methods and helpers, awaited; `paginate` is an async iterator.

```python
import asyncio

from scrawl import AsyncScrawl


async def main() -> None:
    async with AsyncScrawl() as client:
        page = await client.scrape("https://example.com")
        print(page.status, page.get("title"))
        async for dataset in client.paginate(client.list_datasets):
            print(dataset.dataset_id, dataset.active_version_id)


asyncio.run(main())
```

### TypeScript and JavaScript

Save as `quickstart.mjs` and run it with `node quickstart.mjs` (Node.js 20 or later):

```js
import { Scrawl } from "@apexaiofficial/scrawl";

const client = new Scrawl();                      // or new Scrawl({ apiKey, baseUrl })
let page = await client.scrape("https://example.com");
if (page.status === "pending") page = await client.waitForScrape(page.job_id);
if (page.status === "completed") console.log(page.title, page.markdown);
else console.error("failed:", page.error_code, page.error);
```

The package ships its type declarations, so the same code type-checks as TypeScript (`ScrapeResult`, `ErrorCode`
and the other types are exported). Responses are the API's JSON as-is, with snake_case fields (`page.job_id`), and
options are camelCase (`{ waitSeconds: 10 }`). The package is ESM only: use `import`, or `await import()` from
CommonJS.

### Command line

```bash
scrawl scrape https://example.com > page.md       # the page as Markdown, saved to page.md
scrawl map https://example.com --limit 50         # one URL per line
scrawl --json scrape https://example.com          # the full JSON response
```

## Usage

The snippets in this section continue from the quickstart's `client`. Each SDK has nine runnable examples:
[`python/examples/`](python/examples) and [`typescript/examples/`](typescript/examples).

| Area | Python methods (TypeScript: the same names in camelCase) | CLI |
| --- | --- | --- |
| Scrape | `scrape`, `scrape_result`, `map`, `batch_scrape` (up to 20 URLs), `batch_status` | `scrape`, `result`, `map`, `batch`, `batch-status` |
| Crawls and jobs | `crawl`, `get_job`, `list_jobs`, `cancel_job`, `list_artifacts`, `download_artifact` | `crawl`, `job`, `jobs`, `cancel`, `artifacts` |
| Datasets | `list_datasets`, `get_dataset`, `list_versions`, `activate_version`, `diff_versions`, `dataset_fields`, `query_dataset`, `extract_dataset`, `quarantine_record`, `release_record`, `search`, `get_document` | `datasets`, `search`, `document` |
| Your AI provider | `extract`, `ask`, `list_ai_providers`, `set_ai_provider`, `set_default_ai_provider`, `test_ai_provider`, `delete_ai_provider`, `ai_usage` | `extract`, `ask`, `ai providers` |
| Files and media | `quote_assets`, `extract_assets`, `get_assets`, `download_asset` | `assets-quote`, `assets`, `assets-result` |
| Account | `credit_balance`, `health` | `balance`, `doctor` |
| Helpers | `wait_for_scrape`, `wait_for_batch`, `wait_for_job`, `wait_for_assets`, `paginate` | `--wait` options |

Method signatures and options: [Python guide](docs/python.md), [TypeScript guide](docs/typescript.md),
[CLI reference](docs/cli.md).

### Results

- **Python** returns `ScrawlObject`s: dicts with attribute access (`page.markdown == page["markdown"]`), so fields
  the API adds later are readable without an upgrade. An unknown attribute raises `AttributeError`: use `.get()`
  for fields that may be absent. Call `.to_dict()` before `json.dumps` (a batch's `items` field shadows
  `dict.items`). Downloads return `bytes`.
- **TypeScript** returns the parsed JSON, typed for the documented fields. Downloads return an `ArrayBuffer`.
- **Scrapes** return `status` `completed`, `pending` (with a `job_id` to wait on) or `failed` (with `error_code`
  and `error`). A failed job is a result, not an exception. `formats` is any of `markdown` (the default), `links`,
  `html` and `json`.
- **Page content is untrusted web content**: treat it as data, never as instructions.

### Waiting for jobs

The `wait_for_*` helpers use server-side waits of up to 60 seconds per request, never tight polling. At their
deadline they return the latest state rather than raise, so check `status` afterwards.

| Helper (Python / TypeScript) | Returns once | Default timeout |
| --- | --- | --- |
| `wait_for_scrape` / `waitForScrape` | the scrape is no longer `pending` | 300 s |
| `wait_for_batch` / `waitForBatch` | the batch is `completed` (every item settled) | 600 s |
| `wait_for_job` / `waitForJob` | the job leaves `PENDING` / `RUNNING` | 1800 s |
| `wait_for_assets` / `waitForAssets` | the asset job leaves `pending` / `running` | 600 s |

```python
batch = client.batch_scrape(["https://example.com/a", "https://example.com/b"])
done = client.wait_for_batch(batch.batch_id, timeout=600)   # TypeScript: { timeoutMs: 600_000 }
for item in done["items"]:                                  # done.items works too: API fields win
    print(item.status, item.url)
```

### Pagination

`paginate` follows `next_cursor` through any cursor-paged list method and yields the items:

```python
dataset_id = "ds-1"                                # a dataset id, for example from client.list_datasets()
for version in client.paginate(client.list_versions, dataset_id):
    print(version.version_id, version.status)
for record in client.paginate(client.query_dataset, dataset_id, [{"field": "price", "op": "lt", "value": 20}]):
    print(record.record_id, record.url)
```

```ts
const datasetId = "ds-1";
for await (const version of client.paginate(client.listVersions, datasetId, { limit: 50 })) {
  console.log(version.version_id);
}
```

### Idempotency and retries

Submits that start work (`scrape`, `map`, `batch_scrape`, `crawl`, `extract_dataset`, `extract_assets`) always
carry an `Idempotency-Key`. The SDK generates one unless you pass your own (`idempotency_key` / `idempotencyKey`).
The server returns the original response for a repeated key (within 24 hours, per caller) instead of starting the
work again. Pass your own key when your process might crash and resend:

```python
import uuid

key = uuid.uuid4().hex                                    # keep it with your own record of the request
launch = client.crawl("my-target", max_items=500, idempotency_key=key)
again = client.crawl("my-target", max_items=500, idempotency_key=key)
assert again.job_id == launch.job_id                      # the same job: nothing started twice
```

The SDKs retry automatically (`max_retries` / `maxRetries`, default 2), with exponential backoff that honours
`Retry-After`:

- **GETs** retry on 429, 502, 503, 504 and network errors.
- **Keyed submits** retry on 429, network errors, and a 502, 503 or 504 from a proxy. A 5xx in Scrawl's own error
  format is final. If a retry finds the first attempt still running (409), the SDK waits for its stored response.
- **Other POSTs** and other 4xx are never retried.
- **A code the error catalogue marks not retryable is never retried.** That includes `submission_failed` and
  `internal_error`, after which the first request may already have started work: list your jobs before you send it
  again with a new key.

### Datasets

A crawl runs a named crawl target that the server allows and publishes a new version of a dataset. You can then
read its fields, query it with typed filters, compare versions, roll back, and search.

```python
launch = client.crawl("my-target", max_items=500)          # a named crawl target -> a new dataset version
job = client.wait_for_job(launch.job_id)                   # COMPLETED, FAILED, CANCELLED or ORPHANED
if job.status == "COMPLETED":
    dataset_id = launch.dataset_id
    fields = client.dataset_fields(dataset_id).fields      # paths, types, presence, examples
    cheap = client.query_dataset(dataset_id, [{"field": "price", "op": "lt", "value": 20}])
    versions = [v.version_id for v in client.paginate(client.list_versions, dataset_id)]   # newest first
    if len(versions) > 1:
        changes = client.diff_versions(dataset_id, versions[1], versions[0])   # added, removed, changed
        client.activate_version(dataset_id, versions[1])                      # roll back (or forward)
    hits = client.search("desk lamp", limit=10)            # across your active dataset versions
```

Filter operators are `eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `contains`, `in` and `exists`; every filter needs a
`value` (`exists` takes a boolean). `quarantine_record` hides a record from retrieval and `release_record` undoes
it.

### Extraction and answers with your own AI provider

Structured extraction and answers run on your own AI provider account. Store a provider key once per profile; the
server keeps it encrypted and only ever returns a fingerprint. The CLI reads the key from an environment variable
or stdin, never from the command line:

```bash
export SCRAWL_AI_API_KEY=...                       # your AI provider's key
scrawl ai providers set main --provider openai     # --provider: one the server supports
scrawl ai providers test main
```

(In code: `set_ai_provider("main", provider=..., api_key=...)` / `setAiProvider`.) Then:

```python
schema = {"type": "object", "properties": {"name": {"type": "string"}, "price": {"type": "number"}}}
product = client.scrape("https://example.com/item", formats=["json"], schema=schema,
                        instruction="The product name and price")
print(product.json, product.ai)                    # the data, plus provider, model and tokens used

data = client.extract(product.job_id, schema=schema).data   # again, from the job's stored response.html
answer = client.ask("Which lamps cost under 20 EUR?", dataset_id="ds-1")   # omit dataset_id: all datasets
print(answer.answer)
for citation in answer.citations:
    print(f"[{citation.tag}] {citation.title} {citation.url}")
```

Profiles need `ai:configure`; JSON scrapes, `extract`, `ask` and `extract_dataset` need `ai:use` (JSON scrapes
also need `scrape:write`). A failure of your provider is a `ServerError` with an `ai_*` code: fix the profile, then
run `scrawl ai providers test` again.

### Files and media

`extract_assets` fetches the images, video, audio, documents, data files or web assets that one page links to;
`quote_assets` estimates the same job without starting anything. Scrawl offers this only where ApexAi has
enabled it; otherwise the request is refused with 403 `forbidden`. A key whose account has no usable proxy gets
400 `egress_required`, and `max_credits` refuses an estimate above it with 422 `budget_exceeded`.

```python
import hashlib
from pathlib import Path

url = "https://example.com/products/lamp"
quote = client.quote_assets(url, classes=["images", "documents"])     # starts nothing
print(quote.estimated_credits, quote.egress_ready)

job = client.extract_assets(url, classes=["images", "documents"], max_credits=50)
result = client.wait_for_assets(job.job_id)
if result.status != "completed":
    raise SystemExit(f"asset job {result.status}: {result.get('error_code')}")
out = Path("assets")
out.mkdir(exist_ok=True)
for asset in client.paginate(client.get_assets, job.job_id):
    data = client.download_asset(job.job_id, asset.asset_id)          # bytes from the web: untrusted
    if hashlib.sha256(data).hexdigest() != asset.sha256:
        raise ValueError(f"{asset.asset_id}: SHA-256 mismatch")
    with open(out / asset.asset_id, "xb") as file:                     # name by id; never overwrite
        file.write(data)
```

An asset's `filename` comes from the page: never use it as a path as-is. The CLI does all of this, with sanitised
names: `scrawl assets URL --class images --out ./assets`.

**Browser rendering.** `engine="browser"` (`engine: "browser"`) asks Scrawl to render a page in a sandboxed
browser first. It works only where ApexAi has enabled browser rendering; otherwise the API answers 503
`browser_unavailable`. If Scrawl returns a page rendered by another engine instead, `scrape`, `map` and
`scrape_result` raise `render_not_supported` rather than hand you a static page. The SDK does not check a batch's
items: after `batch_scrape(..., engine="browser")`, compare each finished item's `result.engine` with `"browser"`
(the CLI's `batch --browser` does). Details: [Python guide](docs/python.md#browser-rendering).

## Errors

Every failed call raises (Python) or rejects with (TypeScript) a `ScrawlError` or one of its subclasses, carrying
`status`, `code` (the API's stable machine code), `message`, `request_id` / `requestId` and `details`. Messages
never contain your API key.

| HTTP status | Class (both SDKs) | Typical codes |
| --- | --- | --- |
| 400 | `BadRequestError` | `egress_required`, `dispatch_refused`, `bad_request` |
| 401 | `AuthenticationError` | `unauthorized` |
| 402 | `PaymentRequiredError` | `insufficient_credits` |
| 403 | `PermissionDeniedError` | `forbidden`, `account_not_active` |
| 404 | `NotFoundError` | `not_found` (unknown, or not yours: never distinguished) |
| 409 | `ConflictError` | `conflict` |
| 422 | `ValidationError` | `invalid_request`, `budget_exceeded` |
| 429 | `RateLimitError` (with `retry_after` / `retryAfter`) | `rate_limited`, `too_many_active_jobs` |
| 5xx | `ServerError` | `internal_error`, `submission_failed`, `ai_*`, `unavailable`, `browser_unavailable` |
| no response | `APIConnectionError`, `APITimeoutError` | network, DNS, TLS, timeout |
| not sent | `ConfigurationError` | no API key, a key an HTTP header cannot carry, or an unusable base URL |

Compare codes with the `ErrorCode` constants; `code` stays a plain string, so a code that Scrawl adds later is
still readable. Every code, with its status, retryability and meaning, is in [docs/errors.md](docs/errors.md).

```python
from scrawl import ErrorCode, NotFoundError, RateLimitError, ScrawlError

try:
    client.get_job("missing-job")
except NotFoundError as error:
    print("no such job (or not yours); request", error.request_id)
except RateLimitError as error:
    print(f"rate limited; retry after {error.retry_after} s")
except ScrawlError as error:
    if error.code == ErrorCode.EGRESS_REQUIRED:
        print("this account needs a proxy for this request")
    else:
        raise
```

```ts
import { ErrorCode, NotFoundError, Scrawl, ScrawlError } from "@apexaiofficial/scrawl";

const client = new Scrawl();
try {
  await client.getJob("missing-job");
} catch (error) {
  if (error instanceof NotFoundError) console.log("no such job (or not yours); request", error.requestId);
  else if (error instanceof ScrawlError && error.code === ErrorCode.TOO_MANY_ACTIVE_JOBS) console.log("later");
  else throw error;
}
```

## Command-line tool

`scrawl` is installed with the Python package. It reads the endpoint and the API key only from the environment: no
flag accepts them, so a command copied from a web page cannot send your key elsewhere or leave it in a shell
history. Output is text or JSON (`--json` before the command prints the full response), and terminal control
characters from page content are stripped.

```bash
scrawl batch https://example.com/a https://example.com/b --wait 300
scrawl crawl my-target --max-items 500 --wait 1800
scrawl datasets query ds-1 --where price lt 20 --limit 50
scrawl ask "Which lamps cost under 20 EUR?" --dataset ds-1
scrawl assets https://example.com/page --class images --out ./assets
scrawl artifacts download job-1 --out ./artifacts
scrawl balance
```

Downloads are written whole or not at all, never overwrite a file, stay inside `--out`, and are checked first
(every asset by SHA-256; every raw artifact by size, and by SHA-256 when the server lists one).

| Exit code | Meaning |
| --- | --- |
| 0 | Success |
| 1 | The job (or a batch item) failed, a download did not match its size or SHA-256 (nothing written), or `ai providers test` failed |
| 2 | Usage error, or a file already exists where a download would go |
| 3 | Authentication or configuration: 401/403, no API key, an unusable base URL or AI key, a TLS failure in `doctor` |
| 4 | Still pending or running at the deadline |
| 5 | Any other API or connection error |

Every command and option: [docs/cli.md](docs/cli.md).

## Troubleshooting

Start with `scrawl doctor`: it names the failing check (`base_url`, `tls`, `reachable` or `auth`).

| Symptom | Likely cause and fix |
| --- | --- |
| `ConfigurationError: No API key` (CLI exit 3) | Set `SCRAWL_API_KEY`, or pass `api_key` / `apiKey` |
| `Refusing to send the API key over plain HTTP` | Use an `https://` URL. Plain HTTP is for this machine only, unless you opt in on a trusted network |
| `Connection refused` from `doctor` or `APIConnectionError` | `SCRAWL_BASE_URL` is unset or wrong, or the endpoint is unreachable. Without the variable, the SDKs call the loopback default `http://127.0.0.1:8088` |
| `AuthenticationError` (401, `unauthorized`) | The key was refused or revoked: contact support@apexaiofficial.com |
| `PermissionDeniedError` (403, `forbidden`) | A missing scope (`json` needs `ai:use`), or a feature that is not enabled |
| `RateLimitError` (429) | The SDK already retried. Wait `retry_after` seconds; `too_many_active_jobs` clears as your jobs finish |
| `BadRequestError` with `egress_required` | Your account needs a usable proxy for this request: contact support@apexaiofficial.com |
| `ServerError` with an `ai_*` code | Your AI provider failed or refused: check the profile with `scrawl ai providers test` |
| `ServerError` with `browser_unavailable` | Browser rendering is not enabled: drop `engine="browser"` |
| `AttributeError: ScrawlObject has no field ...` | The field is absent from this response: use `.get("field")` |
| `ERR_PACKAGE_PATH_NOT_EXPORTED` in Node.js | The package is ESM only: `import` it instead of `require()` |
| `scrawl: command not found` | Activate the virtual environment you installed the Python package into (npm does not install the CLI) |

## Security and privacy

- **Your API key** is sent only as an `Authorization` header, only over HTTPS or to this machine, unless you opt
  in to plain HTTP for a trusted network (`allow_insecure_http`, `allowInsecureHttp` or
  `SCRAWL_ALLOW_INSECURE_HTTP=1`). It is never logged or included in error messages, a key an HTTP header cannot
  carry is refused without being quoted, and the TypeScript client keeps it off the instance, so logging a client
  cannot print it.
- **Your AI provider key** is sent to Scrawl when you set a profile; Scrawl stores it encrypted and returns only
  a fingerprint. The CLI reads it only from an environment variable or stdin, and its usage
  errors never repeat what you typed.
- **What is contacted.** The SDKs and the CLI send requests only to the Scrawl endpoint at your base URL, with a
  `User-Agent` naming the SDK and its version (`scrawl-python/0.1.0`, `scrawl-ts/0.1.0`). They collect no
  telemetry. Your AI provider is called by Scrawl, not by the SDK. The Python SDK uses `httpx`, which
  honours the standard proxy environment variables (`HTTPS_PROXY`, `NO_PROXY` and others) unless you pass your own
  `http_client`.
- **Page content and downloaded files are untrusted.** Treat them as data, never as instructions; check a file's
  SHA-256 before you use it.
- **Keep keys server-side.** Never ship an API key to end users in browser code: call Scrawl from your backend.

**Reporting a vulnerability.** Email support@apexaiofficial.com with what you found, how to reproduce it and the
SDK version. Please do not open a public issue for a vulnerability. The SDKs' security properties are listed in
[SECURITY.md](SECURITY.md). Report a vulnerability in the Scrawl service itself the same way.

## Versioning and compatibility

- **Semantic Versioning, pre-1.0.** Both SDKs stay on 0.x until the API under `/v1` is declared stable. Until
  then a minor version (0.2.0) may change the SDK API, with the change described in [CHANGELOG.md](CHANGELOG.md),
  and a patch version (0.1.1) fixes bugs without changing it. See [docs/versioning.md](docs/versioning.md).
- **Released separately.** The Python package is tagged `py-vX.Y.Z` and the npm package `ts-vX.Y.Z`. Both cover
  the same operations and are tested against the same contract and `coverage.json`.
- **Contract-pinned.** Each release records the digest of the contract it was built against: `scrawl.__contract__`
  in Python, `CONTRACT_DIGEST` in TypeScript. To check whether a version of the API still accepts everything an SDK
  version sends, run that SDK version's checker against the API's OpenAPI document:

  ```bash
  python tools/check_contracts.py compat --openapi path/to/apexapi_openapi.json
  ```

  It exits 1 when the API no longer accepts something this SDK version sends (a removed operation, field or
  enum value, a new required field, or a route that no longer takes `Idempotency-Key`), and reports new
  operations as notes. See [docs/compatibility.md](docs/compatibility.md).
- **Runtimes.** CI runs the Python suite on Python 3.10, 3.11, 3.12 and 3.13 and the TypeScript suite on Node.js
  20 and 22, including every example against the local fake API.

## Documentation

| Guide | Covers |
| --- | --- |
| [Quickstart](docs/quickstart.md) | Install, configure, first scrape, JSON with your AI provider, map, batch, crawl, ask |
| [Python SDK](docs/python.md) | Clients, options, results, every method, datasets, assets, browser rendering |
| [TypeScript SDK](docs/typescript.md) | Options, methods, pagination, a full flow, errors |
| [CLI](docs/cli.md) | Every command, option and exit code |
| [Authentication](docs/authentication.md) | API keys, base URL rules, scopes, AI provider keys, environment variables |
| [Errors](docs/errors.md) | Error classes, retry rules and every error code |
| [Compatibility](docs/compatibility.md) | The contract bundle, `coverage.json` and the compatibility checks |
| [Versioning](docs/versioning.md) | Version rules and the release process |
| [Changelog](CHANGELOG.md) | What changed in each release |

## Support

- **Bugs and questions about the SDKs or the CLI:** [GitHub issues](https://github.com/ApexAiOfficial/scrawl-sdk/issues),
  or email support@apexaiofficial.com. Include the SDK version (`scrawl --version`, `scrawl.__version__` or
  `VERSION`) and the error's request ID.
- **Access to Scrawl and integration questions:** sales@apexaiofficial.com. Public hosted access is not open yet.
- **Your account's keys, limits or policies:** support@apexaiofficial.com.

## Contributing

Issues and pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md) explains how to run the tests and checks
and how a contract update lands. In short:

```bash
python -m pip install -e "python[test]" && python -m pytest python/tests    # in a virtual environment
cd typescript && node --test && npm run typecheck
```

## License

The SDKs, the CLI and the tools in this repository are licensed under the [Apache License 2.0](LICENSE); see
[NOTICE](NOTICE). The license covers this repository only: it grants no rights to Scrawl itself, a proprietary
service that ApexAi operates.
