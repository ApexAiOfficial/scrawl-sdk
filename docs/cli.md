# The `scrawl` command

Installed with the Python SDK (`pip install scrawl-sdk`, or `pip install ./python` from a clone). It reads the
server and key only from the environment, so commands are safe to paste and to give to an agent:

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
scrawl doctor                      # base URL, TLS, reachability (GET /v1/health) and the API key
scrawl --json doctor               # the same checks as JSON: {"ok": ..., "checks": [...]}
```

## Scrape, map, batch

```bash
scrawl scrape https://example.com                                  # Markdown to stdout (waits up to 60 s)
scrawl scrape https://example.com --format links --format html
scrawl scrape https://example.com/item --instruction "name and price"   # JSON with your AI provider
scrawl scrape https://example.com/item --schema product.schema.json --profile main
scrawl scrape https://example.com/app --browser --wait-for 500    # only where the server enables it
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
rendered (a server that predates the browser engine) is an error (`render_not_supported`, exit 5); `batch`
still prints the batch first, so its id is not lost.

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

`--provider` is one the server supports (for example `openai`, `anthropic`, `deepseek`, or `custom` with
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
```

## Exit codes

| Exit | Meaning |
| --- | --- |
| 0 | Success |
| 1 | The job (or a batch item) failed, or a downloaded file did not match its size or SHA-256 (it was not written); `ai providers test` failed |
| 2 | Usage error, or a file already exists where a download would go (nothing is overwritten) |
| 3 | Authentication or configuration: 401/403, no API key, an unusable base URL or AI key, a TLS failure in `doctor` |
| 4 | Still pending or running at the deadline |
| 5 | Any other API or connection error |
