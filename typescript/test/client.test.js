import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { inspect } from "node:util";

import {
  APIConnectionError, APITimeoutError, AuthenticationError, BadRequestError, ConfigurationError, ConflictError, NotFoundError,
  PaymentRequiredError, PermissionDeniedError, RateLimitError, Scrawl, ScrawlError, ServerError, VERSION, ValidationError,
} from "../src/index.js";
import { makeClient, mockFetch } from "./helpers.js";

const PENDING = { status: 202, body: { job_id: "j1", status: "pending", url: "https://e.example" } };
const DONE = { body: { job_id: "j1", status: "completed", url: "https://e.example", markdown: "# Hi" } };

test("scrape sends defaults, auth, user agent and a generated idempotency key", async () => {
  const { client, fetch } = makeClient([DONE]);
  const result = await client.scrape("https://e.example");
  assert.equal(result.markdown, "# Hi");
  const call = fetch.calls[0];
  assert.equal(call.url.href, "https://api.test/v1/scrape");
  assert.deepEqual(call.body, { url: "https://e.example", formats: ["markdown"], wait_seconds: 30 });
  assert.equal(call.headers.Authorization, "Bearer sk_test_key");
  assert.equal(call.headers["User-Agent"], `scrawl-ts/${VERSION}`);
  assert.equal(call.headers["Content-Type"], "application/json");
  assert.match(call.headers["Idempotency-Key"], /^[0-9a-f]{32}$/);
});

test("a 202 pending scrape is a result, not an error", async () => {
  const { client } = makeClient([PENDING]);
  const result = await client.scrape("https://e.example", { waitSeconds: 0 });
  assert.equal(result.status, "pending");
  assert.equal(result.job_id, "j1");
});

test("query values are encoded and empty options are not sent", async () => {
  const { client, fetch } = makeClient([DONE]);
  await client.scrapeResult("a/b c", { formats: ["markdown", "links"] });
  await client.getJob("j1");
  assert.equal(fetch.calls[0].url.pathname, "/v1/scrape/a%2Fb%20c/content");
  assert.equal(fetch.calls[0].url.search, "?formats=markdown%2Clinks");
  assert.equal(fetch.calls[1].url.search, "");
});

test("ids that would walk to another route are refused before any request", async () => {
  const { client, fetch } = makeClient([DONE]);
  for (const bad of ["..", ".", ""]) {
    await assert.rejects(() => client.getJob(bad), ScrawlError);
  }
  await assert.rejects(() => client.downloadArtifact("j1", ".."), ScrawlError);
  assert.equal(fetch.calls.length, 0);
});

test("waitForScrape uses server-side waits until the job settles", async () => {
  const { client, fetch } = makeClient([PENDING, PENDING, DONE]);
  const result = await client.waitForScrape("j1", { timeoutMs: 120_000 });
  assert.equal(result.status, "completed");
  assert.equal(fetch.calls.length, 3);
  for (const call of fetch.calls) {
    const wait = Number(call.url.searchParams.get("wait_seconds"));
    assert.ok(wait >= 1 && wait <= 60, `wait_seconds ${wait}`);
  }
});

test("waitForScrape returns the pending result at its deadline", async () => {
  const { client } = makeClient([PENDING]);
  const result = await client.waitForScrape("j1", { timeoutMs: 0 });
  assert.equal(result.status, "pending");
});

test("waitForBatch polls until every item settled", async () => {
  const running = { body: { batch_id: "b1", status: "running", total: 2, items: [] } };
  const completed = { body: { batch_id: "b1", status: "completed", total: 2, counts: { completed: 2 }, items: [] } };
  const { client, fetch } = makeClient([running, completed]);
  const status = await client.waitForBatch("b1");
  assert.equal(status.status, "completed");
  assert.equal(fetch.calls.length, 2);
  assert.equal(fetch.calls[0].url.pathname, "/v1/scrape/batch/b1");
});

test("paginate follows next_cursor and keeps positional arguments and options", async () => {
  const { client, fetch } = makeClient([
    { body: { versions: [{ version_id: "v3" }, { version_id: "v2" }], next_cursor: "c2" } },
    { body: { versions: [{ version_id: "v1" }], next_cursor: null } },
  ]);
  const seen = [];
  for await (const version of client.paginate(client.listVersions, "d1", { limit: 2 })) seen.push(version.version_id);
  assert.deepEqual(seen, ["v3", "v2", "v1"]);
  assert.equal(fetch.calls[0].url.search, "?limit=2");
  assert.equal(fetch.calls[1].url.search, "?limit=2&cursor=c2");
  assert.ok(fetch.calls.every((call) => call.url.pathname === "/v1/datasets/d1/versions"));
});

