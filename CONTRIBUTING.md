# Contributing

Issues and pull requests are welcome.

## Run the checks

```bash
# Python SDK and CLI (Python 3.10+)
python -m venv python/.venv
python/.venv/bin/python -m pip install -e "python[test]"
python/.venv/bin/python -m pytest python/tests

# TypeScript SDK (Node 20+; the contract and example tests also need python3 on PATH, or PYTHON=...)
cd typescript && node --test && npm run typecheck

# The shared contract tools
python tools/check_contracts.py coverage
python tools/check_contracts.py manifest
python tools/gen_error_docs.py --check
```

The live suites (`python/tests/live`, `typescript/test/live`) are skipped unless `SCRAWL_LIVE_BASE_URL` and
`SCRAWL_LIVE_API_KEY` point at a live Scrawl endpoint; see [docs/compatibility.md](docs/compatibility.md).

## Rules of the road

- **The SDKs are clients of the public contract.** They implement what `contracts/apexapi_openapi.json` says;
  they never contain server logic or rely on undocumented behaviour.
- **Both SDKs move together.** A new operation needs a method in each SDK, a CLI command, an entry in
  `coverage.json`, a live test and the contract tests' `CALLS` tables; the tests fail until all of them exist.
- **Contracts change only through `tools/sync_contracts.py`** with a bundle exported by Scrawl. Hand edits
  fail the manifest check.
- **Error codes live in `coverage.json`.** Add a code there and to both `ErrorCode`s, then run
  `python tools/gen_error_docs.py`.
- **Failing test first.** A fix or a feature comes with a test that fails without it. Never weaken an
  assertion to get a green run.
- **No secrets, no real hosts.** Use `.example` and `.test` domains and obviously fake keys in code, tests and
  examples. Never put a real key, token or private host name anywhere in this repository.
- **Versions.** Keep `pyproject.toml` and `_version.py`, and `package.json` and `version.js`, in step, and add
  a `CHANGELOG.md` entry (see [docs/versioning.md](docs/versioning.md)).

By contributing you agree that your contribution is licensed under the Apache License 2.0.
