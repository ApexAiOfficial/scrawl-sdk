# TypeScript / JavaScript SDK

`npm install @apexaiofficial/scrawl` (once published; until then `npm install ./typescript` from a clone).
Plain ESM over the global `fetch` with complete type declarations and **no runtime dependencies**: Node 20+,
Deno, Bun and modern browsers. In a browser, never ship an API key to end users: call Scrawl from your backend.

```js
import { Scrawl } from "@apexaiofficial/scrawl";

const client = new Scrawl();                    // or new Scrawl({ apiKey, baseUrl })
const page = await client.scrape("https://example.com");
```

Options: `apiKey`, `baseUrl`, `timeoutMs` (per request, default 90 000), `maxRetries` (default 2), `fetch` (your
own implementation) and `allowInsecureHttp`. See [authentication](authentication.md).

Responses use the API's snake_case fields (`page.job_id`, `batch.batch_id`); the documented fields are typed and
any field the API adds later is still readable. `Job.warnings` is always a `string[]`: `getJob`, `waitForJob` and
`listJobs` default it to `[]` when an older server omits it.

Settled scrapes and maps expose `outcome`: `"ok"`, `"target_blocked"`, `"target_error"`, `"cancelled"` or
`"pipeline_failed"` (`null` while pending). Scrapes also have `block_reason`, `retry_after_s` and `hint`; maps
have `block_reason` and `hint`; batches have `outcomes` counts. Refunds are automatic and cover only Scrawl's own failures: a job that never started, and a scrape whose outcome is `pipeline_failed`. Target
blocks/errors, failures in your proxy and cancellations after work starts remain charged.

## Methods

The same surface as the Python SDK, in camelCase; [`coverage.json`](../coverage.json) is the authoritative map.
Every method returns a promise; options come last, as an object.

| Area | Methods |
| --- | --- |
| Scrape | `scrape`, `scrapeResult`, `waitForScrape`, `map`, `batchScrape`, `batchStatus`, `waitForBatch` |
| Local fetch | `localFetch(url, { respectRobots, maxRedirects, maxBytes, fetchPage, ...scrapeOptions })`, `scrapeLocal(url, body, { httpStatus, contentType, finalUrl, ... })` |
| AI (your provider) | `extract`, `ask`, `listAiProviders`, `setAiProvider`, `deleteAiProvider`, `setDefaultAiProvider`, `testAiProvider`, `aiUsage` |
| Crawls and jobs | `crawl`, `crawlSite`, `siteCrawlStatus`, `waitForSiteCrawl`, `getJob`, `waitForJob`, `listJobs`, `cancelJob`, `listArtifacts`, `downloadArtifact` (→ `ArrayBuffer`) |
| Datasets | `listDatasets`, `getDataset`, `listVersions`, `activateVersion`, `diffVersions`, `datasetFields`, `queryDataset`, `extractDataset`, `curateDataset`, `listCurations`, `quarantineRecord`, `releaseRecord`, `search`, `getDocument` |
| Assets | `quoteAssets`, `extractAssets`, `getAssets`, `waitForAssets`, `downloadAsset` (→ `ArrayBuffer`), `downloadAssetText` (a document's Markdown, → `string`) |
| Proxy | `getProxy`, `setProxy`, `testProxy`, `removeProxy`, `listProxyPool`, `addProxyPoolEntry`, `testProxyPoolEntry`, `enableProxyPoolEntry`, `disableProxyPoolEntry`, `removeProxyPoolEntry`, `setProxyPoolMode`, `proxyHealth` |
| Account | `creditBalance`, `health`, `listApiKeys`, `revokeApiKey` |
| Helpers | `paginate(method, ...args)` follows `next_cursor` for any list method |

```js
for await (const version of client.paginate(client.listVersions, datasetId, { limit: 50 })) {
  console.log(version.version_id);
}
```

Hosted API keys are created in Telegram with `/api_keys create`; the SDK deliberately has no create method.
Listing and revoking need a key with `keys:manage`, made with `/api_keys create_manager`.
`listApiKeys` and `revokeApiKey` need `keys:manage`.

`downloadArtifact` and `downloadAsset` buffer the whole file; for very large exports, fetch the URL with your
own streaming `fetch` and the same `Authorization: Bearer` header.

## Content, site crawls and local fetch

`scrape`, `batchScrape`, `crawlSite` and a `reextract` curation take `onlyMainContent` (`false` keeps the whole
body), `includeTags` (keep only what these CSS selectors match) and `excludeTags` (drop what they match first).
Each list takes at most 20 selectors. They are sent only when set, and the server validates them.

```js
let site = await client.crawlSite("https://example.com/docs/", { maxPages: 50, maxDepth: 2 });
site = await client.waitForSiteCrawl(site.crawl_id);                    // done: the version is final
const deduped = await client.curateDataset(site.dataset_id, "dedupe");  // a new version, no fetch, no charge
```

A site crawl stays on the URL's host and reads robots.txt first. Each page is charged as a scrape, so `maxPages`
is the most it can cost. `cancelJob(site.crawl_id)` stops it, and `resumeFrom` continues an ended crawl.
`localFetch(url)` fetches the page from your machine (robots.txt honoured by default), then has Scrawl render it;
Scrawl fetches nothing. The result says `origin: "client_fetched"` and `url_verified: false`. Link-local and
cloud-metadata destinations are refused (`link_local_refused`) unless `allowLinkLocal: true`. In Node every request
resolves its host and checks each address before connecting; in a browser only the literal addresses and names are
checked. Private and loopback addresses stay reachable: only fetch URLs you chose.

A job's `status` is passed through as the server sent it: the lower case (`completed`) from current servers, the
upper case from older ones. `JobStatus` has both spellings, and the upper-case members are deprecated: compare
with the lower case, or with `status.toLowerCase()`.

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
waiting `waitForMs` more after it settles; it is accepted only where ApexAi has enabled it (elsewhere: 503
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
