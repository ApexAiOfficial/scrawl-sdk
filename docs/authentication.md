# Authentication and configuration

## The API key

Every call except `health` sends `Authorization: Bearer <key>`. Keys are issued by whoever runs your Scrawl
server; the SDKs cannot create them. Pass the key explicitly or let the SDK read `SCRAWL_API_KEY`:

```python
Scrawl(api_key="...")              # or Scrawl() with SCRAWL_API_KEY set
```

```js
new Scrawl({ apiKey: "..." });     // or new Scrawl() with SCRAWL_API_KEY set
```

The key is required lazily: a client without one can still call `health`, and any other call raises
`ConfigurationError` before anything is sent. Surrounding whitespace (a line ending from a key file or a CRLF
`.env`) is trimmed; a key with spaces, control or non-ASCII characters inside is refused the same way, and the
error never quotes it. The TypeScript client keeps the key out of the instance (in a
`WeakMap`), so logging or serialising a client never prints it. The CLI reads the key **only** from
`SCRAWL_API_KEY`: no flag exists, so a command copied from a web page cannot redirect your key or leave it in
a shell history or an agent transcript.

## The base URL

`SCRAWL_BASE_URL` (or `base_url` / `baseUrl`) is the URL of your Scrawl server, for example
`https://scrawl.example`. Without it, the SDKs talk to a server on this machine, `http://127.0.0.1:8088`.
There is deliberately no built-in remote default.

The key never crosses a network in clear text:

- `https://` URLs are always allowed (the certificate is verified).
- `http://` is allowed only to this machine: `localhost`, `*.localhost`, `127.0.0.0/8` and `::1`.
- Plain `http://` to any other host raises `ConfigurationError`, unless you opt in for a trusted network with
  `allow_insecure_http=True` / `allowInsecureHttp: true` or `SCRAWL_ALLOW_INSECURE_HTTP=1`.

`scrawl doctor` checks all of this: the base URL and where it came from, TLS, whether the server answers
`GET /v1/health`, and whether the key is accepted. It never prints the key.

## Scopes

A key carries scopes. Keys are issued with `scrape:write`, `jobs:read`, `artifacts:read` and `credits:read`
unless the operator chooses otherwise; the AI scopes are never on by default.

| Scope | Lets the key |
| --- | --- |
| `scrape:write` | scrape, map, batch, crawl, extract assets, cancel jobs (other than AI extraction jobs), activate versions, quarantine records |
| `jobs:read` | read jobs and list them |
| `artifacts:read` | read results, artifacts, assets, datasets, versions, diffs, fields, queries, search, documents |
| `credits:read` | read the credit balance |
| `ai:configure` | manage your AI provider profiles and read your AI usage |
| `ai:use` | JSON scrapes and batches (together with `scrape:write`), `extract`, `ask` and dataset extraction with your own AI provider, and cancelling dataset extraction jobs |

Two requests need more than the scope of their route:

- A scrape or batch that asks for the `json` format needs `ai:use` as well as `scrape:write`.
- Cancelling a job needs the scope that starts that kind of job: `ai:use` for an AI extraction job (a
  dataset extraction), `scrape:write` for any other.

A missing scope is a 403 `PermissionDeniedError` with code `forbidden`. The server's own scope table is
[`contracts/apexapi_scopes.json`](../contracts/apexapi_scopes.json).

## Your AI provider key (bring-your-own AI)

Structured extraction runs on **your** AI provider account. Store a provider key once per profile with
`set_ai_provider` / `setAiProvider` or `scrawl ai providers set`; the server keeps it encrypted and only ever
returns a fingerprint. The CLI reads that key from an environment variable (`SCRAWL_AI_API_KEY` by default, or
the one named by `--key-env`) or from stdin (`--key-stdin`), never from the command line; an unrecognised
argument is never echoed back, in case it was a pasted secret (no usage error repeats what you typed).

## Environment variables

| Variable | Used by | Meaning |
| --- | --- | --- |
| `SCRAWL_API_KEY` | SDKs, CLI | Your Scrawl API key |
| `SCRAWL_BASE_URL` | SDKs, CLI | Your Scrawl server (default: this machine) |
| `SCRAWL_ALLOW_INSECURE_HTTP` | SDKs, CLI | `1` allows plain HTTP to a non-loopback host |
| `SCRAWL_AI_API_KEY` | CLI | Default source of the provider key for `scrawl ai providers set` |
| `SCRAWL_LIVE_*` | tests | The live compatibility suite (see [compatibility](compatibility.md)) |
