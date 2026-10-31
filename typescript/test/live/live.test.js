// Live compatibility suite: every covered ApexAPI operation against a real Scrawl server.
//
// Skipped unless both are set:
//   SCRAWL_LIVE_BASE_URL      the server, e.g. https://scrawl.example or http://127.0.0.1:8088
//   SCRAWL_LIVE_API_KEY       a key with the default scopes (scrape:write, jobs:read, artifacts:read, credits:read)
// Deterministic targets and optional areas (each area is skipped, with its reason, until its variables are set):
//   SCRAWL_LIVE_TARGET_URL    a stable page the server may fetch (required for anything that fetches)
//   SCRAWL_LIVE_CRAWL_TARGET  a crawl target the key may run (crawl, datasets, search, documents, quarantine)
//   SCRAWL_LIVE_AI_PROVIDER, SCRAWL_LIVE_AI_API_KEY [SCRAWL_LIVE_AI_MODEL, SCRAWL_LIVE_AI_BASE_URL]
//                             your own AI provider; the key needs ai:configure and ai:use
//   SCRAWL_LIVE_ASSETS=1      the server allows asset extraction with egress for this key
//   SCRAWL_LIVE_BROWSER=1     the server has browser rendering enabled
//
// covers(...) names the operations each test exercises; contract.test.js checks that together they name every
// covered operation in coverage.json, so the suite cannot silently fall behind the SDK.

import assert from "node:assert/strict";
import { createHash, randomUUID } from "node:crypto";
import { test } from "node:test";

import { AuthenticationError, ConflictError, ErrorCode, NotFoundError, Scrawl } from "../../src/index.js";

const env = process.env;
const BASE_URL = env.SCRAWL_LIVE_BASE_URL;
const API_KEY = env.SCRAWL_LIVE_API_KEY;
const skip = BASE_URL && API_KEY ? false : "set SCRAWL_LIVE_BASE_URL and SCRAWL_LIVE_API_KEY";
const client = skip ? null : new Scrawl({ apiKey: API_KEY, baseUrl: BASE_URL, timeoutMs: 90_000 });

/** The operations a live test exercises (read statically by contract.test.js). */
function covers(...routes) {
  return { skip, routes };
}

/** The values of NAMES, or null after marking the test skipped (the caller returns). */
function need(t, ...names) {
  const missing = names.filter((name) => !env[name]);
  if (missing.length) {
    t.skip(`set ${missing.join(", ")}`);
    return null;
  }
  return names.map((name) => env[name]);
}

const once = (make) => {
  let promise = null;
  return () => (promise ??= make());
};

const page = once(async () => {
  let result = await client.scrape(env.SCRAWL_LIVE_TARGET_URL, { formats: ["markdown", "links"], waitSeconds: 60 });
  if (result.status === "pending") result = await client.waitForScrape(result.job_id, { timeoutMs: 300_000 });
  assert.equal(result.status, "completed", result.error ?? "");
  return result;
});

async function withProfile(use) {
  const name = `live${randomUUID().replaceAll("-", "").slice(0, 8)}`;
  const info = await client.setAiProvider(name, { provider: env.SCRAWL_LIVE_AI_PROVIDER,
    apiKey: env.SCRAWL_LIVE_AI_API_KEY, model: env.SCRAWL_LIVE_AI_MODEL || undefined,
    baseUrl: env.SCRAWL_LIVE_AI_BASE_URL || undefined });
  assert.equal(info.profile, name);
  assert.ok(!JSON.stringify(info).includes(env.SCRAWL_LIVE_AI_API_KEY), "the provider key is never returned");
  try {
    await use(name);
  } finally {
    await client.deleteAiProvider(name);
  }
}

const dataset = once(async () => {
  const launches = [];
  for (let i = 0; i < 2; i += 1) {
    const launch = await client.crawl(env.SCRAWL_LIVE_CRAWL_TARGET, { maxItems: 20, maxSeconds: 300 });
    const job = await client.waitForJob(launch.job_id, { timeoutMs: 900_000 });
    assert.equal(String(job.status).toUpperCase(), "COMPLETED");
    launches.push(launch);
  }
  return { datasetId: launches.at(-1).dataset_id, versions: launches.map((launch) => launch.dataset_version_id) };
});

test("health, a refused key and the jobs list", covers("GET /v1/health", "GET /v1/jobs"), async () => {
  assert.equal((await client.health()).status, "ok");
  assert.ok(Array.isArray((await client.listJobs({ limit: 1 })).jobs ?? []));
  const wrong = new Scrawl({ apiKey: "sk_live_suite_wrong_key", baseUrl: BASE_URL, maxRetries: 0 });
  const error = await wrong.listJobs({ limit: 1 }).catch((exc) => exc);
  assert.ok(error instanceof AuthenticationError, String(error));
  assert.equal(error.status, 401);
});

