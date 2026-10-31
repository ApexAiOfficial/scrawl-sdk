# Errors

Every failed call raises (Python) or rejects with (TypeScript) a `ScrawlError`. It carries:

| Field | Python | TypeScript | Meaning |
| --- | --- | --- | --- |
| HTTP status | `status` | `status` | `None`/`null` when no response arrived |
| Code | `code` | `code` | The API's stable machine code, a plain string (see the table below) |
| Message | `message` | `message` | Human-readable; never contains your API key |
| Request ID | `request_id` | `requestId` | From the `X-Request-ID` header, else from the error body; quote it when you report a problem |
| Details | `details` | `details` | Extra structure, e.g. the fields a 422 rejected |
| Retry after | `retry_after` | `retryAfter` | `RateLimitError` only: seconds, when the API says |

Compare codes with the `ErrorCode` constants (`error.code == ErrorCode.NOT_FOUND` in Python,
`error.code === ErrorCode.NOT_FOUND` in TypeScript). `code` stays a plain string, so a code added by a newer
server is still readable by an older SDK.

## Classes

| Status | Class (both SDKs) | Typical codes |
| --- | --- | --- |
| 400 | `BadRequestError` | `egress_required`, `dispatch_refused`, `bad_request`, `error` |
| 401 | `AuthenticationError` | `unauthorized` |
| 402 | `PaymentRequiredError` | `insufficient_credits` |
| 403 | `PermissionDeniedError` | `forbidden`, `account_not_active` |
| 404 | `NotFoundError` | `not_found` |
| 409 | `ConflictError` | `conflict` |
| 422 | `ValidationError` | `invalid_request`, `budget_exceeded`, `invalid_artifact_name` |
| 429 | `RateLimitError` | `rate_limited`, `too_many_active_jobs` |
| 5xx | `ServerError` | `internal_error`, `submission_failed`, `ai_*`, `unavailable`, `browser_unavailable` |
| other | `ScrawlError` | anything else |
| none | `APIConnectionError`, `APITimeoutError` | no response: network, DNS, TLS, timeout |
| none | `ConfigurationError` | no API key, a key an HTTP header cannot carry, or an unusable base URL; nothing was sent |

All classes subclass `ScrawlError`; `APITimeoutError` subclasses `APIConnectionError`.

## Retries

The SDKs retry for you, with backoff that honours `Retry-After` (`max_retries`/`maxRetries`, default 2):

- **GETs** retry on 429, 502, 503, 504 and network errors.
- **Submits that start work** (scrape, map, batch, crawl, dataset and asset extraction) carry an
  `Idempotency-Key`, so a retry never starts the work twice. They retry on 429, network errors and a
  proxy's 502/503/504. A 5xx in Scrawl's own error format is final: the key now records that outcome.
  When a retry meets the first attempt still running (409), the SDK waits for its stored response.
