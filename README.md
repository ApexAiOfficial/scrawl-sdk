# Scrawl SDKs and CLI

Official client libraries for [Scrawl](https://github.com/ApexAiOfficial): URL in, clean Markdown or structured
JSON out, plus site maps, batches, crawls into versioned datasets, typed dataset queries and cited answers.

| Package | Install (once published) | Import | Docs |
| --- | --- | --- | --- |
| Python SDK and the `scrawl` CLI | `pip install scrawl-sdk` | `from scrawl import Scrawl` | [docs/python.md](docs/python.md), [docs/cli.md](docs/cli.md) |
| TypeScript / JavaScript SDK | `npm install @apexaiofficial/scrawl` | `import { Scrawl } from "@apexaiofficial/scrawl"` | [docs/typescript.md](docs/typescript.md) |

Neither package is on PyPI or npm yet. Until then, install from a clone of this repository:
`pip install ./python` and `npm install ./typescript`.

Both SDKs talk only to Scrawl's public, versioned HTTP API (ApexAPI) and share one contract: the
[`contracts/`](contracts/) bundle exported by the server, and [`coverage.json`](coverage.json), which maps every
API operation to its Python method, TypeScript method and CLI command (or says why it is left out).

## Five lines

```python
from scrawl import Scrawl

with Scrawl() as client:                        # SCRAWL_API_KEY and SCRAWL_BASE_URL from the environment
    print(client.scrape("https://example.com").markdown)
```

```js
import { Scrawl } from "@apexaiofficial/scrawl";

console.log((await new Scrawl().scrape("https://example.com")).markdown);
```

```bash
export SCRAWL_BASE_URL=https://scrawl.example       # your Scrawl server
export SCRAWL_API_KEY=...                           # an API key from its operator
scrawl doctor                                       # base URL, TLS, reachability, API key
scrawl scrape https://example.com                   # Markdown to stdout
```

Start with the [quickstart](docs/quickstart.md).

## What is in here

```
contracts/      the server's public contract bundle (OpenAPI, MCP tools and resources) + MANIFEST.json
coverage.json   every API operation -> Python method, TypeScript method, CLI command (or an exclusion)
python/         the Python SDK and CLI (scrawl-sdk), its tests and examples
typescript/     the TypeScript SDK (@apexaiofficial/scrawl), its tests and examples
tools/          check_contracts.py (the compatibility checker), sync_contracts.py, fake_apexapi.py
docs/           quickstart, per-language guides, CLI, authentication, errors, compatibility, versioning
```

## Documentation

- [Quickstart](docs/quickstart.md)
- [Python SDK](docs/python.md), [TypeScript SDK](docs/typescript.md), [CLI](docs/cli.md)
- [Authentication and configuration](docs/authentication.md)
- [Errors, codes and retries](docs/errors.md)
- [Compatibility: how the SDKs track the API](docs/compatibility.md)
- [Versioning and releases](docs/versioning.md)

## Status

Version 0.1.0, not yet published. The API is versioned under `/v1`; until it is declared stable, the SDKs stay
on 0.x and a minor version may change their API (see [versioning](docs/versioning.md)). Browser rendering is
available only on servers that enable it.

## Contributing, security, license

- [CONTRIBUTING.md](CONTRIBUTING.md): how to run the tests and how a contract update lands.
- [SECURITY.md](SECURITY.md): report vulnerabilities privately; what the SDKs promise about keys and content.
- Licensed under the [Apache License 2.0](LICENSE); see [NOTICE](NOTICE).