test("paginate works for methods without positional arguments and for query bodies", async () => {
  const { client, fetch } = makeClient([
    { body: { records: [{ id: 1 }], next_cursor: "n" } }, { body: { records: [{ id: 2 }] } },
  ]);
  const filters = [{ field: "price", op: "lt", value: 20 }];
  const ids = [];
  for await (const record of client.paginate(client.queryDataset, "d1", filters)) ids.push(record.id);
  assert.deepEqual(ids, [1, 2]);
  assert.deepEqual(fetch.calls[1].body, { filters, cursor: "n" });

  const { client: other } = makeClient([{ body: { datasets: [{ dataset_id: "a" }] } }]);
  const all = [];
  for await (const dataset of other.paginate(other.listDatasets)) all.push(dataset.dataset_id);
  assert.deepEqual(all, ["a"]);
});

test("errors map to typed classes with the API's code, message and request id", async () => {
  const cases = [
    [401, AuthenticationError], [402, PaymentRequiredError], [403, PermissionDeniedError], [404, NotFoundError], [409, ConflictError],
    [422, ValidationError], [429, RateLimitError], [500, ServerError], [400, BadRequestError], [418, ScrawlError],
  ];
  for (const [status, Cls] of cases) {
    const { client } = makeClient([{ status, body: { error: { code: `c${status}`, message: `m${status}` } },
      headers: { "X-Request-ID": "req-1" } }], { maxRetries: 0 });
    const error = await client.getDataset("d1").then(() => null, (exc) => exc);
    assert.ok(error instanceof Cls, `${status} -> ${error?.name}`);
    assert.ok(error instanceof ScrawlError);
    assert.equal(error.status, status);
    assert.equal(error.code, `c${status}`);
    assert.equal(error.message, `m${status}`);
    assert.equal(error.requestId, "req-1");
    assert.equal(error.name, Cls.name);
    assert.match(String(error), new RegExp(`\\[c${status}\\] m${status} \\(request req-1\\)`));
  }
});

test("legacy and non-JSON error bodies still map cleanly", async () => {
  const { client } = makeClient([{ status: 422, body: { detail: [{ loc: ["body", "url"], msg: "bad" }] } }]);
  const invalid = await client.getDataset("d1").catch((exc) => exc);
  assert.ok(invalid instanceof ValidationError);
  assert.deepEqual(invalid.details, [{ loc: ["body", "url"], msg: "bad" }]);
  assert.equal(invalid.message, "HTTP 422");

  const { client: html } = makeClient([{ status: 502, body: "<html>bad gateway</html>" }], { maxRetries: 0 });
  const gateway = await html.getDataset("d1").catch((exc) => exc);
  assert.ok(gateway instanceof ServerError);
  assert.equal(gateway.message, "<html>bad gateway</html>");

  const { client: envelope } = makeClient([{ status: 404, body: { error: { code: "not_found", message: "no",
    request_id: "from-body" } } }]);
  assert.equal((await envelope.getJob("x").catch((exc) => exc)).requestId, "from-body");
});

test("a 429 carries Retry-After and the retry waits that long", async () => {
  const limited = { status: 429, body: { error: { code: "too_many_active_jobs", message: "slow down" } },
    headers: { "Retry-After": "5" } };
  const { client, fetch, sleeps } = makeClient([limited, limited, limited]);
  const error = await client.scrape("https://e.example").catch((exc) => exc);
  assert.ok(error instanceof RateLimitError);
  assert.equal(error.code, "too_many_active_jobs");
  assert.equal(error.retryAfter, 5);
  assert.equal(fetch.calls.length, 3);                       // 1 + maxRetries
  assert.deepEqual(sleeps, [5000, 5000]);
  const keys = new Set(fetch.calls.map((call) => call.headers["Idempotency-Key"]));
  assert.equal(keys.size, 1, "a retry reuses the same Idempotency-Key");
});

