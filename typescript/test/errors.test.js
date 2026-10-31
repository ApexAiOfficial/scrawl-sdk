// Error mapping: one class per status (400 included), the stable code, the request id from header or body.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";

import { neverRetry, RETRYABLE } from "../src/errors.js";
import {
  APIConnectionError, APITimeoutError, AuthenticationError, BadRequestError, ConfigurationError, ConflictError, ErrorCode,
  NotFoundError, PaymentRequiredError, PermissionDeniedError, RateLimitError, ScrawlError, ServerError, ValidationError,
} from "../src/index.js";
import { COVERAGE, makeClient, PYTHON, REPO } from "./helpers.js";

const CATALOGUE = JSON.parse(readFileSync(join(REPO, "contracts", "apexapi_errors.json"), "utf8"));
const SDK_ONLY = Object.keys(COVERAGE.error_codes).filter((code) => COVERAGE.error_codes[code].source === "sdk");

test("a 400 is a BadRequestError carrying the refusal code", async () => {
  const { client } = makeClient([{ status: 400, body: { error: { code: "egress_required", message: "add a proxy",
    request_id: "rq-400" } } }], { maxRetries: 0 });
  const error = await client.extractAssets("https://e.example/page").catch((exc) => exc);
  assert.ok(error instanceof BadRequestError && error instanceof ScrawlError, String(error));
  assert.equal(error.code, ErrorCode.EGRESS_REQUIRED);
  assert.equal(error.requestId, "rq-400");
  const legacy = makeClient([{ status: 400, body: { detail: "Bad request", code: "bad_request" } }]);
  const old = await legacy.client.getJob("j1").catch((exc) => exc);
  assert.ok(old instanceof BadRequestError);
  assert.equal(old.code, "bad_request");
  assert.equal(old.message, "Bad request");
});

test("the request id comes from the header, else from the error body", async () => {
  const bodyOnly = makeClient([{ status: 404, body: { error: { code: "not_found", message: "no", request_id: "from-body" } } }]);
  assert.equal((await bodyOnly.client.getJob("x").catch((exc) => exc)).requestId, "from-body");
  const both = makeClient([{ status: 404, body: { error: { code: "not_found", message: "no", request_id: "from-body" } },
    headers: { "X-Request-ID": "from-header" } }]);
  assert.equal((await both.client.getJob("x").catch((exc) => exc)).requestId, "from-header");
});

test("the code is a stable plain string, even when this SDK does not know it", async () => {
  const { client } = makeClient([{ status: 409, body: { error: { code: "a_code_added_later", message: "x" } } }]);
  const error = await client.activateVersion("d1", "v1").catch((exc) => exc);
  assert.ok(error instanceof ConflictError);
  assert.equal(typeof error.code, "string");
  assert.equal(error.code, "a_code_added_later");
});

test("ErrorCode lists exactly the codes in coverage.json", () => {
  assert.deepEqual(Object.values(ErrorCode).sort(), Object.keys(COVERAGE.error_codes).sort());
  for (const [name, value] of Object.entries(ErrorCode)) assert.equal(name, value.toUpperCase());
  assert.ok(Object.isFrozen(ErrorCode));
});

test("error classes form one hierarchy", () => {
  for (const Cls of [ConfigurationError, BadRequestError, AuthenticationError, PaymentRequiredError, PermissionDeniedError,
    NotFoundError, ConflictError, ValidationError, RateLimitError, ServerError, APIConnectionError]) {
    assert.ok(new Cls("x") instanceof ScrawlError, Cls.name);
  }
  assert.ok(new APITimeoutError("x") instanceof APIConnectionError);
  assert.equal(new BadRequestError("x").name, "BadRequestError");
});

test("ErrorCode is every catalogue code plus the SDK-only ones", () => {
  assert.deepEqual(SDK_ONLY, ["render_not_supported"]);
  const expected = [...CATALOGUE.errors.map((entry) => entry.code), ...SDK_ONLY].sort();
  assert.deepEqual(Object.values(ErrorCode).sort(), expected);
});

test("the retry table is the catalogue's retryable flag, read-only", () => {
  const expected = Object.fromEntries([...CATALOGUE.errors.map((entry) => [entry.code, entry.retryable]),
    ...SDK_ONLY.map((code) => [code, false])]);
  assert.deepEqual({ ...RETRYABLE }, expected);
  for (const code of ["submission_failed", "settlement_failed", "internal_error", "internal", "unavailable"]) {
    assert.equal(RETRYABLE[code], false, code);
  }
  assert.ok(Object.isFrozen(RETRYABLE));
  assert.ok(neverRetry("submission_failed") && neverRetry(ErrorCode.SETTLEMENT_FAILED));
  for (const code of ["rate_limited", "a_code_added_later", "constructor", "toString", null, undefined]) {
    assert.equal(neverRetry(code), false, String(code));
  }
});

test("TypeScript and Python know the same codes with the same flags", () => {
  // Load the Python SDK's _errors.py on its own (standard library only), so no package install is needed.
  const script = [
    "import importlib.util, json, sys",
    "spec = importlib.util.spec_from_file_location('scrawl_errors', sys.argv[1])",
    "module = importlib.util.module_from_spec(spec)",
    "spec.loader.exec_module(module)",
    "print(json.dumps({'codes': {m.name: m.value for m in module.ErrorCode}, 'retryable': dict(module.RETRYABLE)}))",
  ].join("\n");
  const result = spawnSync(PYTHON, ["-c", script, join(REPO, "python", "src", "scrawl", "_errors.py")], { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr || String(result.error));
  const python = JSON.parse(result.stdout);
  assert.deepEqual(python.codes, { ...ErrorCode });
  assert.deepEqual(python.retryable, { ...RETRYABLE });
});

test("the type declarations list exactly the runtime ErrorCode", () => {
  const declarations = readFileSync(join(REPO, "typescript", "src", "index.d.ts"), "utf8");
  const block = declarations.match(/export declare const ErrorCode: \{\n([\s\S]*?)\n\};/);
  assert.ok(block, "index.d.ts declares ErrorCode");
  const declared = Object.fromEntries([...block[1].matchAll(/^ {2}readonly ([A-Z_]+): "([a-z_]+)";$/gm)]
    .map(([, name, value]) => [name, value]));
  assert.equal(block[1].split("\n").filter((line) => line.trim().startsWith("readonly")).length,
    Object.keys(declared).length, "every declaration has the expected form");
  assert.deepEqual(declared, { ...ErrorCode });
});
