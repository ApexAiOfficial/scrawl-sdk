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
import { DEFAULT_MAX_BYTES, DEFAULT_MAX_REDIRECTS, fetchPage } from "./local_fetch.js";
import { VERSION } from "./version.js";

export const DEFAULT_BASE_URL = "http://127.0.0.1:8088"; // loopback; set SCRAWL_BASE_URL to your Scrawl endpoint
const RETRY_STATUSES = new Set([429, 502, 503, 504]);
const LIST_KEYS = ["datasets", "versions", "jobs", "entries", "records", "results", "items", "assets", "skipped",
  "pages", "curations"];
const ASSETS_ACTIVE = new Set(["pending", "running"]);
const JOBS_ACTIVE = new Set(["PENDING", "RUNNING"]);
// A job's status has one spelling, the lower case (the API's JobStatus). Servers before it sent the upper case from
// the job and dataset routes; the SDK reads either until the next minor release.
const JOB_STATUSES = ["pending", "running", "completed", "failed", "cancelled", "orphaned"];
const OLD_JOB_STATUS = new Map(JOB_STATUSES.map((status) => [status.toUpperCase(), status]));
const API_KEYS = new WeakMap(); // the key never lives on the instance, so logging a client cannot print it
// What an API key may contain: visible ASCII, the characters an HTTP header value can carry as a token.
const KEY_CHARS = /^[\x21-\x7e]+$/;

function toBase64(bytes) {
  if (typeof Buffer !== "undefined") return Buffer.from(bytes).toString("base64");
  let binary = "";
  for (let index = 0; index < bytes.length; index += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(index, index + 0x8000));
  }
  return btoa(binary);
}

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
  if (Number.isFinite(seconds)) return Math.max(0, seconds);
  const date = Date.parse(value);
  return Number.isFinite(date) ? Math.max(0, (date - Date.now()) / 1000) : null;
}