test("idempotent submits and GETs retry 5xx and network errors with backoff", async () => {
  const { client, fetch, sleeps } = makeClient([{ status: 503, body: {} }, new TypeError("fetch failed"), DONE]);
  const result = await client.map("https://e.example", { idempotencyKey: "mine" });
  assert.equal(result.status, "completed");
  assert.equal(fetch.calls.length, 3);
  assert.ok(fetch.calls.every((call) => call.headers["Idempotency-Key"] === "mine"));
  assert.equal(sleeps.length, 2);
  assert.ok(sleeps[0] >= 500 && sleeps[0] < 750 && sleeps[1] >= 1000 && sleeps[1] < 1250, String(sleeps));

  const { client: reader, fetch: readerFetch } = makeClient([new TypeError("fetch failed"), { body: { jobs: [] } }]);
  await reader.listJobs();
  assert.equal(readerFetch.calls.length, 2);
});

test("a POST without an Idempotency-Key, other 4xx and exhausted retries are not retried", async () => {
  const { client: extract, fetch: extractFetch } = makeClient([{ status: 503, body: {} }]);
  await assert.rejects(() => extract.extract("j1"), ServerError);
  assert.equal(extractFetch.calls.length, 1);
  assert.equal(extractFetch.calls[0].headers["Idempotency-Key"], undefined);

  const { client: network, fetch: networkFetch } = makeClient([new TypeError("fetch failed")]);
  await assert.rejects(() => network.search("q"), APIConnectionError);
  assert.equal(networkFetch.calls.length, 1);

  for (const status of [400, 404, 422]) {
    const { client, fetch } = makeClient([{ status, body: {} }]);
    await assert.rejects(() => client.scrape("https://e.example"), ScrawlError);
    assert.equal(fetch.calls.length, 1, `status ${status}`);
  }
  const { client: unkeyed, fetch: unkeyedFetch } = makeClient([{ status: 409, body: {} }]);
  await assert.rejects(() => unkeyed.activateVersion("d1", "v1"), ConflictError);
  assert.equal(unkeyedFetch.calls.length, 1);

  const { client: none, fetch: noneFetch } = makeClient([{ status: 503, body: {} }], { maxRetries: 0 });
  await assert.rejects(() => none.scrape("https://e.example"), ServerError);
  assert.equal(noneFetch.calls.length, 1);
});

test("a timeout is an APITimeoutError", async () => {
  const hang = (_url, init) => new Promise((_, reject) => {
    const socket = setTimeout(() => {}, 10_000);          // what an open connection does to the event loop
    init.signal.addEventListener("abort", () => { clearTimeout(socket); reject(init.signal.reason); });
  });
  const client = new Scrawl({ apiKey: "k", baseUrl: "https://api.test", timeoutMs: 20, maxRetries: 0, fetch: mockFetch([hang]) });
  const error = await client.getJob("j1").catch((exc) => exc);
  assert.ok(error instanceof APITimeoutError && error instanceof APIConnectionError, String(error));
});

test("the API key comes from options or SCRAWL_API_KEY, is required lazily and never printed", async () => {
  const saved = { key: process.env.SCRAWL_API_KEY, url: process.env.SCRAWL_BASE_URL };
  try {
    delete process.env.SCRAWL_API_KEY;
    process.env.SCRAWL_BASE_URL = "https://scrawl.example/";
    const fetch = mockFetch([{ body: { status: "ok" } }]);
    const anonymous = new Scrawl({ fetch });
    assert.equal(anonymous.baseUrl, "https://scrawl.example");
    assert.deepEqual(await anonymous.health(), { status: "ok" });            // health needs no key
    await assert.rejects(() => anonymous.listJobs(), (error) => error instanceof ConfigurationError && /No API key/.test(error.message));
    assert.equal(fetch.calls.length, 1);

    process.env.SCRAWL_API_KEY = "sk_from_env_secret";
    const fromEnv = new Scrawl({ fetch });
    await fromEnv.creditBalance();
    assert.equal(fetch.calls.at(-1).headers.Authorization, "Bearer sk_from_env_secret");
    const quiet = new Scrawl({ fetch: async () => new Response("{}") });     // a fetch that records nothing
    await quiet.creditBalance();
    for (const text of [inspect(quiet, { showHidden: true, depth: 8 }), JSON.stringify(quiet), String(Object.keys(quiet))]) {
      assert.ok(!text.includes("sk_from_env_secret"), "the key leaked into a printable form of the client");
    }
  } finally {
    for (const [name, value] of [["SCRAWL_API_KEY", saved.key], ["SCRAWL_BASE_URL", saved.url]]) {
      if (value === undefined) delete process.env[name]; else process.env[name] = value;
    }
  }
});

