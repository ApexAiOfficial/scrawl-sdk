import { spawn, spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { Scrawl } from "../src/index.js";

export const REPO = fileURLToPath(new URL("../../", import.meta.url));
export const COVERAGE = JSON.parse(readFileSync(join(REPO, "coverage.json"), "utf8"));
export const PYTHON = process.env.PYTHON || "python3";

/** A fetch double: replies from `responses` in order (the last one repeats) and records every call. */
export function mockFetch(responses) {
  const queue = [...responses];
  const fetch = async (url, init = {}) => {
    const parsed = new URL(url);
    fetch.calls.push({
      url: parsed, method: init.method, headers: init.headers ?? {},
      body: init.body === undefined ? undefined : JSON.parse(init.body),
    });
    const next = queue.length > 1 ? queue.shift() : queue[0];
    if (next instanceof Error) throw next;
    if (typeof next === "function") return next(url, init);
    const status = next?.status ?? 200;
    let body = next?.body === undefined ? {} : next.body;
    if (typeof body !== "string" && !(body instanceof Uint8Array)) body = JSON.stringify(body);
    return new Response(status === 204 ? null : body, { status, headers: next?.headers });
  };
  fetch.calls = [];
  return fetch;
}

/** A client over a fetch double, with sleeps recorded instead of slept. */
export function makeClient(responses = [{ body: {} }], options = {}) {
  const fetch = mockFetch(responses);
  const client = new Scrawl({ apiKey: "sk_test_key", baseUrl: "https://api.test/", fetch, ...options });
  const sleeps = [];
  client._sleep = async (ms) => { sleeps.push(ms); };
  return { client, fetch, sleeps };
}

/** A recorded fetch call in the shape tools/check_contracts.py takes. */
export function asRecorded(call) {
  const query = {};
  for (const [key, value] of call.url.searchParams) {
    query[key] = key in query ? [].concat(query[key], value) : value;
  }
  return { method: call.method, path: call.url.pathname, query, body: call.body ?? null, headers: call.headers };
}

/** Run tools/check_contracts.py (the one checker both SDKs share); returns { status, stdout, stderr }. */
export function checkContracts(...args) {
  const result = spawnSync(PYTHON, [join(REPO, "tools", "check_contracts.py"), ...args], { encoding: "utf8" });
  if (result.error) {
    throw new Error(`could not run ${PYTHON} for tools/check_contracts.py (set PYTHON=...): ${result.error.message}`);
  }
  return result;
}

/** Check recorded requests ([{ route, request, exact }]) with the shared checker. */
export function checkRequests(recorded) {
  const dir = mkdtempSync(join(tmpdir(), "scrawl-contract-"));
  try {
    const file = join(dir, "recorded.json");
    writeFileSync(file, JSON.stringify(recorded));
    return checkContracts("requests", file);
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

/** Start tools/fake_apexapi.py on a free loopback port: { baseUrl, problems(), stop() }. */
export async function startFakeApi() {
  const child = spawn(PYTHON, [join(REPO, "tools", "fake_apexapi.py"), "--port", "0"], { stdio: ["ignore", "pipe", "pipe"] });
  const baseUrl = await new Promise((resolve, reject) => {
    let seen = "";
    child.once("error", reject);
    child.once("exit", (code) => reject(new Error(`fake API exited (${code})`)));
    child.stdout.on("data", (chunk) => {
      seen += chunk;
      const match = seen.match(/listening (http:\/\/127\.0\.0\.1:\d+)/);
      if (match) resolve(match[1]);
    });
  });
  return {
    baseUrl,
    async problems() {
      return (await (await fetch(`${baseUrl}/__fake__/problems`)).json()).problems;
    },
    stop() {
      child.removeAllListeners("exit");
      child.kill();
    },
  };
}
