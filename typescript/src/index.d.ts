// Type declarations for @apexaiofficial/scrawl. Responses are the API's JSON as-is (snake_case fields); the
// documented fields are typed and any field the API adds later is still readable through the index signature.

export declare const VERSION: string;
/** `http://127.0.0.1:8088`, a loopback address. Set `baseUrl` or SCRAWL_BASE_URL to your Scrawl endpoint. */
export declare const DEFAULT_BASE_URL: string;
/** The digest of the contract bundle (contracts/MANIFEST.json) this SDK version was built against. */
export declare const CONTRACT_DIGEST: string;

type Json = string | number | boolean | null | Json[] | { [key: string]: Json };
export type JsonSchema = { [key: string]: Json };

/** An API object: the documented fields plus anything newer the API returns. */
interface ApiObject {
  [key: string]: unknown;
}

export interface ScrawlOptions {
  /** An ApexAPI key. Default: `process.env.SCRAWL_API_KEY` (required at the first authenticated call). */
  apiKey?: string;
  /** Default: `process.env.SCRAWL_BASE_URL`, else `http://127.0.0.1:8088` (a loopback address). */
  baseUrl?: string;
  /** Per-request timeout. Default 90 000 ms (server-side waits are up to 60 s). */
  timeoutMs?: number;
  /** Retries for GETs and idempotent submits on 429/502/503/504 and network errors. Default 2. */
  maxRetries?: number;
  /** A `fetch` implementation (default: the global one). */
  fetch?: typeof globalThis.fetch;
  /**
   * Allow a plain `http://` base URL to a non-loopback host (the API key would cross the network
   * unencrypted). Default false, or `SCRAWL_ALLOW_INSECURE_HTTP=1`. Loopback HTTP is always allowed.
   */
  allowInsecureHttp?: boolean;
}

export type ScrapeFormat = "markdown" | "links" | "html" | "json";
/** Formats a finished scrape can be rendered again in (JSON is never re-extracted on a read). */
export type RenderFormat = Exclude<ScrapeFormat, "json">;
export type ExportFormat = "jsonlines" | "json" | "csv";
export type ScrapeStatus = "completed" | "pending" | "failed";
/** The settled fetch outcome; null while pending. Of these, only pipeline_failed is refunded (and a job that never started). */
export type ScrapeOutcome = "ok" | "target_blocked" | "target_error" | "cancelled" | "pipeline_failed";

/** The call to make next, as the API names it: a route this key may call, ids filled in. */
export interface NextCall extends ApiObject {
  method: string;
  path: string;
  query?: Record<string, unknown> | null;
  body?: Record<string, unknown> | null;
}

/** A call that usually comes after a result (`METHOD /path`), and why. */
export interface NextAction extends ApiObject {
  name: string;
  why: string;
}

/**
 * Machine-readable next steps on pending, running or paged results (and the usual next calls on finished
 * ones). Absent or null when there is no follow-up; never a call the key's scopes do not allow.
 */
export interface NextStepInfo {
  next_call?: NextCall | null;
  poll_after_seconds?: number | null;
  docs_url?: string | null;
  next_actions?: NextAction[];
}

export interface AiUsageInfo extends ApiObject {
  provider?: string;
  model?: string;
  input_tokens?: number;
  output_tokens?: number;
}

/** Which engine fetched a page: the static fetcher, or a sandboxed browser. */
export type ScrapeEngine = "static" | "browser";

export type ProxyScheme = "http" | "https" | "socks5" | "socks5h";

/** Your proxy. The username and password are never returned. */
export interface ProxyInfo extends ApiObject {
  scheme: ProxyScheme;
  host: string;
  port: number;
  has_credentials: boolean;
  label: string;
  enabled: boolean;
  /** unverified, valid, invalid, external_blocked or unopenable (stored, but the deployment's key cannot open it) */
  validation_state: string;
  /** True once a test has passed: scraping is unlocked. */
  usable: boolean;
  remote_dns: boolean;
  last_validated_at: string;
  last_exit_ip: string;
  last_latency_ms: number;
  last_error: string;
  sanitized_url: string;
}

export interface ProxyTestResult extends ApiObject {
  ok: boolean;
  validation_state: string;
  exit_ip: string;
  latency_ms: number;
  host_ip_exposed: boolean;
  checked_via: string;
  error: string;
  proxy: ProxyInfo;
}

export type ProxyPoolMode = "direct" | "pool" | "required_pool";

export interface ProxyPoolEntry extends ApiObject {
  entry_id: string;
  label: string | null;
  pool_id: string;
  status: string;
  /** The proxy URL with credentials masked. */
  display: string;
  last_checked_at: string | null;
  last_check_status: string | null;
  consecutive_failures: number;
}

