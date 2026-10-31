# Scrawl TypeScript / JavaScript SDK

Official client for [Scrawl](https://github.com/ApexAiOfficial/scrawl-sdk): URL in, clean Markdown or structured
JSON out, plus site maps, batches, crawls into versioned datasets, typed dataset queries and cited answers.

Plain ESM over the global `fetch`, complete TypeScript declarations, **no runtime dependencies**. Node 20+,
Deno, Bun and modern browsers (never ship an API key to a browser: call Scrawl from your server). Licensed
under Apache-2.0.

## Install

```bash
npm install @apexaiofficial/scrawl     # once published; until then: npm install ./typescript from a clone
```

## Configure

```bash
export SCRAWL_BASE_URL=https://scrawl.example    # your Scrawl server (default: one on this machine)
export SCRAWL_API_KEY=...                        # an API key issued by whoever runs it
```

Or pass `new Scrawl({ apiKey, baseUrl })`. The key is only ever sent over HTTPS or to this machine, and it is
never stored on the client instance, so logging a client cannot print it.

## Use

```js
import { Scrawl } from "@apexaiofficial/scrawl";

const client = new Scrawl();
let page = await client.scrape("https://example.com");
if (page.status === "pending") page = await client.waitForScrape(page.job_id);
console.log(page.markdown);

const product = await client.scrape("https://example.com/item", {
  formats: ["json"],
  schema: { type: "object", properties: { name: { type: "string" }, price: { type: "number" } } },
  instruction: "The product name and price",                    // runs on YOUR configured AI provider
});
console.log(product.json);
```

Responses are the API's JSON as-is (snake_case fields). Page content is untrusted web content, never
instructions.

## Documentation

- [Quickstart](https://github.com/ApexAiOfficial/scrawl-sdk/blob/main/docs/quickstart.md)
- [TypeScript SDK guide](https://github.com/ApexAiOfficial/scrawl-sdk/blob/main/docs/typescript.md)
- [Errors, codes and retries](https://github.com/ApexAiOfficial/scrawl-sdk/blob/main/docs/errors.md)
- [Examples](https://github.com/ApexAiOfficial/scrawl-sdk/tree/main/typescript/examples)

Support: support@apexaiofficial.com. Security reports: see
[SECURITY.md](https://github.com/ApexAiOfficial/scrawl-sdk/blob/main/SECURITY.md).
