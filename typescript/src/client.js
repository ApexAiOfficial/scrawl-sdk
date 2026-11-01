// The Scrawl client over the versioned ApexAPI contract.
//
// Submits that start work (scrape, map, batch, crawl, dataset and asset extraction) carry an Idempotency-Key -
// generated unless you pass one - so a retry after a network error or a 429/5xx never starts the work
// twice. Other POSTs are never retried, and neither is any response whose error code the backend's error
// catalogue marks not retryable (RETRYABLE in errors.js). Responses are the API's JSON as-is (snake_case fields).
//
// The base URL comes from the option or SCRAWL_BASE_URL; without either, the client uses a loopback address
// (http://127.0.0.1:8088). There is no built-in remote default.

import {
  APIConnectionError, APITimeoutError, ConfigurationError, ErrorCode, ScrawlError, codeOf, errorFor, neverRetry,
} from "./errors.js";
import { VERSION } from "./version.js";

export const DEFAULT_BASE_URL = "http://127.0.0.1:8088"; // loopback; set SCRAWL_BASE_URL to your Scrawl endpoint
const RETRY_STATUSES = new Set([429, 502, 503, 504]);
const LIST_KEYS = ["datasets", "versions", "jobs", "entries", "records", "results", "items", "assets", "skipped"];
const ASSETS_ACTIVE = new Set(["pending", "running"]);
const JOBS_ACTIVE = new Set(["PENDING", "RUNNING"]);
const API_KEYS = new WeakMap(); // the key never lives on the instance, so logging a client cannot print it
// What an API key may contain: visible ASCII, the characters an HTTP header value can carry as a token.
const KEY_CHARS = /^[\x21-\x7e]+$/;

function clean(values) {
  return Object.fromEntries(Object.entries(values).filter(([, value]) => value !== undefined && value !== null));
}

function seg(value) {
  const text = String(value);
  // URL parsers resolve "." and ".." even when percent-encoded: never let an id walk to another route.
  if (text === "" || text === "." || text === "..") throw new ScrawlError(`Invalid path segment: ${JSON.stringify(text)}`);
  return encodeURIComponent(text);
}

function newKey(value) {
  if (value) return value;
  const uuid = globalThis.crypto?.randomUUID?.();          // secure contexts only in browsers
  if (uuid) return uuid.replaceAll("-", "");
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) globalThis.crypto.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function isLoopback(hostname) {
  const host = hostname.replace(/^\[|\]$/g, "").toLowerCase();
  return host === "localhost" || host.endsWith(".localhost") || host === "::1" || /^127(\.\d{1,3}){3}$/.test(host);
}

