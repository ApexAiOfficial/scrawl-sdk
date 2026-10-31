// Render a JavaScript-heavy page in a sandboxed browser first, falling back to the static fetcher:
// `node examples/browser-rendering.mjs https://example.com/app`
//
// Browser rendering is available only where the server enables it. Elsewhere the API refuses with 503
// browser_unavailable, and a server that predates the browser engine is caught by the SDK's downgrade guard
// (render_not_supported) instead of silently returning a static page.
import { ErrorCode, Scrawl, ScrawlError } from "@apexaiofficial/scrawl";

const url = process.argv[2];
const client = new Scrawl();
let page;
try {
  page = await client.scrape(url, { engine: "browser", waitForMs: 500 });
  if (page.status === "pending") page = await client.waitForScrape(page.job_id, { engine: "browser" });   // keeps the guard
} catch (error) {
  const fallback = [ErrorCode.BROWSER_UNAVAILABLE, ErrorCode.RENDER_NOT_SUPPORTED];
  if (!(error instanceof ScrawlError) || !fallback.includes(error.code)) throw error;
  console.error(`no browser rendering here (${error.code}); using the static fetcher`);
  page = await client.scrape(url);
}
console.error(`engine: ${page.engine ?? "static"}, final URL: ${page.final_url ?? page.url}`);
console.log(page.markdown);
