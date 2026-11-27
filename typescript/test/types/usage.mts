// Compile-only check of src/index.d.ts (`npm run typecheck`). The expected-error directives below must stay
// errors, so the declarations cannot silently loosen.
import {
  BadRequestError, CONTRACT_DIGEST, ConfigurationError, ErrorCode, NotFoundError, RateLimitError, Scrawl, ScrawlError,
  type AssetClass, type AssetJob, type AssetQuote, type AssetResult, type JobStatus, type QueryFilter, type ScrapeEngine,
  type ProxyHealth, type ProxyPool, type ScrapeOutcome, type ScrapeResult, type SkippedAsset,
} from "@apexaiofficial/scrawl";

const client = new Scrawl({ apiKey: "k", baseUrl: "https://scrawl.example", timeoutMs: 1000, maxRetries: 1 });

export async function usage(): Promise<void> {
  let page: ScrapeResult = await client.scrape("https://e.example", { formats: ["markdown", "json"], schema: { type: "object" } });
  if (page.status === "pending") page = await client.waitForScrape(page.job_id, { timeoutMs: 1000 });
  const markdown: string | null | undefined = page.markdown;
  const status: string | null | undefined = page.http_status;
  const outcome: ScrapeOutcome | null | undefined = page.outcome;
  const blockReason: string | null | undefined = page.block_reason;
  const retryAfter: number | null | undefined = page.retry_after_s;
  const hint: string | null | undefined = page.hint;
  const newer: unknown = page.some_field_added_later;
  const rendered = await client.scrape("https://e.example", { engine: "browser", waitForMs: 500 });
  const engine: ScrapeEngine | undefined = rendered.engine;
  const settle: string | null | undefined = rendered.browser?.settle;
  const finalUrl: string | null | undefined = rendered.final_url;
  console.log(engine, settle, finalUrl, outcome, blockReason, retryAfter, hint, CONTRACT_DIGEST);
  const trimmed = await client.scrape("https://e.example", { onlyMainContent: false, includeTags: ["article", ".post"],
    excludeTags: ["nav"] });
  console.log(trimmed.markdown);
  await client.batchScrape(["https://e.example"], { onlyMainContent: true, includeTags: null, excludeTags: ["aside"] });
  // @ts-expect-error: onlyMainContent is a boolean
  await client.scrape("https://e.example", { onlyMainContent: "no" });
  // @ts-expect-error: the tag options are lists of selectors
  await client.scrape("https://e.example", { includeTags: "article" });
  // @ts-expect-error: the camelCase names are the SDK's; the snake_case ones are the wire format
  await client.scrape("https://e.example", { include_tags: ["article"] });
  // @ts-expect-error: the engine is "static" or "browser"
  await client.scrape("https://e.example", { engine: "chrome" });
  const map = await client.map("https://e.example", { limit: 10, engine: "browser" });
  const mapEngine: ScrapeEngine | undefined = map.engine;
  const mapOutcome: ScrapeOutcome | null | undefined = map.outcome;
  console.log(mapEngine, mapOutcome, map.block_reason, map.hint);
  const batch = await client.batchScrape(map.links ?? []);
  const done = await client.waitForBatch(batch.batch_id);
  console.log(done.outcomes?.target_blocked);
  for (const item of done.items ?? []) console.log(item.url, item.result?.markdown);
  const filters: QueryFilter[] = [{ field: "price", op: "lt", value: 20 }, { field: "sku", op: "exists", value: true }];
  const rows = await client.queryDataset("d", filters, { limit: 5 });
  console.log(rows.records[0]?.record_id, rows.records[0]?.provenance);
  const job = await client.getJob("j");
  const firstArg: string | undefined = job.args[0];
  // A status is passed through as the server sent it: 0.1.4 code comparing with the upper case still compiles, and
  // the lower case (the API's spelling today) is accepted everywhere a JobStatus is.
  const lowerCase: JobStatus = "completed";
  const upperCase: JobStatus = "COMPLETED";                            // deprecated, still a JobStatus
  const jobStatus: string = job.status;
  const crawlStatus: JobStatus = (await client.crawl("target")).status;
  const cancelled: boolean = (await client.cancelJob("j")).status === "cancelled";
  const versionDone = (await client.getDataset("d")).versions[0]?.status === "COMPLETED";
  const extracting = (await client.extractDataset("d", { instruction: "titles" })).status === "pending";
  const siteDone: boolean = (await client.siteCrawlStatus("c")).status === "completed";
  await client.listJobs({ status: "COMPLETED" });                     // either case filters
  await client.listJobs({ status: "running" });
  console.log(lowerCase, upperCase, jobStatus, crawlStatus, cancelled, versionDone, extracting, siteDone);
  const jobWarnings: string[] = job.warnings;
  const launch = await client.crawl("target", { exportFormat: "csv" });
  const finished = await client.waitForJob(launch.job_id, { timeoutMs: 1000 });
  console.log(finished.status === "COMPLETED", finished.status === "completed", launch.dataset_version_id);
  for await (const version of client.paginate(client.listVersions, "d", { limit: 2 })) console.log(version);
  const versions = await client.listVersions("d");
  console.log(versions.versions.map((v) => v.version_id));
  const bytes: ArrayBuffer = await client.downloadArtifact("j", "f.html", { format: "markdown" });
  const listing = await client.listArtifacts("j");
  console.log(listing.artifacts.map((a) => `${a.name}:${a.size_bytes}`));
  console.log(markdown, status, newer, rows.records.length, firstArg, jobWarnings, bytes.byteLength);
  new Scrawl({ baseUrl: "http://scrawl-lan.test", allowInsecureHttp: true });
  const profile = await client.setAiProvider("p", { provider: "example", apiKey: "k" });
  console.log(profile.key_fingerprint, (await client.testAiProvider("p")).ok, (await client.aiUsage()).totals.length);
  const removed: null = await client.deleteAiProvider("p");
  console.log(removed);
  const pool: ProxyPool = await client.listProxyPool();
  const added: null = await client.addProxyPoolEntry({ url: "http://proxy.example:8000", label: "a" });
  const testedPool = await client.testProxyPoolEntry("a");
  await client.disableProxyPoolEntry(testedPool.entry.entry_id);
  await client.enableProxyPoolEntry(testedPool.entry.entry_id);
  await client.setProxyPoolMode("pool");
  await client.removeProxyPoolEntry(testedPool.entry.entry_id);
  const proxyHealth: ProxyHealth = await client.proxyHealth();
  const keys = await client.listApiKeys();
  if (keys.keys[0]) await client.revokeApiKey(keys.keys[0].key_id);
  console.log(pool.mode, proxyHealth.reachable);
  const quote: AssetQuote = await client.quoteAssets("https://e.example/page", { classes: ["images", "documents"], maxCredits: 50 });
  const started: AssetJob = await client.extractAssets("https://e.example/page", { classes: ["video"], maxItems: 10,
    maxBytes: 1_000_000, idempotencyKey: "k" });
  const assets: AssetResult = await client.waitForAssets(started.job_id, { timeoutMs: 1000 });
  for (const asset of assets.assets ?? []) {
    const kind: AssetClass = asset.asset_class;
    const file: ArrayBuffer = await client.downloadAsset(started.job_id, asset.asset_id);
    console.log(kind, asset.sha256, file.byteLength);
  }
  for await (const skip of client.paginate<SkippedAsset>(client.getAssets, started.job_id, { view: "skipped" })) {
    console.log(skip.reason, skip.bytes_received);
  }
  const skippedPage = await client.getAssets(started.job_id, { view: "skipped", limit: 50, cursor: "c", waitSeconds: 5 });
  console.log(quote.egress_ready, skippedPage.counts.skipped_omitted, skippedPage.billing.state);
  try {
    await client.getJob("x");
  } catch (error) {
    if (error instanceof RateLimitError) console.log(error.retryAfter, error.code);
    if (error instanceof NotFoundError) console.log(error.status, error.requestId);
    if (error instanceof BadRequestError && error.code === ErrorCode.EGRESS_REQUIRED) console.log("add a proxy");
    if (error instanceof ConfigurationError) console.log("fix SCRAWL_API_KEY / SCRAWL_BASE_URL");
    if (error instanceof ScrawlError) {
      const code: string | null = error.code;
      console.log(error.details, code);
    }
  }
  const known: ErrorCode = ErrorCode.NOT_FOUND;
  console.log(known);

  // @ts-expect-error - unknown option
  await client.scrape("https://e.example", { wait: 5 });
  // @ts-expect-error - not a format
  await client.scrape("https://e.example", { formats: ["pdf"] });
  // @ts-expect-error - JSON is never re-extracted when a finished scrape is read again
  await client.scrapeResult("j", { formats: ["json"] });
  // @ts-expect-error - every filter needs a value
  await client.queryDataset("d", [{ field: "a", op: "exists" }]);
  // @ts-expect-error - export formats are an enum
  await client.crawl("t", { exportFormat: "jsonlines-gz" });
  // @ts-expect-error - not an asset class
  await client.extractAssets("https://e.example/page", { classes: ["fonts"] });
  // @ts-expect-error - a quote starts nothing, so it takes no idempotency key
  await client.quoteAssets("https://e.example/page", { idempotencyKey: "k" });
  // @ts-expect-error - views are an enum
  await client.getAssets("j", { view: "all" });
  // @ts-expect-error - http_status is a string
  const code: number | null = page.http_status;
  // @ts-expect-error - not a known code constant
  const unknownCode: ErrorCode = "made_up";
  // ADR C-7: a pending or paged result names its next call (method, path, query or body) and when to poll.
  const next = page.next_call;
  if (next) {
    const route: string = `${next.method} ${next.path}`;
    const wait: number | null | undefined = page.poll_after_seconds;
    console.log(route, wait, next.query, page.docs_url, (page.next_actions ?? []).map((action) => action.why));
  }
  // @ts-expect-error - poll_after_seconds is a number
  const later: string | null | undefined = page.poll_after_seconds;
  console.log(code, unknownCode, later);
}