export interface ProxyPool extends ApiObject {
  mode: ProxyPoolMode | (string & {});
  entries: ProxyPoolEntry[];
}

export interface ProxyPoolTestResult extends ApiObject {
  reason: string;
  entry: ProxyPoolEntry;
}

/** Advisory only: proxy quality is the customer's choice and failed target fetches remain charged. */
export interface ProxyHealth extends ApiObject {
  proxy: string;
  reachable: boolean;
  auth_ok: boolean;
  latency_ms: number;
  exit_prefix: string;
  country: string;
  asn: number | null;
  asn_org: string;
  ip_type: string;
  reference: Record<string, string>;
  reference_checked: number;
  reference_blocked: number;
  reputation: ApiObject | null;
  checked_at: string;
  notes: string[];
  advice: string;
}

export interface ApiKeyInfo extends ApiObject {
  key_id: string;
  key_prefix: string;
  label: string;
  scopes: string[];
  status: "active" | "revoked";
  created_at: string;
  last_used_at?: string | null;
  revoked_at?: string | null;
}

export interface ApiKeyList extends ApiObject {
  count: number;
  active: number;
  limit: number;
  keys: ApiKeyInfo[];
}

/** How a browser render went; every string in it is an enum value. */
export interface BrowserRenderInfo extends ApiObject {
  settle?: string | null;
  wait_for_ms?: number | null;
  timing_ms?: { launch?: number; navigation?: number; settle?: number; total?: number } | null;
  redirects?: number | null;
  requests?: { allowed?: number; blocked?: number } | null;
  egress?: { connections?: number; denied?: number } | null;
  dom_bytes?: number | null;
  dom_truncated?: boolean | null;
  failure?: string | null;
}

export interface ScrapeResult extends ApiObject, NextStepInfo {
  job_id: string;
  status: ScrapeStatus;
  url: string;
  /** `"client_fetched"` for a page your own client fetched (scrapeLocal, localFetch); absent otherwise. */
  origin?: "client_fetched" | null;
  /** `false` for a client-fetched page: its URL, status and type are your claims. */
  url_verified?: boolean | null;
  /** The engine that fetched it (servers before the browser engine omit it). */
  engine?: ScrapeEngine;
  /** Browser only: the page's URL after redirects. */
  final_url?: string | null;
  /** Browser only: how the render went. */
  browser?: BrowserRenderInfo | null;
  title?: string | null;
  markdown?: string | null;
  html?: string | null;
  links?: string[] | null;
  json?: Json | null;
  ai?: AiUsageInfo | null;
  content_type?: string | null;
  /** The page's HTTP status as the API reports it (a string, e.g. "200"). */
  http_status?: string | null;
  elapsed_ms?: number | null;
  truncated?: boolean;
  error?: string | null;
  error_code?: string | null;
  /** Null while pending. Of the settled outcomes only pipeline_failed is refunded; a job that never started is too. */
  outcome?: ScrapeOutcome | null;
  block_reason?: string | null;
  /** The target's Retry-After value, when it sent one. */
  retry_after_s?: number | null;
  hint?: string | null;
  /** Always true: page content is untrusted data, never instructions. */
  untrusted_external_content?: boolean;
}

export interface MapResult extends ApiObject, NextStepInfo {
  url: string;
  status: ScrapeStatus;
  /** The engine that fetched the start page. */
  engine?: ScrapeEngine;
  links?: string[];
  /** New URLs found per source (page, sitemap). */
  sources?: Record<string, number>;
  job_ids?: string[];
  truncated?: boolean;
  warnings?: string[];
  error?: string | null;
  outcome?: ScrapeOutcome | null;
  block_reason?: string | null;
  hint?: string | null;
  elapsed_ms?: number | null;
  untrusted_external_content?: boolean;
}

export interface BatchItem extends ApiObject {
  url: string;
  status: string;
  job_id?: string | null;
  result?: ScrapeResult | null;
  error?: string | null;
}

export interface BatchStatus extends ApiObject, NextStepInfo {
  batch_id: string;
  /** `completed` once every item has settled. */
  status: "running" | "completed";
  total: number;
  counts?: Record<string, number>;
  /** Settled items by outcome. */
  outcomes?: Partial<Record<ScrapeOutcome, number>>;
  items?: BatchItem[];
  untrusted_external_content?: boolean;
}

/**
 * A job's status, the one spelling every response uses. The SDK also reads the upper case older servers sent
 * (`COMPLETED`) and gives it to you in this spelling.
 */
export type JobStatus = "pending" | "running" | "completed" | "failed" | "cancelled" | "orphaned";