function checkBaseUrl(baseUrl, allowInsecureHttp) {
  let url;
  try {
    url = new URL(baseUrl);
  } catch {
    throw new ConfigurationError(`Invalid base URL: ${JSON.stringify(baseUrl)}`);
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") throw new ConfigurationError(`Base URL must be http(s): ${baseUrl}`);
  if (url.protocol === "http:" && !isLoopback(url.hostname) && !allowInsecureHttp) {
    throw new ConfigurationError(`Refusing to send the API key over plain HTTP to ${url.host}: use https:// ` +
      "(or allowInsecureHttp / SCRAWL_ALLOW_INSECURE_HTTP=1 on a trusted network)");
  }
}

function jsonBody(text) {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function isErrorEnvelope(body) {
  return Boolean(body && typeof body.error === "object" && body.error?.code);
}

function env(name) {
  try {
    return globalThis.process?.env?.[name] || undefined;
  } catch {
    return undefined; // Deno without --allow-env, sandboxed runtimes
  }
}

function isPlainObject(value) {
  return Object.prototype.toString.call(value) === "[object Object]";
}

function retryAfterSeconds(headers) {
  const value = headers?.get("retry-after");
  if (value === null || value === undefined || value.trim() === "") return null;
  const seconds = Number(value);
  return Number.isFinite(seconds) ? Math.max(0, seconds) : null;
}

function itemsOf(page) {
  for (const key of LIST_KEYS) {
    if (Array.isArray(page?.[key])) return page[key];
  }
  return [];
}

function timeoutSignal(ms) {
  if (typeof AbortSignal.timeout === "function") return AbortSignal.timeout(ms);
  const controller = new AbortController();
  setTimeout(() => controller.abort(new DOMException("timed out", "TimeoutError")), ms).unref?.();
  return controller.signal;
}

/** The Scrawl client. `const client = new Scrawl(); await client.scrape("https://example.com")`. */
export class Scrawl {
  constructor({ apiKey, baseUrl, timeoutMs = 90_000, maxRetries = 2, fetch, allowInsecureHttp } = {}) {
    // A key read from a file or a CRLF .env file keeps its line ending: trim it rather than send it.
    API_KEYS.set(this, String(apiKey || env("SCRAWL_API_KEY") || "").trim() || null);
    this.baseUrl = String(baseUrl || env("SCRAWL_BASE_URL") || DEFAULT_BASE_URL).replace(/\/+$/, "");
    checkBaseUrl(this.baseUrl, allowInsecureHttp ?? env("SCRAWL_ALLOW_INSECURE_HTTP") === "1");
    this.timeoutMs = timeoutMs;
    this.maxRetries = Math.max(0, Math.trunc(maxRetries));
    const fetchImpl = fetch ?? globalThis.fetch;
    if (typeof fetchImpl !== "function") throw new ConfigurationError("No fetch available: pass { fetch } (Node 20+ has one)");
    this._fetch = fetch ? fetch : (...args) => globalThis.fetch(...args);
    this._sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  }

  // -- scrape / map / batch ------------------------------------------------------------------------
  /**
   * Scrape one URL. `status` is `completed`, `pending` (poll `scrapeResult`) or `failed`. `engine: "browser"`
   * renders the page in a sandboxed browser first (only where the server enables it), waiting `waitForMs` more after it
   * settles; a finished result from a server that did not render it throws `render_not_supported`.
   */
  async scrape(url, { formats, schema, instruction, profile, waitSeconds = 30, engine, waitForMs, idempotencyKey } = {}) {
    const json = clean({ url, formats: formats || ["markdown"], schema, instruction, profile,
      wait_seconds: this._serverWait(waitSeconds), engine, wait_for_ms: waitForMs });
    return checkEngine(engine,
      await this._call({ method: "POST", path: "/v1/scrape", json, idempotencyKey: newKey(idempotencyKey) }));
  }

  /**
   * A scrape job's result in the formats it asked for (or re-rendered as markdown/links/html). Pass the `engine`
   * the scrape asked for to keep the downgrade guard on a pending job's follow-up (it is never sent).
   */
  async scrapeResult(jobId, { waitSeconds = 0, formats, engine } = {}) {
    const params = { wait_seconds: this._serverWait(waitSeconds) || undefined,
      formats: formats?.length ? formats.join(",") : undefined };
    return checkEngine(engine, await this._call({ method: "GET", path: `/v1/scrape/${seg(jobId)}/content`, params }));
  }

  /** Same-host URLs of a site: the start page's links plus its sitemap (`engine` as for `scrape`). */
  async map(url, { limit = 100, waitSeconds = 30, engine, waitForMs, idempotencyKey } = {}) {
    const json = { url, limit, wait_seconds: this._serverWait(waitSeconds), ...clean({ engine, wait_for_ms: waitForMs }) };
    return checkEngine(engine,
      await this._call({ method: "POST", path: "/v1/map", json, idempotencyKey: newKey(idempotencyKey) }));
  }

  /** Start a batch of up to 20 URLs; poll `batchStatus` (or use `waitForBatch`). Browser items render one at a time. */
  async batchScrape(urls, { formats, schema, instruction, profile, engine, waitForMs, idempotencyKey } = {}) {
    const json = clean({ urls: [...urls], formats: formats || ["markdown"], schema, instruction, profile, engine,
      wait_for_ms: waitForMs });
    return this._call({ method: "POST", path: "/v1/scrape/batch", json, idempotencyKey: newKey(idempotencyKey) });
  }

  /** A batch's items and their results. */
  async batchStatus(batchId, { waitSeconds = 0 } = {}) {
    return this._call({ method: "GET", path: `/v1/scrape/batch/${seg(batchId)}`,
      params: { wait_seconds: this._serverWait(waitSeconds) || undefined } });
  }

  // -- AI -----------------------------------------------------------------------------------------
  /** Extract JSON from a finished job's artifact with your own AI provider. */
  async extract(jobId, { artifact = "response.html", schema, instruction, profile } = {}) {
    const json = clean({ job_id: jobId, artifact, schema, instruction, profile });
    return this._call({ method: "POST", path: "/v1/extract", json });
  }

  /** Answer a question from your datasets, with citations. */
  async ask(question, { datasetId, profile } = {}) {
    return this._call({ method: "POST", path: "/v1/ask", json: clean({ question, dataset_id: datasetId, profile }) });
  }

  /** Your configured AI provider profiles (never the keys). */
  async listAiProviders() {
    return this._call({ method: "GET", path: "/v1/ai/providers" });
  }

  /** Create or replace an AI provider profile (the key is stored encrypted, never returned). */
  async setAiProvider(profile, { provider, apiKey, model, baseUrl } = {}) {
    const json = clean({ provider, api_key: apiKey, model, base_url: baseUrl });
    return this._call({ method: "PUT", path: `/v1/ai/providers/${seg(profile)}`, json });
  }

  /** Delete an AI provider profile. */
  async deleteAiProvider(profile) {
    return this._call({ method: "DELETE", path: `/v1/ai/providers/${seg(profile)}` });
  }

  /** Make a profile your default. */
  async setDefaultAiProvider(profile) {
    return this._call({ method: "POST", path: `/v1/ai/providers/${seg(profile)}/default` });
  }

  /** Check a profile can reach its provider. */
  async testAiProvider(profile) {
    return this._call({ method: "POST", path: `/v1/ai/providers/${seg(profile)}/test` });
  }

  /** Your AI calls and tokens by provider, model and feature. */
  async aiUsage({ days = 30 } = {}) {
    return this._call({ method: "GET", path: "/v1/ai/usage", params: { days } });
  }

  // -- crawls and jobs ----------------------------------------------------------------------------
  /** Start a bounded crawl that publishes a new dataset version. */
  async crawl(crawlTarget, { exportFormat, maxItems, maxSeconds, idempotencyKey } = {}) {
    const json = clean({ crawl_target: crawlTarget, export_format: exportFormat, max_items: maxItems,
      max_seconds: maxSeconds });
    return this._call({ method: "POST", path: "/v1/crawls", json, idempotencyKey: newKey(idempotencyKey) });
  }

  /** A job's state; `waitSeconds` (<= 60) returns as soon as it finishes. */
  async getJob(jobId, { waitSeconds = 0 } = {}) {
    return this._call({ method: "GET", path: `/v1/jobs/${seg(jobId)}`,
      params: { wait_seconds: this._serverWait(waitSeconds) || undefined } });
  }

  /** Your jobs, newest first (`next_cursor` pages). */
  async listJobs({ limit, status, cursor } = {}) {
    return this._call({ method: "GET", path: "/v1/jobs", params: { limit, status, cursor } });
  }

  /** Cancel a pending or running job (another process's job: `cancelled` false, requested). */
  async cancelJob(jobId) {
    return this._call({ method: "POST", path: `/v1/jobs/${seg(jobId)}/cancel` });
  }

  /** A job's artifacts. */
  async listArtifacts(jobId) {
    return this._call({ method: "GET", path: `/v1/artifacts/${seg(jobId)}` });
  }

  /** One artifact's bytes as an ArrayBuffer (`format: "markdown"` converts HTML). */
  async downloadArtifact(jobId, filename, { format } = {}) {
    return this._call({ method: "GET", path: `/v1/artifacts/${seg(jobId)}/${seg(filename)}`, params: { format },
      raw: true });
  }

  // -- assets -------------------------------------------------------------------------------------
  /** What extracting a page's assets would hold, your credits and egress readiness (starts nothing). */
  async quoteAssets(url, { classes, maxItems, maxBytes, maxCredits } = {}) {
    const json = clean({ url, classes, max_items: maxItems, max_bytes: maxBytes, max_credits: maxCredits });
    return this._call({ method: "POST", path: "/v1/assets/quote", json });
  }

  /** Start extracting a page's assets (images, video, audio, documents, data, web_assets); a job. */
  async extractAssets(url, { classes, maxItems, maxBytes, maxCredits, idempotencyKey } = {}) {
    const json = clean({ url, classes, max_items: maxItems, max_bytes: maxBytes, max_credits: maxCredits });
    return this._call({ method: "POST", path: "/v1/assets", json, idempotencyKey: newKey(idempotencyKey) });
  }

  /** An asset job's state and one page of its stored assets (`view: "skipped"`: what it skipped, why). */
  async getAssets(jobId, { view, limit, cursor, waitSeconds = 0 } = {}) {
    return this._call({ method: "GET", path: `/v1/assets/${seg(jobId)}`,
      params: { view, limit, cursor, wait_seconds: this._serverWait(waitSeconds) || undefined } });
  }

  /** One stored asset's bytes as an ArrayBuffer: untrusted content, compare its `sha256` before use. */
  async downloadAsset(jobId, assetId) {
    return this._call({ method: "GET", path: `/v1/assets/${seg(jobId)}/files/${seg(assetId)}`, raw: true });
  }

  // -- datasets -----------------------------------------------------------------------------------
  /** Your datasets (`next_cursor` pages). */
  async listDatasets({ limit, cursor } = {}) {
    return this._call({ method: "GET", path: "/v1/datasets", params: { limit, cursor } });
  }

  /** A dataset's manifest and active version. */
  async getDataset(datasetId) {
    return this._call({ method: "GET", path: `/v1/datasets/${seg(datasetId)}` });
  }

  /** A dataset's versions, newest first. */
  async listVersions(datasetId, { limit, cursor, status } = {}) {
    return this._call({ method: "GET", path: `/v1/datasets/${seg(datasetId)}/versions`, params: { limit, cursor, status } });
  }

  /** Make a completed version the active one. */
  async activateVersion(datasetId, versionId) {
    return this._call({ method: "POST", path: `/v1/datasets/${seg(datasetId)}/active-version`,
      json: { version_id: versionId } });
  }

  /** Added / removed / changed records between two versions. */
  async diffVersions(datasetId, fromVersion, toVersion, { limit, cursor } = {}) {
    return this._call({ method: "GET", path: `/v1/datasets/${seg(datasetId)}/diff`,
      params: { from: fromVersion, to: toVersion, limit, cursor } });
  }

  /** Fields discovered in a version: paths, types, presence, examples. */
  async datasetFields(datasetId, { version } = {}) {
    return this._call({ method: "GET", path: `/v1/datasets/${seg(datasetId)}/fields`, params: { version } });
  }

  /** Typed filters (eq, ne, lt, lte, gt, gte, contains, in, exists) over a version's records. */
  async queryDataset(datasetId, filters, { versionId, limit, cursor } = {}) {
    const json = clean({ filters, version_id: versionId, limit, cursor });
    return this._call({ method: "POST", path: `/v1/datasets/${seg(datasetId)}/query`, json });
  }

  /** Extract a structured dataset version from a dataset with your own AI provider (a job). */
  async extractDataset(datasetId, { schema, instruction, profile, versionId, maxRecords, idempotencyKey } = {}) {
    const json = clean({ schema, instruction, profile, version_id: versionId, max_records: maxRecords });
    return this._call({ method: "POST", path: `/v1/datasets/${seg(datasetId)}/extract`, json,
      idempotencyKey: newKey(idempotencyKey) });
  }

  /** Hide a record from retrieval (reversible with `releaseRecord`). */
  async quarantineRecord(datasetId, recordId, { reason } = {}) {
    return this._call({ method: "PUT", path: `/v1/datasets/${seg(datasetId)}/records/${seg(recordId)}/quarantine`,
      json: clean({ reason }) });
  }

  /** Undo a quarantine. */
  async releaseRecord(datasetId, recordId) {
    return this._call({ method: "DELETE", path: `/v1/datasets/${seg(datasetId)}/records/${seg(recordId)}/quarantine` });
  }

  /** Search your active dataset versions. */
  async search(query, { limit } = {}) {
    return this._call({ method: "POST", path: "/v1/search", json: clean({ query, limit }) });
  }

  /** One indexed record with provenance. */
  async getDocument(documentId) {
    return this._call({ method: "GET", path: `/v1/documents/${seg(documentId)}` });
  }

  // -- account ------------------------------------------------------------------------------------
  /** Your credit balance, or an unmetered status. */
  async creditBalance() {
    return this._call({ method: "GET", path: "/v1/credits/balance" });
  }

  /** Service health (no authentication needed). */
  async health() {
    return this._call({ method: "GET", path: "/v1/health", auth: false });
  }

  // -- helpers ------------------------------------------------------------------------------------
  /** Wait until a pending scrape settles (server-side waits, no tight polling). */
  async waitForScrape(jobId, { timeoutMs = 300_000, engine } = {}) {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const result = await this.scrapeResult(jobId, { waitSeconds: waitFor(deadline), engine });
      if (result?.status !== "pending" || Date.now() >= deadline) return result;
    }
  }

  /** Wait until every item of a batch has settled (or the timeout). */
  async waitForBatch(batchId, { timeoutMs = 600_000 } = {}) {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const status = await this.batchStatus(batchId, { waitSeconds: waitFor(deadline) });
      if (status?.status === "completed" || Date.now() >= deadline) return status;
    }
  }

  /** Wait until an asset job settles: completed, failed, cancelled or orphaned (or the timeout). */
  async waitForAssets(jobId, { timeoutMs = 600_000 } = {}) {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const result = await this.getAssets(jobId, { waitSeconds: waitFor(deadline) });
      if (!ASSETS_ACTIVE.has(result?.status) || Date.now() >= deadline) return result;
    }
  }

  /** Wait until a job (a crawl, a dataset extraction...) leaves PENDING/RUNNING (or the timeout). */
  async waitForJob(jobId, { timeoutMs = 1_800_000 } = {}) {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const job = await this.getJob(jobId, { waitSeconds: waitFor(deadline) });
      if (!JOBS_ACTIVE.has(String(job?.status ?? "").toUpperCase()) || Date.now() >= deadline) return job;
    }
  }

  /**
   * Iterate every item of a cursor-paged list method:
   * `for await (const d of client.paginate(client.listDatasets)) ...`,
   * `client.paginate(client.listVersions, datasetId, { limit: 50 })`.
   */
  async *paginate(method, ...args) {
    const options = isPlainObject(args.at(-1)) ? { ...args.pop() } : {};
    let cursor = options.cursor;
    for (;;) {
      const page = await method.call(this, ...args, { ...options, cursor });
      yield* itemsOf(page);
      cursor = page?.next_cursor;
      if (!cursor) return;
    }
  }

  // -- transport ----------------------------------------------------------------------------------
  /** A server-side wait (seconds) that finishes inside this client's request timeout (<= 60, the API cap). */
  _serverWait(seconds) {
    if (!seconds || seconds <= 0) return seconds;
    return Math.max(1, Math.min(Math.trunc(seconds), 60, Math.trunc(this.timeoutMs / 1000) - 5));
  }

  _headers({ auth = true, idempotencyKey, json }) {
    const headers = { "User-Agent": `scrawl-ts/${VERSION}`, Accept: "application/json" };
    if (json !== undefined) headers["Content-Type"] = "application/json";
    if (auth) {
      const apiKey = API_KEYS.get(this);
      if (!apiKey) throw new ConfigurationError("No API key: pass { apiKey } or set SCRAWL_API_KEY");
      if (!KEY_CHARS.test(apiKey)) {
        // Never quote the key: fetch refusing it would put the whole value in its message.
        throw new ConfigurationError("The API key contains spaces, control or non-ASCII characters that an HTTP " +
          "header cannot carry (not shown); check { apiKey } or SCRAWL_API_KEY");
      }
      headers.Authorization = `Bearer ${apiKey}`;
    }
    if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;
    return headers;
  }

  /** A library's error text with the API key replaced: some quote the header value they refused. */
  _scrub(text) {
    const apiKey = API_KEYS.get(this);
    return apiKey ? String(text).replaceAll(apiKey, "***") : String(text);
  }

  _delay(attempt, response) {
    const retryAfter = response ? retryAfterSeconds(response.headers) : null;
    if (retryAfter !== null) return Math.min(retryAfter, 60) * 1000;
    return Math.min(500 * 2 ** attempt + Math.random() * 250, 20_000);
  }

  async _call(request) {
    const { method, path, params = {}, json, raw = false } = request;
    const query = new URLSearchParams(Object.entries(clean(params)).map(([key, value]) => [key, String(value)])).toString();
    const url = this.baseUrl + path + (query ? `?${query}` : "");
    const headers = this._headers(request);
    const body = json === undefined ? undefined : JSON.stringify(json);    // a local error, never retried
    const keyed = Boolean(request.idempotencyKey);
    // A keyed submit whose first attempt is still running answers 409: wait for its stored response.
    const replayDeadline = Date.now() + ((json?.wait_seconds ?? 60) + 15) * 1000;
    for (let attempt = 0; ; attempt += 1) {
      let response = null;
      let error = null;
      try {
        const res = await this._fetch(url, { method, headers, body, signal: timeoutSignal(this.timeoutMs) });
        try {
          const data = raw && res.status < 400 ? await res.arrayBuffer() : await res.text();
          response = { status: res.status, headers: res.headers, body: data };
        } catch (exc) {
          if (res.status < 400) throw exc;
          response = { status: res.status, headers: res.headers, body: "" };   // keep the status and Retry-After
        }
      } catch (exc) {
        error = exc?.name === "TimeoutError" || exc?.name === "AbortError"
          ? new APITimeoutError(`Request timed out after ${this.timeoutMs} ms`)
          : new APIConnectionError(`Connection failed: ${this._scrub(exc?.message ?? exc)}`);
      }
      if (response?.status === 409 && keyed && Date.now() < replayDeadline
          && !neverRetry(codeOf(jsonBody(response.body)))) {
        await this._sleep(Math.max(1000, this._delay(0, response)));
        continue;
      }
      const canRetry = (method === "GET" || keyed) && attempt < this.maxRetries;
      if (response && !(canRetry && this._retryable(method, response))) return decode(response, raw);
      if (error && !canRetry) throw error;
      await this._sleep(this._delay(attempt, response));
    }
  }

  /**
   * 429 always; 502/503/504 for GETs, and for submits only when a proxy (not Scrawl) answered. Never when the
   * error code is one the catalogue marks not retryable, whatever the status: a resend after `submission_failed`
   * or `settlement_failed` may charge twice.
   */
  _retryable(method, response) {
    if (response.status < 400) return false;
    const body = jsonBody(response.body);              // only error bodies are parsed here: they are small
    if (neverRetry(codeOf(body))) return false;
    if (response.status === 429) return true;
    if (!RETRY_STATUSES.has(response.status)) return false;
    // Scrawl's own 5xx on a keyed submit is final: its key now stores that outcome, so a retry would
    // only replay a generic failure instead of this error.
    return method === "GET" || !isErrorEnvelope(body);
  }
}

/** The downgrade guard: `browser` was asked for, but a finished result says another engine rendered it. */
function checkEngine(requested, result) {
  if (requested === "browser" && result && (result.status === "completed" || result.status === "failed")
      && result.engine !== "browser") {
    throw new ScrawlError("The server did not render this page in a browser (it may predate the browser engine)",
      { code: ErrorCode.RENDER_NOT_SUPPORTED, details: { engine: result.engine ?? null } });
  }
  return result;
}

function waitFor(deadline) {
  return Math.trunc(Math.min(60, Math.max(1, (deadline - Date.now()) / 1000)));
}

function decode(response, raw) {
  const requestId = response.headers?.get("x-request-id") ?? null;
  if (response.status >= 400) {
    let body;
    try {
      body = JSON.parse(response.body);
    } catch {
      body = { detail: String(response.body).slice(0, 500) };
    }
    throw errorFor(response.status, body, { requestId, retryAfter: retryAfterSeconds(response.headers) });
  }
  if (raw) return response.body;
  if (response.status === 204 || !response.body) return null;
  try {
    return JSON.parse(response.body);
  } catch {
    throw new ScrawlError("The API returned a response that is not JSON", { status: response.status, requestId });
  }
}
