// Structured JSON from a page with your own AI provider (bring-your-own AI):
// `SCRAWL_AI_PROVIDER=openai SCRAWL_AI_API_KEY=... node examples/extract-with-ai-profile.mjs https://example.com/item`
//
// With SCRAWL_AI_PROVIDER and SCRAWL_AI_API_KEY set, the example (re)configures a profile named "example" first;
// the provider key is stored encrypted on the server and never returned. Without them it uses your default profile.
import { Scrawl } from "@apexaiofficial/scrawl";

const url = process.argv[2];
const client = new Scrawl();
let profile;
if (process.env.SCRAWL_AI_PROVIDER && process.env.SCRAWL_AI_API_KEY) {
  const info = await client.setAiProvider("example", { provider: process.env.SCRAWL_AI_PROVIDER,
    apiKey: process.env.SCRAWL_AI_API_KEY, model: process.env.SCRAWL_AI_MODEL || undefined });
  console.error(`profile ${info.profile}: ${info.provider}/${info.model} key ${info.key_fingerprint}`);
  profile = info.profile;
}
const schema = {
  type: "object",
  properties: { name: { type: "string" }, price: { type: "number" }, sku: { type: "string" } },
};
let product = await client.scrape(url, { formats: ["json"], schema, profile,
  instruction: "The product name, price and SKU, if this is a product page" });
if (product.status === "pending") product = await client.waitForScrape(product.job_id);
if (product.status !== "completed") {
  console.error(`extraction failed: ${product.error_code}: ${product.error}`);
  process.exit(1);
}
console.log(JSON.stringify(product.json, null, 2));
console.error("provider, model and tokens used:", JSON.stringify(product.ai));