function jobWithDefaults(job) {
  if (job && typeof job === "object" && !Array.isArray(job) && job.warnings === undefined) job.warnings = [];
  return job;
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
   *
   * The markdown is the page's main content by default; `onlyMainContent: false` keeps the whole body.
   * `includeTags` keeps only what these CSS selectors match (in page order) instead of the main content, and
   * `excludeTags` drops what its selectors match first (each at most 20 selectors of 200 characters). They are sent
   * only when set; the server validates the selectors and answers 422 `invalid_request`.
   */
  async scrape(url, { formats, schema, instruction, profile, waitSeconds = 30, engine, waitForMs, onlyMainContent,
    includeTags, excludeTags, idempotencyKey } = {}) {
    const json = clean({ url, formats: formats || ["markdown"], schema, instruction, profile,
      wait_seconds: this._serverWait(waitSeconds), engine, wait_for_ms: waitForMs,
      only_main_content: onlyMainContent, include_tags: includeTags, exclude_tags: excludeTags });
    return checkEngine(engine,
      await this._call({ method: "POST", path: "/v1/scrape", json, idempotencyKey: newKey(idempotencyKey) }));
  }

  /**
   * Have Scrawl render a page or document you already fetched (`POST /v1/scrape/local`); Scrawl fetches nothing. The
   * result is a scrape's, with `origin: "client_fetched"` and `url_verified: false` (URL, status and type are your
   * claims). `body` is a Uint8Array or a string. `localFetch` fetches the page for you first, honouring robots.txt.
   */
  async scrapeLocal(url, body, { httpStatus = 200, contentType, finalUrl, formats, schema, instruction, profile,
    waitSeconds = 30, onlyMainContent, includeTags, excludeTags, idempotencyKey } = {}) {
    const bytes = typeof body === "string" ? new TextEncoder().encode(body) : body;
    const json = clean({ url, body_base64: toBase64(bytes), http_status: httpStatus, content_type: contentType || undefined,
      final_url: finalUrl, formats: formats || ["markdown"], schema, instruction, profile,
      wait_seconds: this._serverWait(waitSeconds), only_main_content: onlyMainContent, include_tags: includeTags,
      exclude_tags: excludeTags });
    return this._call({ method: "POST", path: "/v1/scrape/local", json, idempotencyKey: newKey(idempotencyKey) });
  }

  /**
   * Fetch `url` from your own machine, then have Scrawl render it (`scrapeLocal`). robots.txt is honoured by default
   * (`respectRobots: false` is your responsibility); at most `maxRedirects` redirects and `maxBytes` bytes. The fetch
   * is its own (`fetchPage`, or the global fetch): it never carries your Scrawl API key. A redirect from https to http
   * is never followed; with your own `fetchPage` a redirect to another host is not either.
   */
  async localFetch(url, { respectRobots = true, maxRedirects = DEFAULT_MAX_REDIRECTS, maxBytes = DEFAULT_MAX_BYTES,
    fetchPage: pageFetch, ...options } = {}) {
    const fetchImpl = pageFetch ?? ((...args) => globalThis.fetch(...args));
    const page = await fetchPage(fetchImpl, url, { respectRobots, maxRedirects, maxBytes,
      sameHostOnly: pageFetch !== undefined });
    return this.scrapeLocal(page.url, page.body, { ...options, httpStatus: page.status, contentType: page.contentType,
      finalUrl: page.finalUrl !== page.url ? page.finalUrl : undefined });
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

  /**
   * Start a batch of up to 20 URLs; poll `batchStatus` (or use `waitForBatch`). Browser items render one at a time.
   * `onlyMainContent`, `includeTags` and `excludeTags` apply to every URL's markdown, as for `scrape`.
   */
  async batchScrape(urls, { formats, schema, instruction, profile, engine, waitForMs, onlyMainContent, includeTags,
    excludeTags, idempotencyKey } = {}) {
    const json = clean({ urls: [...urls], formats: formats || ["markdown"], schema, instruction, profile, engine,
      wait_for_ms: waitForMs, only_main_content: onlyMainContent, include_tags: includeTags,
      exclude_tags: excludeTags });
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

  // -- your proxy: every job needs one that has passed a test -------------------------------------
  /** Your proxy and whether it is usable; NotFoundError when none is registered. */
  async getProxy() {
    return this._call({ method: "GET", path: "/v1/proxy" });
  }

  /**
   * Register or replace your proxy: `url` (scheme://[user:pass@]host:port) or scheme, host and port. The
   * credentials are stored encrypted and never returned. Scraping stays locked until testProxy() passes.
   */
  async setProxy({ url, scheme, host, port, username, password, label } = {}) {
    const json = clean({ url, scheme, host, port, username, password, label });
    return this._call({ method: "PUT", path: "/v1/proxy", json });
  }

  /** Send one real HTTPS request through your proxy; a pass (`ok`) unlocks scraping. */
  async testProxy() {
    return this._call({ method: "POST", path: "/v1/proxy/test" });
  }

  /** Remove your proxy (scraping is locked again). */
  async removeProxy() {
    return this._call({ method: "DELETE", path: "/v1/proxy" });
  }

  /** Your proxy mode and redacted pool entries. */
  async listProxyPool() {
    return this._call({ method: "GET", path: "/v1/proxy-pool" });
  }

  /** Add a proxy URL to the pool; it carries jobs only after testProxyPoolEntry() passes. */
  async addProxyPoolEntry({ url, label, poolId } = {}) {
    return this._call({ method: "POST", path: "/v1/proxy-pool", json: clean({ url, label, pool_id: poolId }) });
  }

  /** Test a pool entry; a pass makes it active. */
  async testProxyPoolEntry(entryRef) {
    return this._call({ method: "POST", path: `/v1/proxy-pool/${seg(entryRef)}/test` });
  }

  /** Enable an entry; it must pass another test before carrying jobs. */
  async enableProxyPoolEntry(entryRef) {
    return this._call({ method: "POST", path: `/v1/proxy-pool/${seg(entryRef)}/enable` });
  }

  /** Take a pool entry out of rotation without removing it. */
  async disableProxyPoolEntry(entryRef) {
    return this._call({ method: "POST", path: `/v1/proxy-pool/${seg(entryRef)}/disable` });
  }

  /** Permanently remove a pool entry. */
  async removeProxyPoolEntry(entryRef) {
    return this._call({ method: "DELETE", path: `/v1/proxy-pool/${seg(entryRef)}` });
  }

  /** Select direct, pool or required_pool proxy routing. */
  async setProxyPoolMode(mode) {
    return this._call({ method: "PUT", path: "/v1/proxy-pool/mode", json: { mode } });
  }

  /** Run the free advisory proxy-health report. This POST is never retried automatically. */
  async proxyHealth() {
    return this._call({ method: "POST", path: "/v1/proxy/health" });
  }

  /** List account API keys (never values). Needs a keys:manage key: /api_keys create_manager in Telegram. */
  async listApiKeys() {
    return this._call({ method: "GET", path: "/v1/keys" });
  }

  /** Permanently revoke an API key by the id returned from listApiKeys(). */
  async revokeApiKey(keyId) {
    return this._call({ method: "DELETE", path: `/v1/keys/${seg(keyId)}` });
  }

  // -- crawls and jobs ----------------------------------------------------------------------------
  /** Start a bounded crawl that publishes a new dataset version. */
  async crawl(crawlTarget, { exportFormat, maxItems, maxSeconds, idempotencyKey } = {}) {
    const json = clean({ crawl_target: crawlTarget, export_format: exportFormat, max_items: maxItems,
      max_seconds: maxSeconds });
    return jobStatus(await this._call({ method: "POST", path: "/v1/crawls", json,
      idempotencyKey: newKey(idempotencyKey) }));
  }

  /**
   * Crawl a site from `url` into a new dataset version: its host only, breadth first, within the bounds. robots.txt
   * is read first (a page it disallows is never fetched). Each page is a scrape, charged as one, so `maxPages` is
   * the most it can cost. Follow it with `siteCrawlStatus` or `waitForSiteCrawl`; cancel with `cancelJob(crawlId)`.
   * `resumeFrom` continues an ended crawl of the same URL.
   */
  async crawlSite(url, { maxPages, maxDepth, engine, waitForMs, onlyMainContent, includeTags, excludeTags, resumeFrom,
    idempotencyKey } = {}) {
    const json = clean({ url, max_pages: maxPages, max_depth: maxDepth, engine, wait_for_ms: waitForMs,
      only_main_content: onlyMainContent, include_tags: includeTags, exclude_tags: excludeTags,
      resume_from: resumeFrom });
    return jobStatus(await this._call({ method: "POST", path: "/v1/site-crawls", json,
      idempotencyKey: newKey(idempotencyKey) }));
  }

  /** A site crawl's status, counts, charge, dataset version and one page of its pages (`next_cursor`). */
  async siteCrawlStatus(crawlId, { waitSeconds = 0, limit, cursor } = {}) {
    return jobStatus(await this._call({ method: "GET", path: `/v1/site-crawls/${seg(crawlId)}`,
      params: { wait_seconds: this._serverWait(waitSeconds) || undefined, limit, cursor } }));
  }

  /** A job's state; `waitSeconds` (<= 60) returns as soon as it finishes. */
  async getJob(jobId, { waitSeconds = 0 } = {}) {
    return jobWithDefaults(jobStatus(await this._call({ method: "GET", path: `/v1/jobs/${seg(jobId)}`,
      params: { wait_seconds: this._serverWait(waitSeconds) || undefined } })));
  }

  /** Your jobs, newest first (`next_cursor` pages). */
  async listJobs({ limit, status, cursor } = {}) {
    const page = jobStatus(await this._call({ method: "GET", path: "/v1/jobs", params: { limit, status, cursor } }));
    if (Array.isArray(page?.jobs)) for (const job of page.jobs) jobWithDefaults(job);
    return page;
  }

  /** Cancel a pending or running job (another process's job: `cancelled` false, requested). */
  async cancelJob(jobId) {
    return jobStatus(await this._call({ method: "POST", path: `/v1/jobs/${seg(jobId)}/cancel` }));
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

  /** A stored document's text (the Markdown behind an asset's `text_url`): untrusted external content, 404 when the
   * asset has none. */
  async downloadAssetText(jobId, assetId) {
    const body = await this._call({ method: "GET", path: `/v1/assets/${seg(jobId)}/files/${seg(assetId)}/text`,
      raw: true });
    return new TextDecoder("utf-8").decode(body);
  }

  // -- datasets -----------------------------------------------------------------------------------
  /** Your datasets (`next_cursor` pages). */
  async listDatasets({ limit, cursor } = {}) {
    return this._call({ method: "GET", path: "/v1/datasets", params: { limit, cursor } });
  }

  /** A dataset's manifest and active version. */
  async getDataset(datasetId) {
    return jobStatus(await this._call({ method: "GET", path: `/v1/datasets/${seg(datasetId)}` }));
  }

  /** A dataset's versions, newest first. */
  async listVersions(datasetId, { limit, cursor, status } = {}) {
    return jobStatus(await this._call({ method: "GET", path: `/v1/datasets/${seg(datasetId)}/versions`,
      params: { limit, cursor, status } }));
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
    return jobStatus(await this._call({ method: "POST", path: `/v1/datasets/${seg(datasetId)}/extract`, json,
      idempotencyKey: newKey(idempotencyKey) }));
  }

  /**
   * A new version of a dataset without a crawl (no fetch, no charge): `remove` `recordIds`, `dedupe` by `field`
   * (`content_hash` by default), or `reextract` each page's markdown with new content options.
   */
  async curateDataset(datasetId, operation, { versionId, recordIds, field, onlyMainContent, includeTags,
    excludeTags } = {}) {
    const json = clean({ operation, version_id: versionId, record_ids: recordIds, field,
      only_main_content: onlyMainContent, include_tags: includeTags, exclude_tags: excludeTags });
    return this._call({ method: "POST", path: `/v1/datasets/${seg(datasetId)}/curate`, json });
  }

  /** A dataset's curations, newest first (`next_cursor` pages). */
  async listCurations(datasetId, { limit, cursor } = {}) {
    return this._call({ method: "GET", path: `/v1/datasets/${seg(datasetId)}/curations`, params: { limit, cursor } });
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

  /** Wait until a site crawl is done (its dataset version final), or the timeout. */
  async waitForSiteCrawl(crawlId, { timeoutMs = 3_900_000 } = {}) {
    const deadline = Date.now() + timeoutMs;
    for (;;) {
      const status = await this.siteCrawlStatus(crawlId, { waitSeconds: waitFor(deadline) });
      if (status?.done || Date.now() >= deadline) return status;
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
   * 429/502/503/504 only when Retry-After is at most 60 s, according to method and responder. Never when the
   * error code is one the catalogue marks not retryable, whatever the status: a resend after `submission_failed`
   * or `settlement_failed` may charge twice.
   */
  _retryable(method, response) {
    if (response.status < 400) return false;
    const body = jsonBody(response.body);              // only error bodies are parsed here: they are small
    if (neverRetry(codeOf(body))) return false;
    const retryAfter = retryAfterSeconds(response.headers);
    if (retryAfter !== null && retryAfter > 60) return false;
    if (response.status === 429) {
      return true;
    }
    if (!RETRY_STATUSES.has(response.status)) return false;
    // Scrawl's own 5xx on a keyed submit is final: its key now stores that outcome, so a retry would
    // only replay a generic failure instead of this error.
    return method === "GET" || !isErrorEnvelope(body);
  }
}

/** RESULT with an upper-case job status (an older server's) in the lower case: top level, `jobs` and `versions`. */
function jobStatus(result) {
  if (!isPlainObject(result)) return result;
  const items = [result];
  for (const key of ["jobs", "versions"]) if (Array.isArray(result[key])) items.push(...result[key]);
  for (const item of items) {
    if (isPlainObject(item) && typeof item.status === "string") {
      item.status = OLD_JOB_STATUS.get(item.status) ?? item.status;
    }
  }
  return result;
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
