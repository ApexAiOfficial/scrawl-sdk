// Typed errors carrying the API's stable error `code` (never the API key).

/**
 * Every code in the backend's error catalogue, plus the SDK's own `render_not_supported`. Most are ApexAPI errors,
 * thrown as a `ScrawlError`; some only appear as the `error_code` of a failed result (`fetch_failed`,
 * `settlement_failed`...) or only on the MCP server (`key_revoked`...). `ScrawlError.code` is a plain string, so it
 * compares equal to these values and stays readable when the API adds a code this SDK version does not list yet.
 * The table with each code's status, retryability and meaning is docs/errors.md.
 */
export const ErrorCode = Object.freeze({
  BAD_REQUEST: "bad_request",
  DISPATCH_REFUSED: "dispatch_refused",
  EGRESS_REQUIRED: "egress_required",
  ERROR: "error",
  INVALID_TOKEN: "invalid_token",
  UNAUTHORIZED: "unauthorized",
  INSUFFICIENT_CREDITS: "insufficient_credits",
  ACCOUNT_NOT_ACTIVE: "account_not_active",
  FORBIDDEN: "forbidden",
  NOT_FOUND: "not_found",
  METHOD_NOT_ALLOWED: "method_not_allowed",
  CONFLICT: "conflict",
  PAYLOAD_TOO_LARGE: "payload_too_large",
  UNSUPPORTED_MEDIA_TYPE: "unsupported_media_type",
  BUDGET_EXCEEDED: "budget_exceeded",
  INVALID_ARTIFACT_NAME: "invalid_artifact_name",
  INVALID_REQUEST: "invalid_request",
  UNSAFE_ARTIFACT_PATH: "unsafe_artifact_path",
  RATE_LIMITED: "rate_limited",
  TOO_MANY_ACTIVE_JOBS: "too_many_active_jobs",
  INTERNAL_ERROR: "internal_error",
  SUBMISSION_FAILED: "submission_failed",
  AI_AUTH: "ai_auth",
  AI_BAD_REQUEST: "ai_bad_request",
  AI_CONTEXT_OVERFLOW: "ai_context_overflow",
  AI_ENDPOINT_FORBIDDEN: "ai_endpoint_forbidden",
  AI_MALFORMED_OUTPUT: "ai_malformed_output",
  AI_PROVIDER_ERROR: "ai_provider_error",
  AI_QUOTA: "ai_quota",
  AI_RATE_LIMITED: "ai_rate_limited",
  AI_REFUSED: "ai_refused",
  AI_TIMEOUT: "ai_timeout",
  AI_UNAVAILABLE: "ai_unavailable",
  BROWSER_UNAVAILABLE: "browser_unavailable",
  TEMPORARILY_UNAVAILABLE: "temporarily_unavailable",
  UNAVAILABLE: "unavailable",
  EGRESS_UNAVAILABLE: "egress_unavailable",
  FETCH_FAILED: "fetch_failed",
  INTERNAL: "internal",
  INTERRUPTED: "interrupted",
  JOB_TIMEOUT: "job_timeout",
  KEY_REVOKED: "key_revoked",
  LISTEN_EXPIRED: "listen_expired",
  PREFLIGHT_DENIED: "preflight_denied",
  RENDER_INTERRUPTED: "render_interrupted",
  SETTLEMENT_FAILED: "settlement_failed",
  TOO_MANY_STREAMS: "too_many_streams",
  RENDER_NOT_SUPPORTED: "render_not_supported",
});

/**
 * The catalogue's `retryable` flag of every ErrorCode: whether the same request can succeed if sent again later
 * unchanged. The client never retries automatically on a code marked false (`submission_failed` and
 * `settlement_failed` above all: a resend may charge twice), and retries a true one only where the HTTP status
 * allows it. Kept equal to contracts/apexapi_errors.json and the Python SDK by the tests. Internal: not exported
 * from the package.
 */
export const RETRYABLE = Object.freeze({
  bad_request: false,
  dispatch_refused: false,
  egress_required: false,
  error: false,
  invalid_token: false,
  unauthorized: false,
  insufficient_credits: false,
  account_not_active: false,
  forbidden: false,
  not_found: false,
  method_not_allowed: false,
  conflict: true,
  payload_too_large: false,
  unsupported_media_type: false,
  budget_exceeded: false,
  invalid_artifact_name: false,
  invalid_request: false,
  unsafe_artifact_path: false,
  rate_limited: true,
  too_many_active_jobs: true,
  internal_error: false,
  submission_failed: false,
  ai_auth: false,
  ai_bad_request: false,
  ai_context_overflow: false,
  ai_endpoint_forbidden: false,
  ai_malformed_output: false,
  ai_provider_error: false,
  ai_quota: false,
  ai_rate_limited: true,
  ai_refused: false,
  ai_timeout: true,
  ai_unavailable: true,
  browser_unavailable: false,
  temporarily_unavailable: true,
  unavailable: false,
  egress_unavailable: true,
  fetch_failed: true,
  internal: false,
  interrupted: true,
  job_timeout: true,
  key_revoked: false,
  listen_expired: true,
  preflight_denied: false,
  render_interrupted: true,
  settlement_failed: false,
  too_many_streams: true,
  render_not_supported: false,
});

