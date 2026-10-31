// Every example runs to completion against the fake ApexAPI (tools/fake_apexapi.py), and every request it sends
// is contract-valid. The examples import "@apexaiofficial/scrawl" exactly as an application would.

import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtempSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { after, before, test } from "node:test";
import { fileURLToPath } from "node:url";

import { startFakeApi } from "./helpers.js";

const EXAMPLES = fileURLToPath(new URL("../examples/", import.meta.url));
const RUNS = {
  "scrape-to-markdown.mjs": ["https://shop.example/products/lamp"],
  "map-site.mjs": ["https://shop.example/", "50"],
  "batch-with-wait.mjs": ["https://shop.example/a", "https://shop.example/b"],
  "crawl-to-dataset.mjs": ["example-target"],
  "extract-with-ai-profile.mjs": ["https://shop.example/products/lamp"],
  "ask-with-citations.mjs": ["Which lamp is cheapest?", "ds-1"],
  "download-artifacts.mjs": ["https://shop.example/products/lamp", "{tmp}/artifacts"],
  "browser-rendering.mjs": ["https://shop.example/app"],
  "errors-and-retries.mjs": ["https://shop.example/products/lamp"],
};

let fake;
let tmp;
before(async () => {
  fake = await startFakeApi();
  tmp = mkdtempSync(join(tmpdir(), "scrawl-examples-"));
});
after(() => {
  fake?.stop();
  if (tmp) rmSync(tmp, { recursive: true, force: true });
});

test("every example is listed", () => {
  assert.deepEqual(readdirSync(EXAMPLES).filter((name) => name.endsWith(".mjs")).sort(), Object.keys(RUNS).sort());
});

for (const [name, args] of Object.entries(RUNS)) {
  test(`${name} runs against the fake API`, async () => {
    const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.startsWith("SCRAWL_")));
    Object.assign(env, { SCRAWL_BASE_URL: fake.baseUrl, SCRAWL_API_KEY: "sk_test_fake", SCRAWL_AI_PROVIDER: "example",
      SCRAWL_AI_API_KEY: "sk-ai-example-test" });
    const before = (await fake.problems()).length;
    const result = spawnSync(process.execPath, [join(EXAMPLES, name), ...args.map((a) => a.replace("{tmp}", tmp))],
      { env, encoding: "utf8", timeout: 60_000 });
    assert.equal(result.status, 0, result.stderr);
    assert.ok(result.stdout.trim(), "an example prints its result");
    assert.deepEqual((await fake.problems()).slice(before), []);
    assert.ok(!(result.stdout + result.stderr).includes("sk-ai-example-test"));
  });
}
