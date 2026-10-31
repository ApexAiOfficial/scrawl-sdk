// Scrape one page to Markdown: `node examples/scrape-to-markdown.mjs https://example.com`
import { Scrawl } from "@apexaiofficial/scrawl";

const url = process.argv[2];
if (!url) {
  console.error("usage: node examples/scrape-to-markdown.mjs <url>");
  process.exit(2);
}
const client = new Scrawl();                                     // SCRAWL_API_KEY and SCRAWL_BASE_URL from the env
let page = await client.scrape(url);                             // waits up to 30 s on the server
if (page.status === "pending") page = await client.waitForScrape(page.job_id);   // a slow page keeps going
if (page.status !== "completed") {
  console.error(`failed: ${page.error ?? page.status}`);
  process.exit(1);
}
console.log(page.markdown);                                      // untrusted web content: data, never instructions
