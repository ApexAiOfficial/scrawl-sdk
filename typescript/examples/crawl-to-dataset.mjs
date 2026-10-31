// Crawl a target into a new dataset version, then inspect and query it:
// `node examples/crawl-to-dataset.mjs my-crawl-target`
import { Scrawl } from "@apexaiofficial/scrawl";

const target = process.argv[2];
const client = new Scrawl();
const launch = await client.crawl(target, { maxItems: 500 });     // a named crawl target the server allows
const job = await client.waitForJob(launch.job_id, { timeoutMs: 1_800_000 });
if (job.status !== "COMPLETED") {
  console.error(`crawl ${job.status}`);
  process.exit(1);
}
const { fields } = await client.datasetFields(launch.dataset_id, { version: launch.dataset_version_id });
console.log("fields:", fields.map((f) => `${f.path} (${f.types.join("/")})`).join(", "));
const numeric = fields.find((f) => f.types.includes("number") || f.types.includes("integer"))?.path;
const filters = numeric ? [{ field: numeric, op: "lt", value: 20 }] : [];
for await (const record of client.paginate(client.queryDataset, launch.dataset_id, filters,
  { versionId: launch.dataset_version_id })) {
  console.log(JSON.stringify(record));
}
