# Python SDK

`pip install scrawl-sdk` (once published; until then `pip install ./python` from a clone). Python 3.10+, one
runtime dependency (`httpx`). Typed (`py.typed`). The import name is `scrawl`.

```python
from scrawl import AsyncScrawl, Scrawl

with Scrawl() as client:                                   # or Scrawl(api_key=..., base_url=...)
    page = client.scrape("https://example.com")

async with AsyncScrawl() as client:                        # the same methods, awaited
    page = await client.scrape("https://example.com")
```

Constructor options (both clients): `api_key`, `base_url`, `timeout` (seconds per request, default 90),
`max_retries` (default 2), `http_client` (your own `httpx.Client` / `httpx.AsyncClient`) and
`allow_insecure_http`. See [authentication](authentication.md).

## Results

Results are `ScrawlObject`s: dicts with attribute access (`page.markdown == page["markdown"]`), recursively,
so new API fields appear without an SDK upgrade. A typo raises `AttributeError` instead of returning `None`;
use `.get()` for fields that may be absent. An API field named like a dict method wins (`batch.items` is the
batch's items; the method stays available as `dict.items(batch)`). Call `.to_dict()` for plain data, for
example before `json.dumps` (which would otherwise call the `items` field).

## Methods

Every ApexAPI operation the SDK covers has one method; [`coverage.json`](../coverage.json) is the authoritative
map. Submits that start work take an optional `idempotency_key` (one is generated otherwise).

| Area | Methods |
| --- | --- |
| Scrape | `scrape(url, formats=, schema=, instruction=, profile=, wait_seconds=30, engine=, wait_for_ms=)`, `scrape_result(job_id, wait_seconds=, formats=, engine=)`, `map(url, limit=100, wait_seconds=30, engine=, wait_for_ms=)`, `batch_scrape(urls, ...)`, `batch_status(batch_id, wait_seconds=)` |
| AI (your provider) | `extract(job_id, artifact="response.html", schema=, instruction=, profile=)`, `ask(question, dataset_id=, profile=)`, `list_ai_providers()`, `set_ai_provider(profile, provider=, api_key=, model=, base_url=)`, `delete_ai_provider(profile)`, `set_default_ai_provider(profile)`, `test_ai_provider(profile)`, `ai_usage(days=30)` |
| Crawls and jobs | `crawl(crawl_target, export_format=, max_items=, max_seconds=)`, `get_job(job_id, wait_seconds=)`, `list_jobs(limit=, status=, cursor=)`, `cancel_job(job_id)`, `list_artifacts(job_id)`, `download_artifact(job_id, filename, format=)` (bytes) |
| Datasets | `list_datasets`, `get_dataset`, `list_versions`, `activate_version`, `diff_versions`, `dataset_fields`, `query_dataset(dataset_id, filters, version_id=, limit=, cursor=)`, `extract_dataset`, `quarantine_record`, `release_record`, `search`, `get_document` |
| Assets | `quote_assets(url, classes=, max_items=, max_bytes=, max_credits=)`, `extract_assets(...)`, `get_assets(job_id, view=, limit=, cursor=, wait_seconds=)`, `download_asset(job_id, asset_id)` (bytes) |
| Account | `credit_balance()`, `health()` |
| Helpers | `wait_for_scrape(job_id, timeout=300, engine=)`, `wait_for_batch(batch_id, timeout=600)`, `wait_for_assets(job_id, timeout=600)`, `wait_for_job(job_id, timeout=1800)`, `paginate(method, *args, **kwargs)` |

The `wait_for_*` helpers use server-side waits (up to 60 s per request, kept inside your `timeout`), never
tight polling. `paginate` follows `next_cursor` for any list method:

```python
for version in client.paginate(client.list_versions, dataset_id):
    print(version.version_id)
for record in client.paginate(client.query_dataset, dataset_id, [{"field": "price", "op": "lt", "value": 20}]):
    print(record.record_id)
```

## Datasets

```python
launch = client.crawl("my-target", max_items=500)             # a named crawl target -> a new dataset version
job = client.wait_for_job(launch.job_id)                      # COMPLETED, FAILED, CANCELLED or ORPHANED
fields = client.dataset_fields(launch.dataset_id)             # paths, types, presence, examples
cheap = client.query_dataset(launch.dataset_id, [{"field": "price", "op": "lt", "value": 20}])
changes = client.diff_versions(launch.dataset_id, "v_old", "v_new")
client.activate_version(launch.dataset_id, "v_old")           # roll back (or forward)
answer = client.ask("Which lamps cost under 20 EUR?", dataset_id=launch.dataset_id)
```

Filter operators: `eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `contains`, `in`, `exists` (every filter needs a
`value`; `exists` takes a boolean).

## Assets

```python
quote = client.quote_assets(url, classes=["images", "documents"])     # starts nothing
job = client.extract_assets(url, classes=["images", "documents"], max_credits=50)
result = client.wait_for_assets(job.job_id)                           # completed / failed / cancelled / orphaned
for asset in client.paginate(client.get_assets, job.job_id):
    data = client.download_asset(job.job_id, asset.asset_id)          # bytes: compare with asset.sha256
```

Classes: `images`, `video`, `audio`, `documents`, `data`, `web_assets`. `max_credits` refuses an estimate above
it (422 `budget_exceeded`); a key without usable egress gets 400 `egress_required`. A downloaded file's
`filename` comes from the page: never use it as a path as-is (the CLI's `--out` sanitises it).

## Browser rendering

`engine="browser"` (on `scrape`, `map` and `batch_scrape`) renders the page in a sandboxed browser first,
waiting `wait_for_ms` more after it settles. It is available only where ApexAi has enabled it; elsewhere
the API answers 503 `browser_unavailable`. If a Scrawl version that predates the browser engine returns a
finished result rendered by another engine, the SDK raises `ScrawlError(code="render_not_supported")` instead
of handing you a static page; pass `engine="browser"` to `scrape_result` / `wait_for_scrape` to keep that guard when you follow
up a pending job. The guard covers `scrape`, `map` and `scrape_result`; a batch's items are not checked by the
SDK, so after `batch_scrape(..., engine="browser")` compare each finished item's `result.engine` with
`"browser"` (the CLI's `batch --browser` and `batch-status --browser` do).

## Errors

See [errors](errors.md) for the classes, every code and the retry rules:

```python
import time

from scrawl import ErrorCode, NotFoundError, RateLimitError, ScrawlError

try:
    client.get_job(job_id)
except NotFoundError:
    ...
except RateLimitError as error:
    time.sleep(error.retry_after or 5)
except ScrawlError as error:
    if error.code == ErrorCode.EGRESS_REQUIRED:
        ...
```

## Contract

`scrawl.__contract__` is the digest of the contract bundle this version was built against
(see [compatibility](compatibility.md)); `scrawl.__version__` is the SDK version.