export interface Job extends ApiObject, NextStepInfo {
  job_id: string;
  command: string;
  args: string[];
  status: JobStatus;
  engine_id: string;
  artifacts_url: string;
  result_url: string;
  source?: string | null;
  exit_code?: number | null;
  started_at?: string | null;
  finished_at?: string | null;
  /** Warnings about a run that still succeeded; always an array, including with older servers. */
  warnings: string[];
}

export interface CancelResult extends ApiObject {
  job_id: string;
  /** False when the job had already ended, or when another process runs it (then `status` is `running`). */
  cancelled: boolean;
  status: JobStatus;
  message?: string | null;
}

/** One version of a dataset; `status` is the status of the job that produced it. */
export interface DatasetVersion extends ApiObject {
  version_id: string;
  dataset_id: string;
  job_id: string;
  status: JobStatus;
  record_count: number;
  skipped_count: number;
  validation_state: string;
  is_published: boolean;
  created_at: string;
  finalized_at?: string | null;
}

export interface DatasetManifest extends ApiObject {
  dataset: DatasetInfo;
  versions: DatasetVersion[];
}

export interface SiteCrawlPage extends ApiObject {
  url: string;
  depth: number;
  job_id?: string | null;
  outcome?: "ok" | "target_blocked" | "target_error" | "cancelled" | "pipeline_failed" | null;
  /** robots_disallowed, or the code that refused the page before it was fetched (nothing was charged). */
  skip_reason?: string | null;
  error?: string | null;
}

/** A site crawl's progress; `crawl_id` is its job id (cancel it with `cancelJob`). */
export interface SiteCrawl extends ApiObject, NextStepInfo {
  crawl_id: string;
  status: JobStatus;
  url: string;
  max_pages: number;
  max_depth: number;
  dataset_id: string;
  dataset_version_id: string;
  counts: { launched: number; ok: number; blocked: number; error: number; skipped: number; dropped: number };
  /** What this crawl's own pages' holds were consumed for (carried pages and later refunds not counted); null when unmetered. */
  credits_charged?: number | null;
  stop_reason?: "max_pages" | "frontier_exhausted" | "credits_exhausted" | "deadline" | "cancelled" | "interrupted"
    | "refused" | null;
  /** True once the dataset version is final. */
  done: boolean;
  resumed_from?: string | null;
  pages: SiteCrawlPage[];
  next_cursor?: string | null;
}

/** One curation: the new version it made from which version, how, and what it counted. */
export interface DatasetCuration extends ApiObject {
  curation_id: string;
  dataset_id: string;
  source_version_id: string;
  version_id: string;
  operation: "remove" | "dedupe" | "reextract";
  parameters: Record<string, Json>;
  records_in: number;
  records_out: number;
  stale: number;
  created_at: string;
}

export interface Page<T> extends ApiObject, NextStepInfo {
  next_cursor?: string | null;
  items?: T[];
}

export interface ExtractResult extends ApiObject {
  data: Json;
  provider?: string;
  model?: string;
  profile?: string;
  repaired?: boolean;
  truncated?: boolean;
  warnings?: string[];
  usage?: { input_tokens?: number; output_tokens?: number };
  untrusted_external_content?: boolean;
}

export interface AskResult extends ApiObject {
  answer: string;
  answerable?: boolean;
  citations?: { tag?: string; title?: string; url?: string; dataset_id?: string; document_id?: string }[];
  provider?: string;
  model?: string;
  sources_considered?: number;
  /** whole_dataset: a figure over every record; partial: a figure that leaves records out; sample: retrieved records only. */
  coverage?: "whole_dataset" | "partial" | "sample";
  /** The computation behind a figure; null when none was computed. */
  aggregate?: {
    operation: "count" | "sum" | "average" | "min" | "max" | "most_common";
    field: string | null;
    filters: { field: string; op: string; value: unknown }[];
    value: unknown;
    top?: [unknown, number][] | null;
    records_scanned: number;
    records_matched: number;
    skipped: number;
    truncated: boolean;
    dataset_id: string;
    version_id: string;
  } | null;
  untrusted_external_content?: boolean;
}

export interface CrawlLaunch extends ApiObject, NextStepInfo {
  job_id: string;
  status: JobStatus;
  crawl_target: string;
  dataset_id: string;
  dataset_version_id: string;
  dataset_artifact: string;
  export_format: string;
  max_items: number;
  max_seconds: number;
  links: Record<string, string>;
}

export interface ArtifactEntry extends ApiObject {
  name: string;
  type: string;
  size_bytes: number;
  download_url: string;
}

export interface ArtifactList extends ApiObject {
  job_id: string;
  artifacts: ArtifactEntry[];
}

