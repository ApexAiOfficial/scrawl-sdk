// List a site's URLs (start page links plus its sitemap, same host): `node examples/map-site.mjs https://example.com 200`
import { Scrawl } from "@apexaiofficial/scrawl";

const [url, limit = "100"] = process.argv.slice(2);
const client = new Scrawl();
const site = await client.map(url, { limit: Number(limit) });
for (const link of site.links ?? []) console.log(link);
console.error(`${(site.links ?? []).length} URL(s); sources: ${JSON.stringify(site.sources ?? {})}`);
