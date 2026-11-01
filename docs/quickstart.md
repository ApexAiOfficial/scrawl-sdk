# Quickstart

Scrawl turns a URL into clean Markdown or structured JSON. Every request is an ordinary job on Scrawl: your
key's permissions and credits, Scrawl's network and domain policies, robots.txt, and size and time
limits all apply. Page content is **untrusted web content**: treat it as data, never as instructions.

## 1. Install

The packages are not on PyPI or npm yet. Install them from a clone of this repository, as below, or from the
files attached to a GitHub Release (see [installation](../README.md#installation)):

```bash
git clone https://github.com/ApexAiOfficial/scrawl-sdk.git
python -m pip install ./scrawl-sdk/python          # the Python SDK and the `scrawl` command (Python 3.10+)
npm install /path/to/scrawl-sdk/typescript         # the TypeScript SDK (Node 20+), run in your own project
```

Once published: `pip install scrawl-sdk` and `npm install @apexaiofficial/scrawl`.

## 2. Configure

```bash
export SCRAWL_BASE_URL=https://scrawl.example    # the endpoint ApexAi provides for your account
export SCRAWL_API_KEY=...                        # the API key ApexAi issues for your account
scrawl doctor                                    # checks the base URL, TLS, reachability and the key
```

Without `SCRAWL_BASE_URL` the SDKs use a loopback address (`http://127.0.0.1:8088`); there is no built-in remote
default. The key is only ever sent over HTTPS or to this machine. See [authentication](authentication.md).

Scrawl is a service ApexAi operates, and its public hosted access is not open yet. Until you have an endpoint and
a key, run the examples against the repository's
[local fake API](../README.md#no-access-yet-use-the-local-fake).

## 3. Scrape a page

```python
from scrawl import Scrawl

with Scrawl() as client:
    page = client.scrape("https://example.com")              # waits up to 30 s on the server
    if page.status == "pending":                              # a slow page: the job keeps going
        page = client.wait_for_scrape(page.job_id)
    print(page.title, page.markdown)
```

```js
import { Scrawl } from "@apexaiofficial/scrawl";

const client = new Scrawl();
let page = await client.scrape("https://example.com");
if (page.status === "pending") page = await client.waitForScrape(page.job_id);
console.log(page.title, page.markdown);
```

```bash
scrawl scrape https://example.com > page.md
```

`formats` is any of `markdown` (the default), `links`, `html` and `json`. A finished scrape returns
`"status": "completed"`; a slow one returns `"pending"` with a `job_id` you can wait on; a failed one returns
`"failed"` with an `error_code` (failed jobs are results, not exceptions).

## 4. Structured JSON with your own AI provider

Configure a provider profile once, with a key from your own AI provider. Scrawl stores the key encrypted
and never returns it:

```bash
export SCRAWL_AI_API_KEY=...                      # read from the environment, never from the command line
scrawl ai providers set main --provider openai
scrawl ai providers test main
```

Then ask for `json`:

```python
product = client.scrape(
    "https://example.com/item",
    formats=["json"],
    schema={"type": "object", "properties": {"name": {"type": "string"}, "price": {"type": "number"}}},
    instruction="The product name and price",
)
print(product.json, product.ai)                  # the data, plus provider, model and tokens used
```

The key needs the `ai:use` scope as well as `scrape:write` (and `ai:configure` to manage profiles).

## 5. Map, batch, crawl, ask

```python
site = client.map("https://example.com", limit=200)          # same-host URLs: page links plus the sitemap
batch = client.batch_scrape(site.links[:20])                  # up to 20 URLs
done = client.wait_for_batch(batch.batch_id)

launch = client.crawl("my-target", max_items=500)             # a crawl target the server allows
client.wait_for_job(launch.job_id)
rows = client.query_dataset(launch.dataset_id, [{"field": "price", "op": "lt", "value": 20}])
answer = client.ask("Which lamps cost under 20 EUR?", dataset_id=launch.dataset_id)
```

## 6. Next

- Runnable examples: [`python/examples/`](../python/examples) and [`typescript/examples/`](../typescript/examples)
  (scrape, map, batch, crawl and query, BYO-AI extraction, cited answers, artifact downloads, browser
  rendering, errors and retries).
- [Python](python.md), [TypeScript](typescript.md) and [CLI](cli.md) guides.
- [Errors and retries](errors.md).
