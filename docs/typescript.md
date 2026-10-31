# TypeScript / JavaScript SDK

`npm install @apexaiofficial/scrawl` (once published; until then `npm install ./typescript` from a clone).
Plain ESM over the global `fetch` with complete type declarations and **no runtime dependencies**: Node 20+,
Deno, Bun and modern browsers. In a browser, never ship an API key to end users: call Scrawl from your server.

```js
import { Scrawl } from "@apexaiofficial/scrawl";

const client = new Scrawl();                    // or new Scrawl({ apiKey, baseUrl })
const page = await client.scrape("https://example.com");
```

Options: `apiKey`, `baseUrl`, `timeoutMs` (per request, default 90 000), `maxRetries` (default 2), `fetch` (your
own implementation) and `allowInsecureHttp`. See [authentication](authentication.md).

Responses are the API's JSON as-is, with snake_case fields (`page.job_id`, `batch.batch_id`); the documented
fields are typed and any field the API adds later is still readable.

## Methods

The same surface as the Python SDK, in camelCase; [`coverage.json`](../coverage.json) is the authoritative map.
Every method returns a promise; options come last, as an object.

| Area | Methods |
| --- | --- |
| Scrape | `scrape`, `scrapeResult`, `waitForScrape`, `map`, `batchScrape`, `batchStatus`, `waitForBatch` |
| AI (your provider) | `extract`, `ask`, `listAiProviders`, `setAiProvider`, `deleteAiProvider`, `setDefaultAiProvider`, `testAiProvider`, `aiUsage` |
| Crawls and jobs | `crawl`, `getJob`, `waitForJob`, `listJobs`, `cancelJob`, `listArtifacts`, `downloadArtifact` (→ `ArrayBuffer`) |
| Datasets | `listDatasets`, `getDataset`, `listVersions`, `activateVersion`, `diffVersions`, `datasetFields`, `queryDataset`, `extractDataset`, `quarantineRecord`, `releaseRecord`, `search`, `getDocument` |
| Assets | `quoteAssets`, `extractAssets`, `getAssets`, `waitForAssets`, `downloadAsset` (→ `ArrayBuffer`) |
| Account | `creditBalance`, `health` |
| Helpers | `paginate(method, ...args)` follows `next_cursor` for any list method |

```js
for await (const version of client.paginate(client.listVersions, datasetId, { limit: 50 })) {
  console.log(version.version_id);
}
```

`downloadArtifact` and `downloadAsset` buffer the whole file; for very large exports, fetch the URL with your
own streaming `fetch` and the same `Authorization: Bearer` header.

## A full flow

```js
const launch = await client.crawl("my-target", { maxItems: 500 });
await client.waitForJob(launch.job_id);
const { fields } = await client.datasetFields(launch.dataset_id);
const rows = await client.queryDataset(launch.dataset_id, [{ field: "price", op: "lt", value: 20 }]);
const answer = await client.ask("Which lamps cost under 20 EUR?", { datasetId: launch.dataset_id });
for (const citation of answer.citations) console.log(citation.tag, citation.url);
```

## Browser rendering

`engine: "browser"` (on `scrape`, `map` and `batchScrape`) renders the page in a sandboxed browser first,
waiting `waitForMs` more after it settles; only servers that enable it accept it (elsewhere: 503
`browser_unavailable`). A finished result from another engine rejects with `code: "render_not_supported"`;
pass `engine: "browser"` to `scrapeResult` / `waitForScrape` to keep that guard on a pending job. The guard
covers `scrape`, `map` and `scrapeResult`; a batch's items are not checked by the SDK, so after
`batchScrape(urls, { engine: "browser" })` compare each finished item's `result.engine` with `"browser"`.

## Errors

Failures reject with a `ScrawlError` subclass; see [errors](errors.md):

```js
import { ErrorCode, NotFoundError, ScrawlError } from "@apexaiofficial/scrawl";

try {
  await client.getJob(jobId);
} catch (error) {
  if (error instanceof NotFoundError) console.log("no such job (or not yours)");
  else if (error instanceof ScrawlError && error.code === ErrorCode.TOO_MANY_ACTIVE_JOBS) console.log("later");
  else throw error;
}
```

## Contract

`CONTRACT_DIGEST` is the digest of the contract bundle this version was built against
(see [compatibility](compatibility.md)); `VERSION` is the SDK version.
