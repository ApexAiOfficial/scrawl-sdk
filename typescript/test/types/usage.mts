// Compile-only check of src/index.d.ts (`npm run typecheck`). The expected-error directives below must stay
// errors, so the declarations cannot silently loosen.
import {
  BadRequestError, CONTRACT_DIGEST, ConfigurationError, ErrorCode, NotFoundError, RateLimitError, Scrawl, ScrawlError,
  type AssetClass, type AssetJob, type AssetQuote, type AssetResult, type QueryFilter, type ScrapeEngine,
  type ScrapeResult, type SkippedAsset,
} from "@apexaiofficial/scrawl";

const client = new Scrawl({ apiKey: "k", baseUrl: "https://scrawl.example", timeoutMs: 1000, maxRetries: 1 });

export async function usage(): Promise<void> {
  let page: ScrapeResult = await client.scrape("https://e.example", { formats: ["markdown", "json"], schema: { type: "object" } });
  if (page.status === "pending") page = await client.waitForScrape(page.job_id, { timeoutMs: 1000 });
  const markdown: string | null | undefined = page.markdown;
  const status: string | null | undefined = page.http_status;
  const newer: unknown = page.some_field_added_later;
  const rendered = await client.scrape("https://e.example", { engine: "browser", waitForMs: 500 });
  const engine: ScrapeEngine | undefined = rendered.engine;
  const settle: string | null | undefined = rendered.browser?.settle;
  const finalUrl: string | null | undefined = rendered.final_url;
  console.log(engine, settle, finalUrl, CONTRACT_DIGEST);
  // @ts-expect-error: the engine is "static" or "browser"
  await client.scrape("https://e.example", { engine: "chrome" });
  const map = await client.map("https://e.example", { limit: 10, engine: "browser" });
  const mapEngine: ScrapeEngine | undefined = map.engine;
  console.log(mapEngine);
  const batch = await client.batchScrape(map.links ?? []);
  const done = await client.waitForBatch(batch.batch_id);
  for (const item of done.items ?? []) console.log(item.url, item.result?.markdown);
  const filters: QueryFilter[] = [{ field: "price", op: "lt", value: 20 }, { field: "sku", op: "exists", value: true }];
  const rows = await client.queryDataset("d", filters, { limit: 5 });
  console.log(rows.records[0]?.record_id, rows.records[0]?.provenance);
  const job = await client.getJob("j");
  const firstArg: string | undefined = job.args[0];
  const launch = await client.crawl("target", { exportFormat: "csv" });
  const finished = await client.waitForJob(launch.job_id, { timeoutMs: 1000 });
  console.log(finished.status === "COMPLETED", launch.dataset_version_id);
  for await (const version of client.paginate(client.listVersions, "d", { limit: 2 })) console.log(version);
  const versions = await client.listVersions("d");
  console.log(versions.versions.map((v) => v.version_id));
  const bytes: ArrayBuffer = await client.downloadArtifact("j", "f.html", { format: "markdown" });
  const listing = await client.listArtifacts("j");
  console.log(listing.artifacts.map((a) => `${a.name}:${a.size_bytes}`));
  console.log(markdown, status, newer, rows.records.length, firstArg, bytes.byteLength);
  new Scrawl({ baseUrl: "http://scrawl-lan.test", allowInsecureHttp: true });
  const profile = await client.setAiProvider("p", { provider: "example", apiKey: "k" });
  console.log(profile.key_fingerprint, (await client.testAiProvider("p")).ok, (await client.aiUsage()).totals.length);
  const removed: null = await client.deleteAiProvider("p");
  console.log(removed);
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
  await client.extractAssets("https://e.example/page", { classes: ["archives"] });
  // @ts-expect-error - a quote starts nothing, so it takes no idempotency key
  await client.quoteAssets("https://e.example/page", { idempotencyKey: "k" });
  // @ts-expect-error - views are an enum
  await client.getAssets("j", { view: "all" });
  // @ts-expect-error - http_status is a string
  const code: number | null = page.http_status;
  // @ts-expect-error - not a known code constant
  const unknownCode: ErrorCode = "made_up";
  console.log(code, unknownCode);
}