/** True when the error catalogue marks `code` not retryable; a code this SDK does not know is left to the status. */
export function neverRetry(code) {
  return typeof code === "string" && Object.hasOwn(RETRYABLE, code) && RETRYABLE[code] === false;
}

/** The error code of an API error body, in either shape: `{"error": {code...}}` or `{"detail", "code"}`. */
export function codeOf(body) {
  if (!body || typeof body !== "object" || Array.isArray(body)) return null;
  const envelope = body.error && typeof body.error === "object" ? body.error : null;
  const code = envelope ? envelope.code : body.code;
  return typeof code === "string" ? code : null;
}

/** Any failed Scrawl call. `code` is the API's stable machine code (e.g. `not_found`). */
export class ScrawlError extends Error {
  constructor(message, { status = null, code = null, requestId = null, details = null } = {}) {
    super(message);
    this.name = new.target.name;
    this.status = status;
    this.code = typeof code === "string" ? code : null;
    this.requestId = requestId;
    this.details = details;
  }

  toString() {
    const parts = [this.message];
    if (this.code) parts.unshift(`[${this.code}]`);
    if (this.requestId) parts.push(`(request ${this.requestId})`);
    return `${this.name}: ${parts.join(" ")}`;
  }
}

/** The client cannot be used as configured (no API key, an unusable base URL); nothing was sent. */
export class ConfigurationError extends ScrawlError {}
/** 400: refused before any work started (`egress_required`, `dispatch_refused`, `bad_request`). */
export class BadRequestError extends ScrawlError {}
/** 401: missing, invalid or revoked API key. */
export class AuthenticationError extends ScrawlError {}
/** 402: `insufficient_credits`; the hosted account cannot cover this job. */
export class PaymentRequiredError extends ScrawlError {}
/** 403: the key lacks the scope, or the server has the feature turned off. */
export class PermissionDeniedError extends ScrawlError {}
/** 404: unknown or not yours (Scrawl never reveals other owners' resources). */
export class NotFoundError extends ScrawlError {}
/** 409: e.g. an Idempotency-Key whose first request is still running. */
export class ConflictError extends ScrawlError {}
/** 422: the request is invalid (or an Idempotency-Key was reused for a different request). */
export class ValidationError extends ScrawlError {}

/** 429: rate limited or `too_many_active_jobs`; `retryAfter` is in seconds when the API says. */
export class RateLimitError extends ScrawlError {
  constructor(message, { retryAfter = null, ...rest } = {}) {
    super(message, rest);
    this.retryAfter = retryAfter;
  }
}

/** 5xx from Scrawl (including `ai_*` failures of your own AI provider, which are 502). */
export class ServerError extends ScrawlError {}
/** The request never got a response (network, DNS, TLS). */
export class APIConnectionError extends ScrawlError {}
/** The request timed out. */
export class APITimeoutError extends APIConnectionError {}

const BY_STATUS = {
  400: BadRequestError, 401: AuthenticationError, 402: PaymentRequiredError, 403: PermissionDeniedError,
  404: NotFoundError, 409: ConflictError, 422: ValidationError, 429: RateLimitError,
};

/**
 * Map an HTTP error response to the matching `ScrawlError` subclass. Reads both shapes the API uses:
 * `{"error": {code, message, request_id, details?}}` and `{"detail": ..., "code": ...}`. The `X-Request-ID`
 * header wins; the envelope's `request_id` is the fallback.
 */
export function errorFor(status, body, { requestId = null, retryAfter = null } = {}) {
  let code = null;
  let message = null;
  let details = null;
  if (body && typeof body === "object" && !Array.isArray(body)) {
    const envelope = body.error && typeof body.error === "object" ? body.error : null;
    if (envelope) {
      ({ code = null, message = null, details = null } = envelope);
      requestId = requestId || envelope.request_id || null;
    } else {
      code = body.code ?? null;
      const detail = body.detail;
      if (typeof detail === "string") message = detail;
      else if (detail !== undefined) details = detail;
    }
  }
  message = message || `HTTP ${status}`;
  const Cls = BY_STATUS[status] || (status >= 500 ? ServerError : ScrawlError);
  const options = { status, code, requestId, details };
  return Cls === RateLimitError ? new RateLimitError(message, { ...options, retryAfter }) : new Cls(message, options);
}