test("downloadArtifact returns the bytes; DELETE with 204 returns null", async () => {
  const bytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);
  const { client } = makeClient([{ body: bytes, headers: { "Content-Type": "image/png" } }, { status: 204 }]);
  const data = await client.downloadArtifact("j1", "shot.png");
  assert.ok(data instanceof ArrayBuffer);
  assert.deepEqual(new Uint8Array(data), bytes);
  assert.equal(await client.deleteAiProvider("p"), null);
});

test("a success body that is not JSON is a clear error", async () => {
  const { client } = makeClient([{ body: "<html>proxy login</html>" }]);
  const error = await client.getDataset("d1").catch((exc) => exc);
  assert.ok(error instanceof ScrawlError);
  assert.match(error.message, /not JSON/);
});

test("the package version matches the SDK's", () => {
  const pkg = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));
  assert.equal(pkg.version, VERSION);
  assert.equal(pkg.type, "module");
  assert.deepEqual(Object.keys(pkg.dependencies ?? {}), [], "the SDK has no runtime dependencies");
});

test("a keyed retry that meets its still-running first attempt (409) waits for the stored response", async () => {
  const conflict = { status: 409, body: { error: { code: "conflict", message: "still in progress" } } };
  const { client, fetch, sleeps } = makeClient([new TypeError("socket hang up"), conflict, conflict, DONE]);
  const result = await client.scrape("https://e.example", { waitSeconds: 10 });
  assert.equal(result.status, "completed");
  assert.equal(fetch.calls.length, 4);
  assert.equal(new Set(fetch.calls.map((call) => call.headers["Idempotency-Key"])).size, 1);
  assert.ok(sleeps.slice(1).every((ms) => ms >= 1000), String(sleeps));
});

test("Scrawl's own 5xx on a keyed submit is final; a proxy's 5xx is retried; GETs retry both", async () => {
  const aiDown = { status: 502, body: { error: { code: "ai_provider_error", message: "provider timed out" } } };
  const { client, fetch } = makeClient([aiDown, DONE]);
  const error = await client.scrape("https://e.example", { formats: ["json"] }).catch((exc) => exc);
  assert.ok(error instanceof ServerError);
  assert.equal(error.code, "ai_provider_error");          // the actionable error, not a replayed generic 500
  assert.equal(fetch.calls.length, 1);

  const { client: viaProxy, fetch: proxyFetch } = makeClient([{ status: 502, body: "<html>Bad Gateway</html>" }, DONE]);
  assert.equal((await viaProxy.scrape("https://e.example")).status, "completed");
  assert.equal(proxyFetch.calls.length, 2);

  // A GET retries Scrawl's own 5xx when its code is retryable or unknown.
  const { client: reader, fetch: readerFetch } = makeClient([{ status: 503, body: { error: { code: "a_code_added_later",
    message: "x" } } }, DONE]);
  await reader.getJob("j1");
  assert.equal(readerFetch.calls.length, 2);
});

test("a code the catalogue marks not retryable is never retried, whatever the status", async () => {
  // A resend after these may charge twice or start a second job.
  for (const code of ["submission_failed", "settlement_failed", "internal_error", "unavailable"]) {
    for (const status of [409, 429, 500, 502, 503, 504]) {
      for (const body of [{ error: { code, message: "list your jobs first" } }, { detail: "x", code }]) {
        for (const call of [(c) => c.getJob("j1"), (c) => c.scrape("https://e.example")]) {
          const { client, fetch, sleeps } = makeClient([{ status, body }, DONE]);
          const error = await call(client).catch((exc) => exc);
          assert.ok(error instanceof ScrawlError, `${code} ${status}: ${error}`);
          assert.equal(error.code, code);
          assert.equal(fetch.calls.length, 1, `${code} ${status} ${JSON.stringify(body)}`);
          assert.deepEqual(sleeps, []);
        }
      }
    }
  }
});

test("GETs retry a 5xx only when its code is retryable or unknown", async () => {
  for (const [code, status, attempts] of [["ai_auth", 502, 1], ["browser_unavailable", 503, 1], ["unavailable", 503, 1],
    ["internal_error", 500, 1], ["ai_timeout", 502, 2], ["a_code_added_later", 503, 2]]) {
    const { client, fetch } = makeClient([{ status, body: { error: { code, message: "x" } } }, DONE]);
    const outcome = await client.getJob("j1").catch((exc) => exc);
    if (attempts === 1) assert.ok(outcome instanceof ServerError, `${code}: ${outcome}`);
    else assert.equal(outcome.status, "completed", code);
    assert.equal(fetch.calls.length, attempts, code);
  }
});