export interface AiProfile extends ApiObject {
  profile: string;
  provider: string;
  model: string;
  base_url: string;
  /** A fingerprint of the stored key; the key itself is never returned. */
  key_fingerprint: string;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface AiProfileList extends ApiObject {
  count: number;
  profiles: AiProfile[];
}

export interface AiTestResult extends ApiObject {
  profile: string;
  provider: string;
  model: string;
  ok: boolean;
  model_listed: boolean | null;
  latency_ms: number;
  error?: string | null;
  error_kind?: string | null;
}

export interface AiUsage extends ApiObject {
  days: number;
  totals: { provider: string; model: string; feature: string; calls: number; failed: number; input_tokens: number;
    output_tokens: number }[];
}

export interface DatasetInfo extends ApiObject {
  dataset_id: string;
  dataset_key: string;
  title: string;
  crawl_target: string;
  active_version_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface DatasetFields extends ApiObject {
  fields: { path: string; types: string[]; present: number; examples: Json[] }[];
  truncated: boolean;
}

export interface DatasetDiff extends ApiObject {
  entries: { record_id: string; change: string; from_content_hash: string | null; to_content_hash: string | null;
    quarantined: boolean }[];
  totals: { added: number; removed: number; changed: number };
  next_cursor?: string | null;
}

export interface DatasetExtraction extends ApiObject, NextStepInfo {
  job_id: string;
  status: JobStatus;
  source_dataset_id: string;
  source_version_id: string;
  target_dataset_id: string;
  target_version_id: string;
  links: Record<string, string>;
}

export interface DocumentResult extends ApiObject {
  id: string;
  title: string;
  text: string;
  url: string;
  metadata: ApiObject;
}

export interface QueryFilter {
  field: string;
  op: "eq" | "ne" | "lt" | "lte" | "gt" | "gte" | "contains" | "in" | "exists";
  /** Required by the API for every op (`exists` takes a boolean). */
  value: Json;
}

export interface QueryRecord extends ApiObject {
  record_id: string;
  title: string | null;
  text: string | null;
  url: string | null;
  record: ApiObject;
  provenance: ApiObject;
}

export interface QueryResult extends ApiObject, NextStepInfo {
  records: QueryRecord[];
  scanned?: number;
  next_cursor?: string | null;
}

export interface SearchResult extends ApiObject {
  results: { id: string; title?: string | null; url?: string | null; text?: string | null }[];
}

export interface QuarantineResult extends ApiObject {
  dataset_id: string;
  record_id: string;
  quarantined: boolean;
  reason?: string | null;
}

export interface ScrapeLocalOptions extends Omit<ScrapeOptions, "engine" | "waitForMs"> {
  /** The status your client received (default 200). */
  httpStatus?: number;
  /** The Content-Type your client received. */
  contentType?: string;
  /** The URL after redirects, when it differs. */
  finalUrl?: string;
  idempotencyKey?: string;
}

export interface LocalFetchOptions extends Omit<ScrapeLocalOptions, "httpStatus" | "contentType" | "finalUrl"> {
  /** Honour the site's robots.txt (default true); `false` is your responsibility. */
  respectRobots?: boolean;
  /** At most this many redirects (default 5). */
  maxRedirects?: number;
  /** At most this many bytes of body (default 5 MiB). */
  maxBytes?: number;
  /** The fetch used for the page (default the global fetch); never the one that talks to Scrawl. With your own
   * fetch, a redirect to another host is refused (`cross_origin_redirect`), as it may carry your credentials. */
  fetchPage?: typeof fetch;
}

export interface ScrapeOptions {
  /** Default `["markdown"]`. `"json"` uses YOUR AI provider and needs the `ai:use` scope as well as `scrape:write`. */
  formats?: ScrapeFormat[];
  /** JSON Schema for `formats: ["json"]` (uses YOUR configured AI provider). */
  schema?: JsonSchema;
  instruction?: string;
  /** Your AI provider profile (default profile when omitted). */
  profile?: string;
  /** Wait up to this many seconds for the result before returning `pending`. Default 30. */
  waitSeconds?: number;
  /** `"browser"` renders the page in a sandboxed browser first (only where the server enables it). */
  engine?: ScrapeEngine;
  /** Browser only: wait this many more milliseconds after the page settles (0-10000). */
  waitForMs?: number;
  /** Markdown only: the page's main content (the server's default is `true`); `false` keeps the whole body. */
  onlyMainContent?: boolean;
  /**
   * Markdown only: keep only what these CSS selectors match, in page order, instead of the main content (at most
   * 20 selectors of 200 characters; the server validates them and answers 422 `invalid_request`).
   */
  includeTags?: string[] | null;
  /** Markdown only: drop what these CSS selectors match first (the same subset and bounds as `includeTags`). */
  excludeTags?: string[] | null;
  /** Reuse to make a retried submit return the original response (generated when omitted). */
  idempotencyKey?: string;
}

export type AssetClass = "images" | "video" | "audio" | "documents" | "data" | "web_assets";

export interface AssetOptions {
  /** Default: all six classes. */
  classes?: AssetClass[];
  /** At most this many candidate files are fetched (1-1000, server default 100). */
  maxItems?: number;
  /** At most this many bytes are fetched (server default 50 MiB, at most 150 MiB). */
  maxBytes?: number;
  /** Refuse (422 `budget_exceeded`) when the estimate is above this many credits. */
  maxCredits?: number;
}

export interface AssetQuote extends ApiObject {
  metered: boolean;
  metering: "hosted_saas_account_ledger" | "self_hosted_unmetered";
  estimated_credits: number;
  breakdown: Record<string, number>;
  job_mode: "standard" | "heavy";
  classes: AssetClass[];
  max_items: number;
  max_bytes: number;
  wall_clock_seconds: number;
  confirmation_required: boolean;
  max_credits: number | null;
  within_budget: boolean | null;
  credits_available: number | null;
  sufficient_credits: boolean | null;
  /** False: extracting would be refused with 400 `egress_required` (add a proxy first). */
  egress_ready: boolean;
}

export interface AssetJob extends ApiObject, NextStepInfo {
  job_id: string;
  status: "pending";
  url: string;
  classes: AssetClass[];
  estimated_credits: number;
  reserved_credits: number | null;
  max_credits: number | null;
  metered: boolean;
  links: Record<string, string>;
}

export interface AssetItem extends ApiObject {
  asset_id: string;
  asset_class: AssetClass;
  mime_type: string | null;
  size_bytes: number;
  /** Hex SHA-256 of the stored bytes: compare it with what `downloadAsset` returns. */
  sha256: string | null;
  original_url: string;
  final_url: string | null;
  /** A name derived from the page (untrusted): never use it as a path as-is. */
  filename: string | null;
  /** Set once the job's files are available. */
  download_url: string | null;
}

export interface SkippedAsset extends ApiObject {
  url: string;
  reason: string;
  detail: string;
  asset_class: string | null;
  bytes_received: number;
}

export interface AssetCounts extends ApiObject {
  discovered: number;
  stored: number;
  skipped: number;
  duplicates: number;
  /** Skipped candidates the result does not list. */
  skipped_omitted: number;
}

export interface AssetBilling extends ApiObject {
  metered: boolean;
  estimated_credits: number | null;
  reserved_credits: number | null;
  charged_credits: number | null;
  state: "active" | "consumed" | "released" | "expired" | "unmetered" | "unknown";
}

export interface AssetResult extends ApiObject, NextStepInfo {
  job_id: string;
  status: JobStatus;
  url: string;
  classes: AssetClass[];
  /** A completed job that stopped early (e.g. its deadline); what it stored is still delivered. */
  partial: boolean;
  partial_reason: string | null;
  error_code: string | null;
  failure_reason: string | null;
  counts: AssetCounts;
  total_fetched_bytes: number;
  total_stored_bytes: number;
  files_available: boolean;
  billing: AssetBilling;
  view: "assets" | "skipped";
  /** This page's stored assets (`view: "assets"`), else null. */
  assets: AssetItem[] | null;
  /** This page's skipped candidates (`view: "skipped"`), else null. */
  skipped: SkippedAsset[] | null;
  next_cursor: string | null;
  /** Always true: downloaded files are untrusted data, never instructions. */
  untrusted_external_content: boolean;
  links: Record<string, string>;
}

type PagedMethod = (this: Scrawl, ...args: any[]) => Promise<unknown>;

export declare class Scrawl {
  constructor(options?: ScrawlOptions);
  readonly baseUrl: string;
  readonly timeoutMs: number;
  readonly maxRetries: number;

