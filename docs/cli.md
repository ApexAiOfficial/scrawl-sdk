# The `scrawl` command

Installed with the Python SDK. It is not on PyPI yet: install it from a GitHub Release or a clone (see
[installation](../README.md#installation)); once published, `pip install scrawl-sdk`. It reads the endpoint and key
only from the environment, so commands are safe to paste and to give to an agent:

```bash
export SCRAWL_BASE_URL=https://scrawl.example
export SCRAWL_API_KEY=...
scrawl doctor
```

`--json` (before the command) prints the full JSON response; most commands print JSON anyway. Page content is
untrusted: terminal control characters are stripped from anything printed as text (error messages included)
and escaped in JSON output. Usage errors never repeat what you typed, in case it was a pasted secret.

## Setup check

```bash
scrawl doctor                      # base URL, TLS, reachability (GET /v1/health), the API key and your proxy
scrawl --json doctor               # the same checks as JSON: {"ok": ..., "checks": [...]}
```

In `direct` mode, doctor requires the single proxy to have passed its test. In `pool` or `required_pool` mode,
it requires at least one active pool entry that passed its test. It never reports ready with no tested proxy.

## Scrape, map, batch

```bash
scrawl scrape https://example.com                                  # Markdown to stdout (waits up to 60 s)
scrawl scrape https://example.com --format links --format html
scrawl scrape https://example.com/item --instruction "name and price"   # JSON with your AI provider
scrawl scrape https://example.com/item --schema product.schema.json --profile main
scrawl scrape https://example.com/app --browser --wait-for 500    # only where browser rendering is enabled
scrawl result job_123 --wait 60                                     # a pending scrape's result
scrawl result job_123 --browser                                     # keep the browser downgrade guard
scrawl map https://example.com --limit 200                          # one URL per line
scrawl batch https://example.com/a https://example.com/b --wait 300
scrawl batch-status batch_123 --wait 60
scrawl batch-status batch_123 --browser                             # the batch asked for --browser: keep the guard
scrawl extract job_123 --instruction "the product name"             # JSON from a finished job's artifact
```

JSON output (`--format json`, or `--instruction` / `--schema` on `scrape`) runs on your own AI provider: the key
needs `ai:use` as well as `scrape:write`. `cancel` needs the scope that starts that kind of job (see
[scopes](authentication.md#scopes)).

`--browser` keeps the downgrade guard: a finished result, or a finished batch item, that another engine
rendered (a Scrawl version that predates the browser engine) is an error (`render_not_supported`, exit 5); `batch`
still prints the batch first, so its id is not lost.

For a non-JSON scrape, the CLI writes `outcome` (and any `block_reason`, `retry_after_s` and `hint`) to stderr
while the selected content stays on stdout. Full scrape JSON and batch output include those fields and the
batch's `outcomes` counts. Refunds are automatic and cover only Scrawl's own failures: a job that never started, and a scrape whose outcome is `pipeline_failed`. Target blocks/errors, failures in your proxy and
cancellations after work starts remain charged.

If a map's start page has `outcome: target_blocked`, `scrawl map` prints the `block_reason` and any `hint` to
stderr and exits 1, even though the settled map result itself has `status: completed`.

## Crawls, jobs, artifacts

```bash
scrawl crawl my-target --max-items 500 --wait 1800                  # waits for the job; prints dataset ids
scrawl jobs --limit 20 --status RUNNING
scrawl job job_123 --wait 60
scrawl cancel job_123
scrawl artifacts list job_123
scrawl artifacts download job_123 --out ./artifacts                 # every listed artifact
scrawl artifacts download job_123 response.html --format markdown --out ./artifacts
```

Detailed job output (`job`, a waited `crawl`, or a waited dataset extraction) includes `warnings`; it is an empty
list when there are none or when an older server omitted the field.

`artifacts download` checks each file against the job's artifact list (its size, and its SHA-256 when the
server lists one), writes it whole or not at all, and never overwrites an existing file. Names are reduced to
`[A-Za-z0-9._-]` and must resolve inside `--out`. `--format markdown` converts an HTML artifact and writes
`NAME.md` (a conversion has nothing to verify against).

## Datasets

```bash
scrawl datasets                                                     # list (same as: scrawl datasets list)
scrawl datasets get ds_123
scrawl datasets versions ds_123 --status completed
scrawl datasets fields ds_123 --version v_2
scrawl datasets query ds_123 --where price lt 20 --where sku exists true --limit 50
scrawl datasets query ds_123 --filters-file filters.json
scrawl datasets diff ds_123 v_1 v_2
scrawl datasets activate ds_123 v_1                                 # roll back (or forward)
scrawl datasets extract ds_123 --schema product.schema.json --max-records 50 --wait 900
scrawl datasets quarantine ds_123 rec_9 --reason "duplicate"
scrawl datasets release ds_123 rec_9
scrawl search "desk lamp" --limit 10
scrawl document doc_123
scrawl ask "Which lamps cost under 20 EUR?" --dataset ds_123        # the answer, then its sources
```

`--where FIELD OP VALUE`: `OP` is one of `eq`, `ne`, `lt`, `lte`, `gt`, `gte`, `contains`, `in`, `exists`;
`VALUE` is parsed as JSON when it can be (`20`, `true`, `["a","b"]`) and is text otherwise.

## Your proxy

Every job leaves through your own proxy, and nothing is fetched until it has passed a test.

```bash
scrawl proxy set --label "my provider"           # URL from SCRAWL_PROXY_URL
scrawl proxy set --url-env MY_PROXY_URL          # URL from another variable
scrawl proxy set --url-stdin < proxy-url.txt     # URL from the first line of stdin
scrawl proxy test                                # one real HTTPS request through it; exit 1 if it fails
scrawl proxy show                                # the proxy (credentials masked) and whether it is usable
scrawl proxy remove                              # jobs are refused again until you set and test another
scrawl proxy health                              # free advisory quality report; does not change readiness
scrawl proxy pool list                           # mode and entries (credentials masked)
scrawl proxy pool add --label provider-a         # URL from SCRAWL_PROXY_URL, as for proxy set
scrawl proxy pool test provider-a                # a pass makes the entry active
scrawl proxy pool disable provider-a
scrawl proxy pool enable provider-a              # test it again before use
scrawl proxy pool mode required_pool
scrawl proxy pool remove provider-a
```

The URL is `scheme://[user:pass@]host:port` with `http`, `https`, `socks5` or `socks5h`. For both `proxy set`
and `proxy pool add`, it is never a command-line argument: use `--url-env` or `--url-stdin`. Proxy passwords are
never returned, and the CLI masks unexpected URL userinfo defensively.

## Your AI providers

```bash
scrawl ai providers list
scrawl ai providers set main --provider openai                           # key from SCRAWL_AI_API_KEY
scrawl ai providers set main --provider anthropic --key-env MY_AI_KEY    # key from another variable
scrawl ai providers set work --provider custom --base-url https://llm.example/v1 --key-stdin < key.txt
scrawl ai providers default main
scrawl ai providers test main                                            # exit 1 if the provider fails
scrawl ai providers usage --days 7
scrawl ai providers remove main
```

`--provider` is one Scrawl supports (for example `openai`, `anthropic`, `deepseek`, or `custom` with
`--base-url` for an OpenAI-compatible endpoint); `--model NAME` picks a model. The provider key is never a
command-line argument, and an unrecognised argument is never echoed back.

## Assets

```bash
scrawl assets-quote https://example.com/page --class images --max-credits 50
scrawl assets https://example.com/page --class images --class documents --wait 300 --out ./assets
scrawl assets-result job_123 --wait 60 --view skipped
scrawl assets-result job_123 --out ./assets                          # download a finished job's files later
```

`--out DIR` writes `DIR/<class>/<asset_id[:12]>-<name>`: only SHA-256-verified files, never overwriting.

## Account

```bash
scrawl balance
scrawl keys list
scrawl keys revoke 0123456789abcdef0123456789abcdef
```

Hosted keys are created in Telegram with `/api_keys create`; the CLI and SDKs deliberately have no create
operation. Listing and revoking keys need `keys:manage`, which a key made with `/api_keys create_manager` holds;
revocation is permanent and a key may revoke itself.

## Exit codes

| Exit | Meaning |
| --- | --- |
| 0 | Success |
| 1 | The job (or a batch item) failed, a map's start page was blocked, or a downloaded file did not match its size or SHA-256 (it was not written); `ai providers test` failed |
| 2 | Usage error, or a file already exists where a download would go (nothing is overwritten) |
| 3 | Authentication or configuration: 401/403, no API key, an unusable base URL or AI key; in `doctor`, a TLS failure or no proxy that has passed its test (in pool modes, no pool entry that has) |
| 4 | Still pending or running at the deadline |
| 5 | Any other API or connection error |