test("a 503 without a known code retries only where the status rule allows", async () => {
  // No code (a proxy's page, an empty body) or a code this SDK does not know: the status rule decides.
  for (const body of ["<html>Service Unavailable</html>", "", { detail: "Service Unavailable" }]) {
    const get = makeClient([{ status: 503, body }, DONE]);
    assert.equal((await get.client.getJob("j1")).status, "completed");
    assert.equal(get.fetch.calls.length, 2, `GET ${JSON.stringify(body)}`);
    const keyed = makeClient([{ status: 503, body }, DONE]);
    assert.equal((await keyed.client.scrape("https://e.example")).status, "completed");
    assert.equal(keyed.fetch.calls.length, 2, `keyed submit ${JSON.stringify(body)}`);
    const plain = makeClient([{ status: 503, body }, DONE]);
    assert.ok((await plain.client.extract("j1", { instruction: "x" }).catch((exc) => exc)) instanceof ServerError);
    assert.equal(plain.fetch.calls.length, 1, `plain POST ${JSON.stringify(body)}`);
  }
  const later = { status: 503, body: { error: { code: "a_code_added_later", message: "x" } } };
  const get = makeClient([later, DONE]);
  assert.equal((await get.client.getJob("j1")).status, "completed");
  assert.equal(get.fetch.calls.length, 2);
  const keyed = makeClient([later, DONE]);
  assert.ok((await keyed.client.scrape("https://e.example").catch((exc) => exc)) instanceof ServerError);
  assert.equal(keyed.fetch.calls.length, 1, "Scrawl's own 5xx on a keyed submit stays final");
});

test("a failed body read keeps the HTTP status (no retry of 4xx, Retry-After honoured)", async () => {
  const brokenBody = (status, headers = {}) => () => new Response(new ReadableStream({
    start(controller) { controller.error(new TypeError("terminated")); },
  }), { status, headers });
  const { client, fetch } = makeClient([brokenBody(422)]);
  const invalid = await client.scrape("https://e.example").catch((exc) => exc);
  assert.ok(invalid instanceof ValidationError, String(invalid));
  assert.equal(fetch.calls.length, 1);

  const { client: limited, sleeps } = makeClient([brokenBody(429, { "Retry-After": "7" }), DONE]);
  await limited.scrape("https://e.example");
  assert.deepEqual(sleeps, [7000]);

  const { client: reader, fetch: readerFetch } = makeClient([brokenBody(200), DONE]);
  await reader.getJob("j1");                                 // a 2xx whose body broke is a network error
  assert.equal(readerFetch.calls.length, 2);
});

test("a body that cannot be serialized fails at once and is not retried", async () => {
  const { client, fetch } = makeClient([DONE]);
  const cyclic = {};
  cyclic.self = cyclic;
  await assert.rejects(() => client.scrape("https://e.example", { schema: cyclic }), TypeError);
  assert.equal(fetch.calls.length, 0);
});

test("server-side waits finish inside the request timeout", async () => {
  const { client, fetch } = makeClient([PENDING, DONE], { timeoutMs: 20_000 });
  await client.scrape("https://e.example");                  // default waitSeconds 30
  assert.equal(fetch.calls[0].body.wait_seconds, 15);
  await client.waitForScrape("j1");
  assert.equal(fetch.calls[1].url.searchParams.get("wait_seconds"), "15");
  const { client: tiny, fetch: tinyFetch } = makeClient([DONE], { timeoutMs: 2_000 });
  await tiny.getJob("j1", { waitSeconds: 60 });
  assert.equal(tinyFetch.calls[0].url.searchParams.get("wait_seconds"), "1");
});

