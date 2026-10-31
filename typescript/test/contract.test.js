// Contract gate, driven by the shared coverage.json and tools/check_contracts.py (the same checker the Python
// SDK and the backend's CI use): every ApexAPI operation is covered or excluded; each covered method, called
// with every option set, sends exactly the path, query parameters, body fields, enum values and Idempotency-Key
// that coverage.json declares, and all of them exist in the contract.

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { CONTRACT_DIGEST, Scrawl } from "../src/index.js";
import { asRecorded, checkContracts, checkRequests, COVERAGE, makeClient, REPO } from "./helpers.js";

const SCHEMA = { type: "object", properties: { name: { type: "string" } } };

// "METHOD path" -> arguments with every option set (path parameters first, in template order).
export const CALLS = {
  "POST /v1/scrape": ["https://e.example", { formats: ["markdown", "json"], schema: SCHEMA, instruction: "name",
    profile: "p", waitSeconds: 5, engine: "browser", waitForMs: 500, idempotencyKey: "key-1" }],
  "GET /v1/scrape/{job_id}/content": ["job1", { waitSeconds: 5, formats: ["markdown", "links"] }],
  "POST /v1/map": ["https://e.example", { limit: 50, waitSeconds: 5, engine: "browser", waitForMs: 500,
    idempotencyKey: "key-2" }],
  "POST /v1/scrape/batch": [["https://a.example"], { formats: ["json"], schema: SCHEMA, instruction: "i", profile: "p",
    engine: "browser", waitForMs: 500, idempotencyKey: "key-3" }],
  "GET /v1/scrape/batch/{batch_id}": ["b1", { waitSeconds: 5 }],
  "POST /v1/extract": ["job1", { artifact: "response.html", schema: SCHEMA, instruction: "i", profile: "p" }],
  "POST /v1/ask": ["why?", { datasetId: "d1", profile: "p" }],
  "GET /v1/ai/providers": [],
  "PUT /v1/ai/providers/{profile}": ["p", { provider: "example", apiKey: "sk-ai-test", model: "m",
    baseUrl: "https://ai.example" }],
  "DELETE /v1/ai/providers/{profile}": ["p"],
  "POST /v1/ai/providers/{profile}/default": ["p"],
  "POST /v1/ai/providers/{profile}/test": ["p"],
  "GET /v1/ai/usage": [{ days: 7 }],
  "POST /v1/crawls": ["target", { exportFormat: "jsonlines", maxItems: 10, maxSeconds: 60, idempotencyKey: "key-4" }],
  "GET /v1/jobs/{job_id}": ["job1", { waitSeconds: 5 }],
  "GET /v1/jobs": [{ limit: 5, status: "RUNNING", cursor: "c" }],
  "POST /v1/jobs/{job_id}/cancel": ["job1"],
  "GET /v1/artifacts/{job_id}": ["job1"],
  "GET /v1/artifacts/{job_id}/{filename}": ["job1", "response.html", { format: "markdown" }],
  "GET /v1/datasets": [{ limit: 5, cursor: "c" }],
  "GET /v1/datasets/{dataset_id}": ["d1"],
  "GET /v1/datasets/{dataset_id}/versions": ["d1", { limit: 5, cursor: "c", status: "completed" }],
  "POST /v1/datasets/{dataset_id}/active-version": ["d1", "v1"],
  "GET /v1/datasets/{dataset_id}/diff": ["d1", "v1", "v2", { limit: 5, cursor: "c" }],
  "GET /v1/datasets/{dataset_id}/fields": ["d1", { version: "v1" }],
  "POST /v1/datasets/{dataset_id}/query": ["d1", [{ field: "price", op: "lt", value: 20 }],
    { versionId: "v1", limit: 5, cursor: "c" }],
  "POST /v1/datasets/{dataset_id}/extract": ["d1", { schema: SCHEMA, instruction: "i", profile: "p", versionId: "v1",
    maxRecords: 10, idempotencyKey: "key-5" }],
  "PUT /v1/datasets/{dataset_id}/records/{record_id}/quarantine": ["d1", "r1", { reason: "spam" }],
  "DELETE /v1/datasets/{dataset_id}/records/{record_id}/quarantine": ["d1", "r1"],
  "POST /v1/search": ["lantern", { limit: 5 }],
  "GET /v1/documents/{document_id}": ["doc1"],
  "GET /v1/credits/balance": [],
  "GET /v1/health": [],
  "POST /v1/assets": ["https://e.example/page", { classes: ["images", "video"], maxItems: 10, maxBytes: 1000000,
    maxCredits: 50, idempotencyKey: "key-6" }],
  "POST /v1/assets/quote": ["https://e.example/page", { classes: ["documents"], maxItems: 10, maxBytes: 1000000,
    maxCredits: 50 }],
  "GET /v1/assets/{job_id}": ["job1", { view: "skipped", limit: 50, cursor: "c", waitSeconds: 5 }],
  "GET /v1/assets/{job_id}/files/{asset_id}": ["job1", "0123456789abcdef01234567"],
};

const COVERED = Object.fromEntries(Object.entries(COVERAGE.operations).filter(([, entry]) => !("excluded" in entry)));

test("every operation is covered or excluded, and every declaration holds (shared checker)", () => {
  const result = checkContracts("coverage");
  assert.equal(result.status, 0, result.stderr);
});

test("the TypeScript calls table covers exactly the covered operations", () => {
  assert.deepEqual(Object.keys(CALLS).sort(), Object.keys(COVERED).sort());
  for (const [route, entry] of Object.entries(COVERED)) {
    assert.equal(typeof Scrawl.prototype[entry.typescript], "function", `${route}: no Scrawl.${entry.typescript}`);
  }
});

test("each method sends exactly what coverage.json declares", async () => {
  const recorded = [];
  for (const [route, entry] of Object.entries(COVERED)) {
    const args = CALLS[route];
    const { client, fetch } = makeClient([{ body: {} }]);
    await client[entry.typescript](...structuredClone(args));
    assert.equal(fetch.calls.length, 1, route);
    const call = asRecorded(fetch.calls[0]);
    // Path parameters are the method's leading arguments, in template order: the exact path, not a pattern.
    let index = 0;
    const template = route.split(" ")[1];
    assert.equal(call.path, template.replace(/\{[^}]+\}/g, () => encodeURIComponent(args[index++])), route);
    recorded.push({ route, request: call, exact: true });
  }
  const result = checkRequests(recorded);
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, new RegExp(`requests ok: ${recorded.length} checked`));
});

test("the SDK records the digest of the contract bundle it was built against", () => {
  const manifest = JSON.parse(readFileSync(join(REPO, "contracts", "MANIFEST.json"), "utf8"));
  assert.equal(CONTRACT_DIGEST, manifest.digest);
  const result = checkContracts("manifest");
  assert.equal(result.status, 0, result.stderr);
});

test("the live suite exercises every covered operation", () => {
  const source = readFileSync(new URL("./live/live.test.js", import.meta.url), "utf8");
  const named = new Set();
  for (const [, args] of source.matchAll(/covers\(([^)]*)\)/g)) {
    for (const [, route] of args.matchAll(/"([A-Z]+ \/[^"]+)"/g)) named.add(route);
  }
  const covered = Object.keys(COVERED);
  assert.deepEqual([...named].sort(), covered.sort());
});
