// Scrape a page, then save its job's artifacts, checked against the artifact list and never overwriting:
// `node examples/download-artifacts.mjs https://example.com ./artifacts`
import { createHash } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";

import { Scrawl } from "@apexaiofficial/scrawl";

const [url, out] = process.argv.slice(2);
await mkdir(out, { recursive: true });
const client = new Scrawl();
let page = await client.scrape(url);
if (page.status === "pending") page = await client.waitForScrape(page.job_id);
const { artifacts } = await client.listArtifacts(page.job_id);
for (const artifact of artifacts) {
  const bytes = Buffer.from(await client.downloadArtifact(page.job_id, artifact.name));
  if (bytes.length !== artifact.size_bytes) throw new Error(`${artifact.name}: size does not match the list`);
  const safeName = artifact.name.replace(/[^A-Za-z0-9._-]/g, "_").replace(/^\.+/, "") || "artifact";   // never trust a name
  await writeFile(join(out, safeName), bytes, { flag: "wx" });                // "wx": fail rather than overwrite
  console.log(`${safeName}  ${bytes.length} bytes  sha256 ${createHash("sha256").update(bytes).digest("hex")}`);
}