test("an unknown id is a 404", covers("GET /v1/jobs/{job_id}"), async () => {
  const error = await client.getJob(`missing-${randomUUID()}`).catch((exc) => exc);
  assert.ok(error instanceof NotFoundError, String(error));
  assert.equal(error.code, ErrorCode.NOT_FOUND);
});

test("scrape, its result, its job and its artifacts", covers("POST /v1/scrape", "GET /v1/scrape/{job_id}/content",
  "GET /v1/jobs/{job_id}", "GET /v1/artifacts/{job_id}", "GET /v1/artifacts/{job_id}/{filename}"), async (t) => {
  if (!need(t, "SCRAWL_LIVE_TARGET_URL")) return;
  const scraped = await page();
  assert.ok(scraped.markdown && scraped.untrusted_external_content === true);
  const again = await client.scrapeResult(scraped.job_id, { formats: ["links"] });
  assert.ok(Array.isArray(again.links));
  assert.equal((await client.getJob(scraped.job_id)).job_id, scraped.job_id);
  const { artifacts } = await client.listArtifacts(scraped.job_id);
  assert.ok(artifacts.length > 0);
  const bytes = await client.downloadArtifact(scraped.job_id, artifacts[0].name);
  assert.equal(bytes.byteLength, artifacts[0].size_bytes);
});

test("map", covers("POST /v1/map"), async (t) => {
  const values = need(t, "SCRAWL_LIVE_TARGET_URL");
  if (!values) return;
  const site = await client.map(values[0], { limit: 20, waitSeconds: 60 });
  assert.ok(["completed", "pending"].includes(site.status));
});

test("batch", covers("POST /v1/scrape/batch", "GET /v1/scrape/batch/{batch_id}"), async (t) => {
  const values = need(t, "SCRAWL_LIVE_TARGET_URL");
  if (!values) return;
  const started = await client.batchScrape([values[0]]);
  const done = await client.waitForBatch(started.batch_id, { timeoutMs: 300_000 });
  assert.equal(done.status, "completed");
  assert.equal(done.items[0].status, "completed");
});

test("cancel", covers("POST /v1/jobs/{job_id}/cancel"), async (t) => {
  const values = need(t, "SCRAWL_LIVE_TARGET_URL");
  if (!values) return;
  const started = await client.scrape(values[0], { waitSeconds: 0 });
  const result = await client.cancelJob(started.job_id).catch((exc) => exc);
  if (result instanceof ConflictError) return;                      // it already finished
  assert.equal(result.job_id, started.job_id);
});

test("credit balance", covers("GET /v1/credits/balance"), async () => {
  assert.equal(typeof (await client.creditBalance()), "object");
});

test("bring-your-own AI: profiles, JSON scrape, extract, usage", covers("PUT /v1/ai/providers/{profile}",
  "GET /v1/ai/providers", "POST /v1/ai/providers/{profile}/default", "POST /v1/ai/providers/{profile}/test",
  "GET /v1/ai/usage", "POST /v1/extract", "DELETE /v1/ai/providers/{profile}"), async (t) => {
  if (!need(t, "SCRAWL_LIVE_TARGET_URL", "SCRAWL_LIVE_AI_PROVIDER", "SCRAWL_LIVE_AI_API_KEY")) return;
  const scraped = await page();
  await withProfile(async (name) => {
    assert.ok((await client.listAiProviders()).profiles.some((p) => p.profile === name));
    assert.equal((await client.setDefaultAiProvider(name)).is_default, true);
    assert.equal((await client.testAiProvider(name)).ok, true);
    let product = await client.scrape(scraped.url, { formats: ["json"], profile: name, waitSeconds: 60,
      schema: { type: "object", properties: { title: { type: "string" } } } });
    if (product.status === "pending") product = await client.waitForScrape(product.job_id);
    assert.equal(product.status, "completed");
    const extracted = await client.extract(scraped.job_id, { instruction: "The page title", profile: name });
    assert.ok("data" in extracted);
    assert.ok(Array.isArray((await client.aiUsage({ days: 1 })).totals));
  });
});