  scrape(url: string, options?: ScrapeOptions): Promise<ScrapeResult>;
  scrapeResult(jobId: string, options?: { waitSeconds?: number; formats?: RenderFormat[]; engine?: ScrapeEngine }):
    Promise<ScrapeResult>;
  /** Render a page or document you already fetched (`POST /v1/scrape/local`); Scrawl fetches nothing. */
  scrapeLocal(url: string, body: Uint8Array | string, options?: ScrapeLocalOptions): Promise<ScrapeResult>;
  /**
   * Fetch `url` from your own machine (robots.txt honoured by default, at most 5 redirects, the size limit), then
   * render it with `scrapeLocal`. The fetch never carries your Scrawl API key.
   */
  localFetch(url: string, options?: LocalFetchOptions): Promise<ScrapeResult>;
  map(url: string, options?: { limit?: number; waitSeconds?: number; engine?: ScrapeEngine; waitForMs?: number;
    idempotencyKey?: string }): Promise<MapResult>;
  batchScrape(urls: string[], options?: Omit<ScrapeOptions, "waitSeconds">): Promise<BatchStatus>;
  batchStatus(batchId: string, options?: { waitSeconds?: number }): Promise<BatchStatus>;

  extract(jobId: string, options?: { artifact?: string; schema?: JsonSchema; instruction?: string; profile?: string }): Promise<ExtractResult>;
  ask(question: string, options?: { datasetId?: string; profile?: string }): Promise<AskResult>;
  listAiProviders(): Promise<AiProfileList>;
  /** Create or replace a profile. The key is stored encrypted on the server and never returned. */
  setAiProvider(profile: string, options: { provider: string; apiKey: string; model?: string; baseUrl?: string }): Promise<AiProfile>;
  /** Resolves to null (204 No Content). */
  deleteAiProvider(profile: string): Promise<null>;
  setDefaultAiProvider(profile: string): Promise<AiProfile>;
  testAiProvider(profile: string): Promise<AiTestResult>;
  aiUsage(options?: { days?: number }): Promise<AiUsage>;

