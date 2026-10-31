# Versioning and releases

## Versions

Both SDKs follow [Semantic Versioning](https://semver.org/) and stay on **0.x** until the API under `/v1` is
declared stable. Before 1.0:

- a **minor** version (0.2.0) may change the SDK's API; the changelog says what to change;
- a **patch** version (0.1.1) fixes bugs and never changes the API.

The Python package (`scrawl-sdk`) and the npm package (`@apexaiofficial/scrawl`) are versioned and released
independently, but they cover the same operations: both are tested against the same `coverage.json` and
contract bundle.

Every release records the contract it was built against: `scrawl.__contract__` / `CONTRACT_DIGEST` hold the
digest of `contracts/MANIFEST.json`, and `CHANGELOG.md` names it for each release. A server is compatible with
an SDK release when that release's `tools/check_contracts.py compat` passes against the server's OpenAPI
document (see [compatibility](compatibility.md)).

## What counts as a change

| Change | Version |
| --- | --- |
| A new method, option or `ErrorCode` for something the API added | minor (pre-1.0) |
| A method or option removed or renamed, a different return shape, a different exception class | minor (pre-1.0), called out in the changelog |
| A bug fix, documentation, a contract update that changes nothing the SDK sends | patch |

The version lives in two places per SDK, and the tests fail if they disagree:
`python/pyproject.toml` and `python/src/scrawl/_version.py`; `typescript/package.json` and
`typescript/src/version.js`.

## Releasing

Releases are cut from tags; the [release workflow](../.github/workflows/release.yml) runs the full CI first.

| Tag | Builds | Attaches to a GitHub Release | Publishes |
| --- | --- | --- | --- |
| `py-vX.Y.Z` | sdist and wheel (`python -m build python`) | yes | PyPI, only when the repository variable `ENABLE_PYPI` is `true` (trusted publishing, no token) |
| `ts-vX.Y.Z` | `npm pack` of `typescript/` | yes | npm, only when the repository variable `ENABLE_NPM` is `true` (with provenance) |

The workflow refuses a tag whose version differs from the package's. Steps for a release:

1. Update the version (both places) and `CHANGELOG.md`, including the contract digest.
2. Merge to `main` with CI green.
3. Tag: `git tag py-v0.2.0 && git push origin py-v0.2.0` (or `ts-v...`).