test("the API key is never sent over plain HTTP to a remote host", async () => {
  const fetch = mockFetch([DONE]);
  for (const baseUrl of ["http://scrawl-lan.test:8088", "http://192.0.2.5", "http://scrawl.example"]) {
    assert.throws(() => new Scrawl({ apiKey: "k", baseUrl, fetch }), (error) => error instanceof ConfigurationError && /plain HTTP/.test(error.message));
  }
  for (const baseUrl of ["http://127.0.0.1:8088", "http://localhost:8088", "http://[::1]:8088", "http://api.localhost",
    "https://scrawl.example"]) {
    assert.doesNotThrow(() => new Scrawl({ apiKey: "k", baseUrl, fetch }), baseUrl);
  }
  assert.doesNotThrow(() => new Scrawl({ apiKey: "k", baseUrl: "http://scrawl-lan.test", fetch, allowInsecureHttp: true }));
  assert.throws(() => new Scrawl({ apiKey: "k", baseUrl: "ftp://scrawl.example", fetch }), /http\(s\)/);
  assert.throws(() => new Scrawl({ apiKey: "k", baseUrl: "not a url", fetch }), /Invalid base URL/);
  const saved = process.env.SCRAWL_ALLOW_INSECURE_HTTP;
  try {
    process.env.SCRAWL_ALLOW_INSECURE_HTTP = "1";
    assert.doesNotThrow(() => new Scrawl({ apiKey: "k", baseUrl: "http://scrawl-lan.test", fetch }));
  } finally {
    if (saved === undefined) delete process.env.SCRAWL_ALLOW_INSECURE_HTTP; else process.env.SCRAWL_ALLOW_INSECURE_HTTP = saved;
  }
});

const assetResult = (status, extra = {}) => ({ body: { job_id: "aj1", status, url: "https://e.example/page",
  classes: ["images"], partial: false, view: "assets", assets: [], skipped: null, next_cursor: null, ...extra } });

test("waitForAssets polls with server-side waits until the asset job settles", async () => {
  const { client, fetch } = makeClient([assetResult("pending"), assetResult("running"), assetResult("completed")]);
  const result = await client.waitForAssets("aj1");
  assert.equal(result.status, "completed");
  assert.equal(fetch.calls.length, 3);
  for (const call of fetch.calls) {
    assert.equal(call.url.pathname, "/v1/assets/aj1");
    assert.equal(call.url.searchParams.get("wait_seconds"), "60");
  }
  for (const status of ["failed", "cancelled", "orphaned"]) {
    const { client: settled, fetch: settledFetch } = makeClient([assetResult(status), assetResult("completed")]);
    assert.equal((await settled.waitForAssets("aj1")).status, status);
    assert.equal(settledFetch.calls.length, 1);
  }
  const { client: slow, fetch: slowFetch } = makeClient([assetResult("running")]);
  assert.equal((await slow.waitForAssets("aj1", { timeoutMs: 0 })).status, "running");   // the deadline
  assert.equal(slowFetch.calls.length, 1);
});

test("downloadAsset returns the raw bytes as an ArrayBuffer", async () => {
  const bytes = new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x00, 0xff]);
  const { client, fetch } = makeClient([{ body: bytes, headers: { "Content-Type": "application/octet-stream",
    "X-Asset-SHA256": "ab".repeat(32), "X-Untrusted-External-Content": "true" } }]);
  const data = await client.downloadAsset("aj1", "0123456789abcdef01234567");
  assert.ok(data instanceof ArrayBuffer);
  assert.deepEqual(new Uint8Array(data), bytes);
  assert.equal(fetch.calls[0].url.pathname, "/v1/assets/aj1/files/0123456789abcdef01234567");
  assert.equal(fetch.calls[0].headers["Idempotency-Key"], undefined);
  await assert.rejects(() => client.downloadAsset("aj1", ".."), ScrawlError);
  assert.equal(fetch.calls.length, 1);
});

test("extractAssets is keyed and retried with its key; quoteAssets is never retried", async () => {
  const job = { status: 202, body: { job_id: "aj1", status: "pending", url: "https://e.example/page" } };
  const { client, fetch } = makeClient([{ status: 503, body: "<html>proxy</html>" }, job]);
  assert.equal((await client.extractAssets("https://e.example/page")).job_id, "aj1");
  assert.equal(fetch.calls.length, 2);
  assert.deepEqual(fetch.calls[0].body, { url: "https://e.example/page" });   // server defaults otherwise
  assert.match(fetch.calls[0].headers["Idempotency-Key"], /^[0-9a-f]{32}$/);
  assert.equal(fetch.calls[0].headers["Idempotency-Key"], fetch.calls[1].headers["Idempotency-Key"]);

  const { client: quoter, fetch: quoteFetch } = makeClient([{ status: 503, body: "<html>proxy</html>" }, { body: {} }]);
  await assert.rejects(() => quoter.quoteAssets("https://e.example/page", { classes: ["documents"] }), ServerError);
  assert.equal(quoteFetch.calls.length, 1);
  assert.equal(quoteFetch.calls[0].url.pathname, "/v1/assets/quote");
  assert.equal(quoteFetch.calls[0].headers["Idempotency-Key"], undefined);
});