  getProxy(): Promise<ProxyInfo>;
  setProxy(options: { url?: string; scheme?: ProxyScheme; host?: string; port?: number; username?: string;
    password?: string; label?: string }): Promise<ProxyInfo>;
  testProxy(): Promise<ProxyTestResult>;
  removeProxy(): Promise<ApiObject | null>;
  listProxyPool(): Promise<ProxyPool>;
  addProxyPoolEntry(options: { url: string; label?: string; poolId?: string }): Promise<null>;
  testProxyPoolEntry(entryRef: string): Promise<ProxyPoolTestResult>;
  enableProxyPoolEntry(entryRef: string): Promise<ProxyPoolEntry>;
  disableProxyPoolEntry(entryRef: string): Promise<ProxyPoolEntry>;
  removeProxyPoolEntry(entryRef: string): Promise<null>;
  setProxyPoolMode(mode: ProxyPoolMode): Promise<ProxyPool>;
  proxyHealth(): Promise<ProxyHealth>;

  /** Hosted keys are created in Telegram with /api_keys create; listing and revoking need a keys:manage key
   * (/api_keys create_manager). The SDK deliberately has no create method. */
  listApiKeys(): Promise<ApiKeyList>;
  revokeApiKey(keyId: string): Promise<null>;

  crawl(crawlTarget: string, options?: { exportFormat?: ExportFormat; maxItems?: number; maxSeconds?: number; idempotencyKey?: string }): Promise<CrawlLaunch>;
  getJob(jobId: string, options?: { waitSeconds?: number }): Promise<Job>;
  /** `status` filters by a job status; either case is accepted. */
  listJobs(options?: { limit?: number; status?: JobStatus | Uppercase<JobStatus>; cursor?: string }): Promise<{ jobs: Job[]; next_cursor?: string | null } & ApiObject>;
  curateDataset(datasetId: string, operation: "remove" | "dedupe" | "reextract", options?: { versionId?: string; recordIds?: string[]; field?: string; onlyMainContent?: boolean; includeTags?: string[]; excludeTags?: string[] }): Promise<DatasetCuration>;
  listCurations(datasetId: string, options?: { limit?: number; cursor?: string }): Promise<Page<DatasetCuration> & { curations: DatasetCuration[] }>;
  crawlSite(url: string, options?: { maxPages?: number; maxDepth?: number; engine?: ScrapeEngine; waitForMs?: number; onlyMainContent?: boolean; includeTags?: string[]; excludeTags?: string[]; resumeFrom?: string; idempotencyKey?: string }): Promise<SiteCrawl>;
  siteCrawlStatus(crawlId: string, options?: { waitSeconds?: number; limit?: number; cursor?: string }): Promise<SiteCrawl>;
  waitForSiteCrawl(crawlId: string, options?: { timeoutMs?: number }): Promise<SiteCrawl>;
  /** Needs the scope that starts that kind of job: `ai:use` for a dataset extraction, else `scrape:write`. */
  cancelJob(jobId: string): Promise<CancelResult>;
  listArtifacts(jobId: string): Promise<ArtifactList>;
  /** One artifact's bytes, buffered in memory (`format: "markdown"` converts HTML). */
  downloadArtifact(jobId: string, filename: string, options?: { format?: "raw" | "markdown" }): Promise<ArrayBuffer>;