test("crawl into datasets, then inspect, query, diff, activate, search and quarantine", covers("POST /v1/crawls",
  "GET /v1/datasets", "GET /v1/datasets/{dataset_id}", "GET /v1/datasets/{dataset_id}/versions",
  "GET /v1/datasets/{dataset_id}/fields", "POST /v1/datasets/{dataset_id}/query", "GET /v1/datasets/{dataset_id}/diff",
  "POST /v1/datasets/{dataset_id}/active-version", "POST /v1/search", "GET /v1/documents/{document_id}",
  "PUT /v1/datasets/{dataset_id}/records/{record_id}/quarantine",
  "DELETE /v1/datasets/{dataset_id}/records/{record_id}/quarantine"), async (t) => {
  if (!need(t, "SCRAWL_LIVE_CRAWL_TARGET")) return;
  const { datasetId, versions: [older, newer] } = await dataset();
  const ids = [];
  for await (const item of client.paginate(client.listDatasets, { limit: 50 })) ids.push(item.dataset_id);
  assert.ok(ids.includes(datasetId));
  assert.equal((await client.getDataset(datasetId)).dataset.dataset_id, datasetId);
  const versionIds = [];
  for await (const version of client.paginate(client.listVersions, datasetId)) versionIds.push(version.version_id);
  assert.ok(versionIds.includes(older) && versionIds.includes(newer));
  const { fields } = await client.datasetFields(datasetId, { version: newer });
  assert.ok(fields.length > 0);
  const rows = await client.queryDataset(datasetId, [{ field: fields[0].path, op: "exists", value: true }],
    { versionId: newer, limit: 5 });
  assert.ok(rows.records.length > 0);
  const diff = await client.diffVersions(datasetId, older, newer);
  assert.ok("added" in diff.totals && "removed" in diff.totals && "changed" in diff.totals);
  assert.equal((await client.activateVersion(datasetId, older)).dataset.active_version_id, older);
  assert.equal((await client.activateVersion(datasetId, newer)).dataset.active_version_id, newer);
  const { results } = await client.search(rows.records[0].title || fields[0].path, { limit: 5 });
  if (results.length) assert.equal((await client.getDocument(results[0].id)).id, results[0].id);
  const recordId = rows.records[0].record_id;
  assert.equal((await client.quarantineRecord(datasetId, recordId, { reason: "live suite" })).quarantined, true);
  assert.equal((await client.releaseRecord(datasetId, recordId)).quarantined, false);
});

test("AI over datasets: extraction and cited answers", covers("POST /v1/datasets/{dataset_id}/extract",
  "POST /v1/ask"), async (t) => {
  if (!need(t, "SCRAWL_LIVE_CRAWL_TARGET", "SCRAWL_LIVE_AI_PROVIDER", "SCRAWL_LIVE_AI_API_KEY")) return;
  const { datasetId } = await dataset();
  await withProfile(async (name) => {
    const launch = await client.extractDataset(datasetId, { instruction: "The title of each record", profile: name,
      maxRecords: 5 });
    assert.equal(String((await client.waitForJob(launch.job_id, { timeoutMs: 900_000 })).status).toUpperCase(),
      "COMPLETED");
    const answer = await client.ask("What is in this dataset?", { datasetId, profile: name });
    assert.equal(typeof answer.answer, "string");
    assert.ok(Array.isArray(answer.citations));
  });
});

test("assets: quote, extract, list, download verified", covers("POST /v1/assets/quote", "POST /v1/assets",
  "GET /v1/assets/{job_id}", "GET /v1/assets/{job_id}/files/{asset_id}"), async (t) => {
  const values = need(t, "SCRAWL_LIVE_TARGET_URL", "SCRAWL_LIVE_ASSETS");
  if (!values) return;
  const quote = await client.quoteAssets(values[0], { classes: ["images", "documents"], maxItems: 5 });
  assert.equal(quote.egress_ready, true, "SCRAWL_LIVE_ASSETS=1 needs a key with usable egress");
  const job = await client.extractAssets(values[0], { classes: ["images", "documents"], maxItems: 5 });
  assert.equal((await client.waitForAssets(job.job_id, { timeoutMs: 600_000 })).status, "completed");
  for await (const asset of client.paginate(client.getAssets, job.job_id)) {
    const bytes = await client.downloadAsset(job.job_id, asset.asset_id);
    assert.equal(createHash("sha256").update(Buffer.from(bytes)).digest("hex"), asset.sha256);
    break;
  }
});

test("browser rendering (where the server enables it)", { skip }, async (t) => {
  const values = need(t, "SCRAWL_LIVE_TARGET_URL", "SCRAWL_LIVE_BROWSER");
  if (!values) return;
  let rendered = await client.scrape(values[0], { engine: "browser", waitSeconds: 60 });
  if (rendered.status === "pending") rendered = await client.waitForScrape(rendered.job_id, { engine: "browser" });
  assert.equal(rendered.engine, "browser");
});