test("paginate iterates the requested asset view", async () => {
  const skipped = (url) => ({ url, reason: "ARCHIVE_DEFERRED", detail: "", asset_class: null, bytes_received: 0 });
  const { client, fetch } = makeClient([
    assetResult("completed", { view: "skipped", assets: null, skipped: [skipped("a.zip")], next_cursor: "c1" }),
    assetResult("completed", { view: "skipped", assets: null, skipped: [skipped("b.zip")] }),
  ]);
  const urls = [];
  for await (const item of client.paginate(client.getAssets, "aj1", { view: "skipped" })) urls.push(item.url);
  assert.deepEqual(urls, ["a.zip", "b.zip"]);
  assert.equal(fetch.calls[0].url.search, "?view=skipped");
  assert.equal(fetch.calls[1].url.search, "?view=skipped&cursor=c1");
});

// -- the browser engine option and its downgrade guard --------------------------------------------------

test("engine options are sent only when set", async () => {
  const { client, fetch } = makeClient([{ body: { status: "completed", engine: "static" } }]);
  await client.scrape("https://e.example");
  await client.map("https://e.example");
  await client.batchScrape(["https://e.example"]);
  for (const call of fetch.calls) {
    assert.ok(!("engine" in call.body) && !("wait_for_ms" in call.body), JSON.stringify(call.body));
  }
  const browser = makeClient([{ body: { status: "completed", engine: "browser" } }]);
  await browser.client.scrape("https://e.example", { engine: "browser", waitForMs: 750 });
  await browser.client.map("https://e.example", { engine: "browser" });
  await browser.client.batchScrape(["https://e.example"], { engine: "browser", waitForMs: 0 });
  const [scrape, map, batch] = browser.fetch.calls.map((call) => call.body);
  assert.deepEqual([scrape.engine, scrape.wait_for_ms, map.engine, batch.engine, batch.wait_for_ms],
    ["browser", 750, "browser", "browser", 0]);
  assert.ok(!("wait_for_ms" in map));
});

test("a downgraded finished result throws render_not_supported on scrape and map", async () => {
  for (const status of ["completed", "failed"]) {
    for (const echo of [{ engine: "static" }, {}]) {
      for (const call of [(c) => c.scrape("https://e.example", { engine: "browser" }),
                          (c) => c.map("https://e.example", { engine: "browser" })]) {
        const { client } = makeClient([{ body: { status, ...echo } }]);
        await assert.rejects(call(client), (error) => error instanceof ScrawlError && error.code === "render_not_supported");
      }
    }
  }
});

test("the guard passes a browser echo, a pending result and static requests", async () => {
  const { client } = makeClient([{ body: { status: "completed", engine: "browser", final_url: "https://e.example/x",
    browser: { settle: "network_quiet" } } }]);
  const page = await client.scrape("https://e.example", { engine: "browser" });
  assert.deepEqual([page.engine, page.final_url, page.browser.settle], ["browser", "https://e.example/x", "network_quiet"]);
  const pending = makeClient([{ body: { status: "pending", job_id: "j" } }]);
  assert.equal((await pending.client.scrape("https://e.example", { engine: "browser" })).status, "pending");
  const plain = makeClient([{ body: { status: "completed" } }]);
  assert.equal((await plain.client.scrape("https://e.example")).status, "completed");
});

test("the guard covers the pending-then-poll path", async () => {
  const { client } = makeClient([{ status: 202, body: { job_id: "j1", status: "pending" } },
    { body: { job_id: "j1", status: "completed", engine: "static" } }]);
  assert.equal((await client.scrape("https://e.example", { engine: "browser", waitSeconds: 0 })).status, "pending");
  await assert.rejects(client.waitForScrape("j1", { timeoutMs: 5000, engine: "browser" }),
    (error) => error instanceof ScrawlError && error.code === "render_not_supported");
  const direct = makeClient([{ body: { job_id: "j1", status: "completed", engine: "static" } }]);
  await assert.rejects(direct.client.scrapeResult("j1", { engine: "browser" }),
    (error) => error.code === "render_not_supported");
  const plain = makeClient([{ body: { job_id: "j1", status: "completed", engine: "static" } }]);
  assert.equal((await plain.client.scrapeResult("j1")).status, "completed");
  assert.ok(!direct.fetch.calls[0].url.searchParams.has("engine"));   // client-side only: never a query parameter
});