  listDatasets(options?: { limit?: number; cursor?: string }): Promise<{ count: number; datasets: DatasetInfo[]; next_cursor?: string | null } & ApiObject>;
  getDataset(datasetId: string): Promise<DatasetManifest>;
  listVersions(datasetId: string, options?: { limit?: number; cursor?: string; status?: JobStatus | Uppercase<JobStatus> }): Promise<{ count: number; versions: DatasetVersion[]; next_cursor?: string | null } & ApiObject>;
  activateVersion(datasetId: string, versionId: string): Promise<{ dataset: DatasetInfo } & ApiObject>;
  diffVersions(datasetId: string, fromVersion: string, toVersion: string, options?: { limit?: number; cursor?: string }): Promise<DatasetDiff>;
  datasetFields(datasetId: string, options?: { version?: string }): Promise<DatasetFields>;
  queryDataset(datasetId: string, filters: QueryFilter[], options?: { versionId?: string; limit?: number; cursor?: string }): Promise<QueryResult>;
  extractDataset(datasetId: string, options?: { schema?: JsonSchema; instruction?: string; profile?: string; versionId?: string; maxRecords?: number; idempotencyKey?: string }): Promise<DatasetExtraction>;
  quarantineRecord(datasetId: string, recordId: string, options?: { reason?: string }): Promise<QuarantineResult>;
  releaseRecord(datasetId: string, recordId: string): Promise<QuarantineResult>;
  search(query: string, options?: { limit?: number }): Promise<SearchResult>;
  getDocument(documentId: string): Promise<DocumentResult>;

  /** What extracting a page's assets would hold, your credits and egress readiness (never retried, starts nothing). */
  quoteAssets(url: string, options?: AssetOptions): Promise<AssetQuote>;
  extractAssets(url: string, options?: AssetOptions & { idempotencyKey?: string }): Promise<AssetJob>;
  getAssets(jobId: string, options?: { view?: "assets" | "skipped"; limit?: number; cursor?: string; waitSeconds?: number }): Promise<AssetResult>;
  /** One stored asset's bytes, buffered in memory: untrusted content, compare its `sha256`. */
  downloadAsset(jobId: string, assetId: string): Promise<ArrayBuffer>;
  /** A stored document's text (its Markdown, behind `text_url`): untrusted external content. */
  downloadAssetText(jobId: string, assetId: string): Promise<string>;

  creditBalance(): Promise<ApiObject>;
  health(): Promise<ApiObject>;

