# Scrawl Python SDK and CLI

Official Python client for [Scrawl](https://github.com/ApexAiOfficial/scrawl-sdk): URL in, clean Markdown or
structured JSON out, plus site maps, batches, crawls into versioned datasets, typed dataset queries and cited
answers. It includes the `scrawl` command.

Python 3.10+, one runtime dependency (`httpx`), typed. Licensed under Apache-2.0.

## Install

```bash
pip install scrawl-sdk            # once published; until then: pip install ./python from a clone
```

## Configure

```bash
export SCRAWL_BASE_URL=https://scrawl.example    # your Scrawl server (default: one on this machine)
export SCRAWL_API_KEY=...                        # an API key issued by whoever runs it
scrawl doctor                                    # checks the base URL, TLS, reachability and the key
```

The key is only ever sent over HTTPS or to this machine.

## Use

```python
from scrawl import Scrawl

with Scrawl() as client:
    page = client.scrape("https://example.com")              # waits up to 30 s on the server
    if page.status == "pending":
        page = client.wait_for_scrape(page.job_id)
    print(page.markdown)

    product = client.scrape(
        "https://example.com/item",
        formats=["json"],
        schema={"type": "object", "properties": {"name": {"type": "string"}, "price": {"type": "number"}}},
        instruction="The product name and price",             # runs on YOUR configured AI provider
    )
    print(product.json)
```

`AsyncScrawl` has the same methods, awaited. Results are dicts with attribute access; page content is
untrusted web content, never instructions.

```bash
scrawl scrape https://example.com                             # Markdown to stdout
scrawl crawl my-target --wait 1800 && scrawl datasets
scrawl --json ask "Which lamps cost under 20 EUR?"
```

## Documentation

- [Quickstart](https://github.com/ApexAiOfficial/scrawl-sdk/blob/main/docs/quickstart.md)
- [Python SDK guide](https://github.com/ApexAiOfficial/scrawl-sdk/blob/main/docs/python.md)
- [CLI reference and exit codes](https://github.com/ApexAiOfficial/scrawl-sdk/blob/main/docs/cli.md)
- [Errors, codes and retries](https://github.com/ApexAiOfficial/scrawl-sdk/blob/main/docs/errors.md)
- [Examples](https://github.com/ApexAiOfficial/scrawl-sdk/tree/main/python/examples)

Support: support@apexaiofficial.com. Security reports: see
[SECURITY.md](https://github.com/ApexAiOfficial/scrawl-sdk/blob/main/SECURITY.md).