test("without a base URL the client talks to this machine only (no hard-coded remote host)", () => {
  const saved = process.env.SCRAWL_BASE_URL;
  try {
    delete process.env.SCRAWL_BASE_URL;
    assert.equal(new Scrawl({ apiKey: "k", fetch: mockFetch([DONE]) }).baseUrl, "http://127.0.0.1:8088");
    process.env.SCRAWL_BASE_URL = "https://scrawl.example/";
    assert.equal(new Scrawl({ apiKey: "k", fetch: mockFetch([DONE]) }).baseUrl, "https://scrawl.example");
  } finally {
    if (saved === undefined) delete process.env.SCRAWL_BASE_URL; else process.env.SCRAWL_BASE_URL = saved;
  }
});

test("waitForJob follows a job until it leaves PENDING or RUNNING", async () => {
  const job = (status) => ({ body: { job_id: "c1", command: "crawl", args: [], status, engine_id: "e",
    artifacts_url: "", result_url: "" } });
  const { client, fetch } = makeClient([job("PENDING"), job("RUNNING"), job("COMPLETED")]);
  assert.equal((await client.waitForJob("c1")).status, "COMPLETED");
  assert.equal(fetch.calls.length, 3);
  for (const call of fetch.calls) {
    assert.equal(call.url.pathname, "/v1/jobs/c1");
    assert.equal(call.url.searchParams.get("wait_seconds"), "60");
  }
  for (const status of ["FAILED", "CANCELLED", "ORPHANED"]) {
    const settled = makeClient([job(status), job("COMPLETED")]);
    assert.equal((await settled.client.waitForJob("c1")).status, status);
    assert.equal(settled.fetch.calls.length, 1);
  }
  const slow = makeClient([job("RUNNING")]);
  assert.equal((await slow.client.waitForJob("c1", { timeoutMs: 0 })).status, "RUNNING");
  assert.equal(slow.fetch.calls.length, 1);
});

// -- the API key never reaches an error message -------------------------------------------------------

const SECRET = "sk-live-secret-0123456789";

test("a key with surrounding whitespace (a file, a CRLF .env) is trimmed before it is sent", async () => {
  for (const raw of [`${SECRET}\n`, `${SECRET}\r\n`, `  ${SECRET}\t`]) {
    const { client, fetch } = makeClient([{ body: { jobs: [] } }], { apiKey: raw });
    await client.listJobs();
    assert.equal(fetch.calls[0].headers.Authorization, `Bearer ${SECRET}`);
  }
});

test("a key an HTTP header cannot carry is a ConfigurationError that never shows it", async () => {
  for (const bad of [`${SECRET.slice(0, 8)}\n${SECRET.slice(8)}`, `${SECRET.slice(0, 8)}\u0000${SECRET.slice(8)}`,
    `${SECRET.slice(0, 8)} ${SECRET.slice(8)}`, `${SECRET.slice(0, 8)}é${SECRET.slice(8)}`]) {
    const { client, fetch } = makeClient([{ body: {} }], { apiKey: bad });
    const error = await client.listJobs().catch((exc) => exc);
    assert.ok(error instanceof ConfigurationError, String(error));
    assert.ok(!String(error).includes(SECRET.slice(8)) && /SCRAWL_API_KEY/.test(error.message), String(error));
    assert.equal(fetch.calls.length, 0);
  }
});

test("a malformed key never leaks through the real fetch's error", async () => {
  // undici refuses an illegal header value and quotes it: that text must not reach the caller.
  const client = new Scrawl({ apiKey: `${SECRET.slice(0, 8)}\u0000${SECRET.slice(8)}`, baseUrl: "http://127.0.0.1:9",
    maxRetries: 0 });
  const error = await client.listJobs().catch((exc) => exc);
  assert.ok(error instanceof ScrawlError, String(error));
  assert.ok(!String(error.message).includes(SECRET.slice(8)), error.message);
});

test("transport errors are scrubbed of the key", async () => {
  const echoing = async (_url, init) => { throw new TypeError(`bad header ${init.headers.Authorization}`); };
  const client = new Scrawl({ apiKey: SECRET, baseUrl: "https://api.test", maxRetries: 0, fetch: echoing });
  const error = await client.getJob("j1").catch((exc) => exc);
  assert.ok(error instanceof APIConnectionError, String(error));
  assert.ok(!error.message.includes(SECRET), error.message);
});