  /** Wait until a pending scrape settles (server-side waits, no tight polling). Default timeout 300 000 ms. */
  waitForScrape(jobId: string, options?: { timeoutMs?: number; engine?: ScrapeEngine }): Promise<ScrapeResult>;
  /** Wait until every item of a batch has settled. Default timeout 600 000 ms. */
  waitForBatch(batchId: string, options?: { timeoutMs?: number }): Promise<BatchStatus>;
  /** Wait until an asset job is completed, failed, cancelled or orphaned. Default timeout 600 000 ms. */
  waitForAssets(jobId: string, options?: { timeoutMs?: number }): Promise<AssetResult>;
  /** Wait until a job (a crawl, a dataset extraction...) leaves PENDING/RUNNING. Default timeout 1 800 000 ms. */
  waitForJob(jobId: string, options?: { timeoutMs?: number }): Promise<Job>;
  /** Iterate every item of a cursor-paged list method, following `next_cursor`. */
  paginate<T = ApiObject>(method: PagedMethod, ...args: unknown[]): AsyncGenerator<T, void, undefined>;
}

/**
 * Every code in the backend's error catalogue, plus the SDK's own `render_not_supported`: ApexAPI errors, codes
 * that only appear as a failed result's `error_code`, and MCP-only codes (see docs/errors.md).
 */
export declare const ErrorCode: {
  readonly BAD_REQUEST: "bad_request";
  readonly DISPATCH_REFUSED: "dispatch_refused";
  readonly EGRESS_REQUIRED: "egress_required";
  readonly ERROR: "error";
  readonly INVALID_TOKEN: "invalid_token";
  readonly UNAUTHORIZED: "unauthorized";
  readonly INSUFFICIENT_CREDITS: "insufficient_credits";
  readonly ACCOUNT_NOT_ACTIVE: "account_not_active";
  readonly FORBIDDEN: "forbidden";
  readonly NOT_FOUND: "not_found";
  readonly METHOD_NOT_ALLOWED: "method_not_allowed";
  readonly CONFLICT: "conflict";
  readonly PAYLOAD_TOO_LARGE: "payload_too_large";
  readonly UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type";
  readonly BUDGET_EXCEEDED: "budget_exceeded";
  readonly INVALID_ARTIFACT_NAME: "invalid_artifact_name";
  readonly INVALID_REQUEST: "invalid_request";
  readonly UNSAFE_ARTIFACT_PATH: "unsafe_artifact_path";
  readonly RATE_LIMITED: "rate_limited";
  readonly TOO_MANY_ACTIVE_JOBS: "too_many_active_jobs";
  readonly INTERNAL_ERROR: "internal_error";
  readonly SUBMISSION_FAILED: "submission_failed";
  readonly AI_AUTH: "ai_auth";
  readonly AI_BAD_REQUEST: "ai_bad_request";
  readonly AI_CONTEXT_OVERFLOW: "ai_context_overflow";
  readonly AI_DAILY_BUDGET_EXCEEDED: "ai_daily_budget_exceeded";
  readonly AI_ENDPOINT_FORBIDDEN: "ai_endpoint_forbidden";
  readonly AI_KILL_SWITCH_ENGAGED: "ai_kill_switch_engaged";
  readonly AI_MALFORMED_OUTPUT: "ai_malformed_output";
  readonly AI_PROVIDER_ERROR: "ai_provider_error";
  readonly AI_QUOTA: "ai_quota";
  readonly AI_RATE_LIMITED: "ai_rate_limited";
  readonly AI_REFUSED: "ai_refused";
  readonly AI_TIMEOUT: "ai_timeout";
  readonly AI_UNAVAILABLE: "ai_unavailable";
  readonly AI_UNSUPPORTED: "ai_unsupported";
  readonly BROWSER_UNAVAILABLE: "browser_unavailable";
  readonly TEMPORARILY_UNAVAILABLE: "temporarily_unavailable";
  readonly UNAVAILABLE: "unavailable";
  readonly EGRESS_UNAVAILABLE: "egress_unavailable";
  readonly FETCH_FAILED: "fetch_failed";
  readonly INTERNAL: "internal";
  readonly INTERRUPTED: "interrupted";
  readonly JOB_TIMEOUT: "job_timeout";
  readonly KEY_REVOKED: "key_revoked";
  readonly LISTEN_EXPIRED: "listen_expired";
  readonly PREFLIGHT_DENIED: "preflight_denied";
  readonly RENDER_INTERRUPTED: "render_interrupted";
  readonly ROBOTS_DISALLOWED: "robots_disallowed";
  readonly SETTLEMENT_FAILED: "settlement_failed";
  readonly TOO_MANY_STREAMS: "too_many_streams";
  readonly RENDER_NOT_SUPPORTED: "render_not_supported";
};
/** A code this SDK knows; `ScrawlError.code` may also be a newer one, so it is typed as any string. */
export type ErrorCode = (typeof ErrorCode)[keyof typeof ErrorCode];

export interface ScrawlErrorOptions {
  status?: number | null;
  code?: string | null;
  requestId?: string | null;
  details?: unknown;
  retryAfter?: number | null;
}

/** Any failed Scrawl call. `retryAfter` is set when the response supplied Retry-After. */
export declare class ScrawlError extends Error {
  constructor(message: string, options?: ScrawlErrorOptions);
  readonly status: number | null;
  readonly code: ErrorCode | (string & {}) | null;
  readonly requestId: string | null;
  readonly details: unknown;
  readonly retryAfter: number | null;
}
/** The client cannot be used as configured (no API key, an unusable base URL); nothing was sent. */
export declare class ConfigurationError extends ScrawlError {}
/** 400: refused before any work started (`egress_required`, `dispatch_refused`, `bad_request`). */
export declare class BadRequestError extends ScrawlError {}
/** 401: missing, invalid or revoked API key. */
export declare class AuthenticationError extends ScrawlError {}
/** 403: the key lacks the scope, or the server has the feature turned off. */
export declare class PermissionDeniedError extends ScrawlError {}
/** 404: unknown or not yours. */
export declare class NotFoundError extends ScrawlError {}
/** 402: `insufficient_credits`; the hosted account cannot cover this job. */
export declare class PaymentRequiredError extends ScrawlError {}
/** 409: e.g. an Idempotency-Key whose first request is still running. */
export declare class ConflictError extends ScrawlError {}
/** 422: the request is invalid (or an Idempotency-Key was reused for a different request). */
export declare class ValidationError extends ScrawlError {}
/** 429: rate limited or `too_many_active_jobs`; `retryAfter` in seconds when the API says. */
export declare class RateLimitError extends ScrawlError {
  constructor(message: string, options?: ScrawlErrorOptions & { retryAfter?: number | null });
  readonly retryAfter: number | null;
}
/** 5xx from Scrawl (including `ai_*` failures of your own AI provider, which are 502). */
export declare class ServerError extends ScrawlError {}
/** The request never got a response (network, DNS, TLS). */
export declare class APIConnectionError extends ScrawlError {}
/** The request timed out. */
export declare class APITimeoutError extends APIConnectionError {}

export declare function errorFor(status: number, body: unknown, options?: { requestId?: string | null; retryAfter?: number | null }): ScrawlError;
