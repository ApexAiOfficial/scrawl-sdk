// Typed errors, the stable error code, and retries that never start the work twice:
// `node examples/errors-and-retries.mjs https://example.com`
import { randomUUID } from "node:crypto";

import {
  APIConnectionError, AuthenticationError, ErrorCode, NotFoundError, RateLimitError, Scrawl, ScrawlError, ServerError,
} from "@apexaiofficial/scrawl";

const url = process.argv[2];
// GETs and submits that start work retry 429, 502/503/504 and network errors with backoff (Retry-After honoured),
// never an error code marked not retryable (docs/errors.md). Submits carry an Idempotency-Key, so a retry never
// starts a second job.
const client = new Scrawl({ maxRetries: 3, timeoutMs: 90_000 });

const key = randomUUID();                                         // your own key: safe to resend after a crash
const first = await client.scrape(url, { idempotencyKey: key });
const again = await client.scrape(url, { idempotencyKey: key });  // replayed by the server, not run again
console.log("the same job both times:", first.job_id === again.job_id);

try {
  await client.getJob(`missing-${randomUUID()}`);
} catch (error) {
  if (!(error instanceof NotFoundError)) throw error;             // unknown, or not yours: never distinguished
  console.log(`not found: code=${error.code} request=${error.requestId}`);
}

try {
  await client.scrape(url, { formats: ["json"], instruction: "The page title" });
} catch (error) {
  if (error instanceof RateLimitError) console.log(`rate limited (${error.code}); retry after ${error.retryAfter} s`);
  else if (error instanceof AuthenticationError) throw new Error("the API key was refused: check SCRAWL_API_KEY");
  else if (error instanceof ServerError && String(error.code).startsWith("ai_")) {
    console.log(`your AI provider failed: ${error.code}`);       // fix the profile, then retry
  } else if (error instanceof APIConnectionError) throw new Error(`no response from the server: ${error.message}`);
  else if (error instanceof ScrawlError && error.code === ErrorCode.FORBIDDEN) {
    console.log("this key lacks the ai:use scope (or BYO AI is off on this server)");
  } else if (error instanceof ScrawlError) console.log(`refused: ${error}`);
  else throw error;
}
