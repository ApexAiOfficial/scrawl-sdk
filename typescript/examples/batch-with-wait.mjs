// Scrape up to 20 URLs as one batch and wait for every item:
// `node examples/batch-with-wait.mjs https://example.com/a https://example.com/b`
import { Scrawl } from "@apexaiofficial/scrawl";

const urls = process.argv.slice(2, 22);
const client = new Scrawl();
const batch = await client.batchScrape(urls, { formats: ["markdown"] });
const done = await client.waitForBatch(batch.batch_id, { timeoutMs: 600_000 });   // server-side waits, no tight polling
for (const item of done.items ?? []) {
  console.log(`${item.status.padEnd(10)} ${item.url} (${(item.result?.markdown ?? "").length} characters)`);
}
const failed = (done.items ?? []).filter((item) => item.status !== "completed");
process.exit(failed.length || done.status !== "completed" ? 1 : 0);