- **Other POSTs** and other 4xx are never retried.
- **A code marked not retryable is never retried**, whatever its status, on a GET or a submit: the error is
  raised (or rejected) at once. That includes `submission_failed` and `settlement_failed`, after which a
  resend may charge twice, and `internal_error` (500) and `unavailable` (503), after which the first request
  may already have started work: list your jobs (or read the job's `failure_reason`) first, then send it
  again with a new `Idempotency-Key` only if the work did not happen. A response that carries no code (a
  proxy's page, an empty body) or a code this SDK version does not know yet follows the rules above, and a
  code marked retryable is retried only where they allow it.

## Codes

Every code in the backend's error catalogue is an `ErrorCode` constant in both SDKs. In the table:

- **Retryable**: `yes` when the same request can succeed if sent again later unchanged (honour
  `Retry-After`); `no` when it cannot, and the SDKs never resend it for you.
- **Where** the code appears: **API**, an ApexAPI error response, raised as the class shown; **result**, the
  `error_code` of a failed job, scrape or asset result (not raised); **MCP**, the MCP server only (listed for
  completeness; the SDKs do not use MCP); **SDK**, raised by the SDKs themselves.

<!-- BEGIN GENERATED: error codes (tools/gen_error_docs.py) -->
Generated from the vendored error catalogue (`contracts/apexapi_errors.json`) and `coverage.json`; do not edit by hand.

| Code | HTTP | Retryable | Where | Class (both SDKs) | Constant | Meaning |
| --- | --- | --- | --- | --- | --- | --- |
| `bad_request` | 400 | no | API | `BadRequestError` | `ErrorCode.BAD_REQUEST` | The request was refused as it stands, for example a refused job or an invalid artifact file name. |
| `dispatch_refused` | 400 | no | API, MCP | `BadRequestError` | `ErrorCode.DISPATCH_REFUSED` | A policy gate refused the job before it started, for example a crawl target that is not allowed. |
| `egress_required` | 400 | no | API, MCP | `BadRequestError` | `ErrorCode.EGRESS_REQUIRED` | The job needs a validated proxy and the caller has none; nothing was sent. |
| `error` | 400 | no | API | `BadRequestError` | `ErrorCode.ERROR` | An error without a more specific code. |
| `invalid_token` | 401 | no | MCP | - | `ErrorCode.INVALID_TOKEN` | MCP over HTTP: the bearer key was not accepted. |
| `unauthorized` | 401 | no | API, MCP | `AuthenticationError` | `ErrorCode.UNAUTHORIZED` | No credential was sent, or the API key or admin token was not accepted. |
| `insufficient_credits` | 402 | no | API, MCP | `PaymentRequiredError` | `ErrorCode.INSUFFICIENT_CREDITS` | The account does not have the credits this job needs. |
| `account_not_active` | 403 | no | API, MCP | `PermissionDeniedError` | `ErrorCode.ACCOUNT_NOT_ACTIVE` | The key's hosted account is suspended, banned, or has not accepted the Trust Pledge. |
| `forbidden` | 403 | no | API, MCP | `PermissionDeniedError` | `ErrorCode.FORBIDDEN` | The key is valid but may not do this: a missing scope, a disabled endpoint or command, or a key not bound to a hosted account. |
| `not_found` | 404 | no | API, MCP | `NotFoundError` | `ErrorCode.NOT_FOUND` | The resource does not exist or is not the caller's (the two are never distinguished), or there is no such route. |
| `method_not_allowed` | 405 | no | API | `ScrawlError` | `ErrorCode.METHOD_NOT_ALLOWED` | The route does not accept this HTTP method. |
| `conflict` | 409 | yes | API, MCP | `ConflictError` | `ErrorCode.CONFLICT` | The request conflicts with one still in progress (the same Idempotency-Key) or with a job that has not finished. |
| `payload_too_large` | 413 | no | API | `ScrawlError` | `ErrorCode.PAYLOAD_TOO_LARGE` | The request body is larger than the route accepts. |
| `unsupported_media_type` | 415 | no | API | `ScrawlError` | `ErrorCode.UNSUPPORTED_MEDIA_TYPE` | The request body's content type is not accepted. |
| `budget_exceeded` | 422 | no | API, MCP | `ValidationError` | `ErrorCode.BUDGET_EXCEEDED` | The job's estimate is above the request's max_credits; nothing was reserved. |
| `invalid_artifact_name` | 422 | no | API, MCP | `ValidationError` | `ErrorCode.INVALID_ARTIFACT_NAME` | An artifact must be named by a single file name from the job's artifact list. |
| `invalid_request` | 422 | no | API, MCP | `ValidationError` | `ErrorCode.INVALID_REQUEST` | The request is malformed or outside a documented bound; field errors never echo the submitted values. |
| `unsafe_artifact_path` | 422 | no | API, MCP | `ValidationError` | `ErrorCode.UNSAFE_ARTIFACT_PATH` | The artifact name resolves outside its job's files. |
| `rate_limited` | 429 | yes | API, MCP | `RateLimitError` | `ErrorCode.RATE_LIMITED` | Too many requests for this account; wait Retry-After seconds, then retry. |
| `too_many_active_jobs` | 429 | yes | API, MCP | `RateLimitError` | `ErrorCode.TOO_MANY_ACTIVE_JOBS` | The caller already has the maximum number of running or queued jobs, or the browser renderer is busy; retry after Retry-After seconds. |
| `internal_error` | 500 | no | API, result | `ServerError` | `ErrorCode.INTERNAL_ERROR` | An unexpected failure, possibly after work started: list your jobs before sending a job request again. Quote the request ID when reporting it. |
| `submission_failed` | 500 | no | API | `ServerError` | `ErrorCode.SUBMISSION_FAILED` | The first request with this Idempotency-Key failed after it may have started work; list your jobs, then retry with a new key. |
| `ai_auth` | 502 | no | API, MCP, result | `ServerError` | `ErrorCode.AI_AUTH` | Your AI provider rejected the key, or the key may not use this model. |
| `ai_bad_request` | 502 | no | API, MCP, result | `ServerError` | `ErrorCode.AI_BAD_REQUEST` | Your AI provider refused the request, for example an unknown model. |
| `ai_context_overflow` | 502 | no | API, MCP, result | `ServerError` | `ErrorCode.AI_CONTEXT_OVERFLOW` | The input is too large for the model's context window. |
| `ai_endpoint_forbidden` | 502 | no | API, MCP, result | `ServerError` | `ErrorCode.AI_ENDPOINT_FORBIDDEN` | The AI profile's base URL is not allowed by the endpoint policy. |
| `ai_malformed_output` | 502 | no | API, MCP, result | `ServerError` | `ErrorCode.AI_MALFORMED_OUTPUT` | The model's answer was not the JSON that was asked for, even after one repair. |
| `ai_provider_error` | 502 | no | API, MCP, result | `ServerError` | `ErrorCode.AI_PROVIDER_ERROR` | Your AI provider failed for a reason without a more specific AI failure code. |
| `ai_quota` | 502 | no | API, MCP, result | `ServerError` | `ErrorCode.AI_QUOTA` | Your AI provider account cannot pay for the call. |
| `ai_rate_limited` | 502 | yes | API, MCP, result | `ServerError` | `ErrorCode.AI_RATE_LIMITED` | Your AI provider rate-limited the call. |
| `ai_refused` | 502 | no | API, MCP, result | `ServerError` | `ErrorCode.AI_REFUSED` | Your AI provider refused to answer (a content filter or safety refusal). |
| `ai_timeout` | 502 | yes | API, MCP, result | `ServerError` | `ErrorCode.AI_TIMEOUT` | Your AI provider did not answer in time. |
| `ai_unavailable` | 502 | yes | API, MCP, result | `ServerError` | `ErrorCode.AI_UNAVAILABLE` | Your AI provider is unavailable: an outage or a connection failure. |
| `browser_unavailable` | 503 | no | API, MCP | `ServerError` | `ErrorCode.BROWSER_UNAVAILABLE` | This deployment cannot render pages in a browser; use the static engine. |
| `temporarily_unavailable` | 503 | yes | MCP | - | `ErrorCode.TEMPORARILY_UNAVAILABLE` | MCP over HTTP: the key store is unavailable; retry after Retry-After seconds. |
| `unavailable` | 503 | no | API, MCP | `ServerError` | `ErrorCode.UNAVAILABLE` | A feature or service the request needs is turned off, not configured or not running on this deployment; try again later only if the message says to. |
| `egress_unavailable` | none | yes | result | - | `ErrorCode.EGRESS_UNAVAILABLE` | The job's proxy could not be used, so the page was not fetched. |
| `fetch_failed` | none | yes | result | - | `ErrorCode.FETCH_FAILED` | The page could not be fetched: a network error, a timeout or an error response. |
| `internal` | none | no | MCP | - | `ErrorCode.INTERNAL` | An MCP tool failed unexpectedly, possibly after it started work; the details are only in the server log. |
| `interrupted` | none | yes | result | - | `ErrorCode.INTERRUPTED` | The job stopped before it finished, for example on a service restart. |
| `job_timeout` | none | yes | result | - | `ErrorCode.JOB_TIMEOUT` | The job did not finish within its time limit. |
| `key_revoked` | none | no | MCP | - | `ErrorCode.KEY_REVOKED` | The key of an open listen stream was revoked; use an active key. |
| `listen_expired` | none | yes | MCP | - | `ErrorCode.LISTEN_EXPIRED` | A listen stream reached its lifetime; listen again. |
| `preflight_denied` | none | no | result | - | `ErrorCode.PREFLIGHT_DENIED` | The destination policy refused the page before any fetch. |
| `render_interrupted` | none | yes | result | - | `ErrorCode.RENDER_INTERRUPTED` | A scrape's JSON step was interrupted; scrape the URL again, or extract from the job. |
| `render_not_supported` | none | no | SDK | `ScrawlError` | `ErrorCode.RENDER_NOT_SUPPORTED` | Raised by the SDKs, not the API: you asked for engine=browser, but the finished result came from another engine. |
| `settlement_failed` | none | no | result | - | `ErrorCode.SETTLEMENT_FAILED` | The job's charge could not be settled or confirmed; its failure_reason says whether anything was charged. Check it before sending the request again. |
| `too_many_streams` | none | yes | MCP | - | `ErrorCode.TOO_MANY_STREAMS` | The caller already holds the maximum number of open listen streams; close one first. |
<!-- END GENERATED: error codes -->

`ai_*` codes describe a failure of **your own** AI provider (bring-your-own AI); fix the profile with
`set_ai_provider` / `setAiProvider` or `scrawl ai providers set`, then `test`.

## Failed jobs are results, not errors

A job that runs and fails is not an exception: the result says `"status": "failed"` with an `error_code`
(for example `fetch_failed`, `job_timeout`, `interrupted`, `egress_unavailable`, `preflight_denied`,
`render_interrupted`, `settlement_failed` or `internal_error`) and a human-readable `error` or
`failure_reason`. A scrape whose JSON step failed still carries the other formats you asked for. Neither the
SDKs nor the CLI ever resubmit a failed job; the Retryable column says whether resubmitting can help. After
`settlement_failed`, read `failure_reason` first: it says whether anything was charged.

## CLI exit codes

| Exit | Meaning |
| --- | --- |
| 0 | Success |
| 1 | The job (or a batch item) failed, or a downloaded file did not match its size or SHA-256 (it was not written) |
| 2 | Usage error, or a file already exists where a download would go (nothing is overwritten) |
| 3 | Authentication or configuration: 401/403, no API key, an unusable base URL or AI key |
| 4 | Still pending or running at the deadline |
| 5 | Any other API or connection error |
