"""The repository's contract tools: the checker catches what it must, sync verifies bundles, docs stay generated."""

from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import check_contracts as cc
import gen_error_docs
import pytest
import sync_contracts
from conftest import COVERAGE, OPENAPI, REPO, TOOLS

SCRAPE = "POST /v1/scrape"


def _without(openapi: dict, path: str, method: str) -> dict:
    changed = copy.deepcopy(openapi)
    del changed["paths"][path][method]
    return changed


def test_the_checker_passes_the_vendored_contract() -> None:
    assert cc.check_coverage(OPENAPI, COVERAGE) == []
    assert cc.check_compat(OPENAPI, COVERAGE)[0] == []
    assert cc.verify_manifest() == []


def test_coverage_fails_on_a_new_operation_and_on_a_stale_one() -> None:
    added = copy.deepcopy(OPENAPI)
    added["paths"]["/v1/brand-new"] = {"get": {"responses": {}}}
    assert any("GET /v1/brand-new: new operation" in p for p in cc.check_coverage(added, COVERAGE))
    removed = _without(OPENAPI, "/v1/search", "post")
    assert any("POST /v1/search: coverage.json lists an operation the contract no longer has" in p
               for p in cc.check_coverage(removed, COVERAGE))
    bare = copy.deepcopy(COVERAGE)
    bare["operations"]["GET /v1/health"] = {"excluded": "no"}
    assert any("needs a reason" in p for p in cc.check_coverage(OPENAPI, bare))
    missing_cli = copy.deepcopy(COVERAGE)
    del missing_cli["operations"]["GET /v1/health"]["cli"]
    assert any("needs a cli" in p for p in cc.check_coverage(OPENAPI, missing_cli))


def test_compat_fails_when_something_the_sdk_sends_disappears() -> None:
    problems, notes = cc.check_compat(_without(OPENAPI, "/v1/search", "post"), COVERAGE)
    assert any("POST /v1/search: removed, but the SDK calls it" in p for p in problems)

    schemas = copy.deepcopy(OPENAPI)
    del schemas["components"]["schemas"]["ScrapeRequest"]["properties"]["wait_for_ms"]
    assert any("body field 'wait_for_ms' is not in the contract" in p for p in cc.check_compat(schemas, COVERAGE)[0])

    enum = copy.deepcopy(OPENAPI)
    enum["components"]["schemas"]["ScrapeRequest"]["properties"]["engine"]["enum"] = ["static"]
    assert any("'browser' is not one of ['static']" in p for p in cc.check_compat(enum, COVERAGE)[0])

    required = copy.deepcopy(OPENAPI)
    required["components"]["schemas"]["SearchRequest"]["required"] = ["query", "tenant"]
    required["components"]["schemas"]["SearchRequest"]["properties"]["tenant"] = {"type": "string"}
    assert any("requires body field 'tenant'" in p for p in cc.check_compat(required, COVERAGE)[0])

    query = copy.deepcopy(OPENAPI)
    query["paths"]["/v1/jobs"]["get"]["parameters"].append({"in": "query", "name": "owner", "required": True,
                                                            "schema": {"type": "string"}})
    assert any("requires query parameter 'owner'" in p for p in cc.check_compat(query, COVERAGE)[0])

    keyless = copy.deepcopy(OPENAPI)
    keyless["paths"]["/v1/scrape"]["post"]["parameters"] = []
    assert any("no longer accepts" in p for p in cc.check_compat(keyless, COVERAGE)[0])

    added = copy.deepcopy(OPENAPI)
    added["paths"]["/v1/brand-new"] = {"get": {"responses": {}}}
    problems, notes = cc.check_compat(added, COVERAGE)
    assert problems == [] and any("GET /v1/brand-new: new operation" in n for n in notes)


def test_check_request_catches_wrong_paths_fields_values_and_headers() -> None:
    sends = COVERAGE["operations"][SCRAPE]["sends"]
    good = {"method": "POST", "path": "/v1/scrape", "query": {}, "body": {"url": "https://e.example"},
            "headers": {"Authorization": "Bearer k", "Idempotency-Key": "key-1"}}
    assert cc.check_request(OPENAPI, SCRAPE, good, sends) == []
    assert any("not in the contract" in p for p in
               cc.check_request(OPENAPI, SCRAPE, {**good, "body": {"url": "u", "mystery": 1}}, sends))
    assert any("'pdf' is not one of" in p for p in
               cc.check_request(OPENAPI, SCRAPE, {**good, "body": {"url": "u", "formats": ["pdf"]}}, sends))
    assert any("required body field 'url' is missing" in p for p in
               cc.check_request(OPENAPI, SCRAPE, {**good, "body": {"formats": ["markdown"]}}, sends))
    assert any("does not match" in p for p in cc.check_request(OPENAPI, SCRAPE, {**good, "path": "/v1/scrapes"}, sends))
    assert any("Idempotency-Key sent=False" in p for p in
               cc.check_request(OPENAPI, SCRAPE, {**good, "headers": {"Authorization": "Bearer k"}}, sends))
    search = COVERAGE["operations"]["POST /v1/search"]["sends"]
    keyed = {"method": "POST", "path": "/v1/search", "body": {"query": "q"},
             "headers": {"Authorization": "Bearer k", "Idempotency-Key": "x"}}
    assert any("does not accept it" in p for p in cc.check_request(OPENAPI, "POST /v1/search", keyed, search))
    diff = "GET /v1/datasets/{dataset_id}/diff"
    assert any("required query parameter 'to'" in p for p in cc.check_request(
        OPENAPI, diff, {"method": "GET", "path": "/v1/datasets/d1/diff", "query": {"from": "v1"},
                        "headers": {"Authorization": "Bearer k"}}, COVERAGE["operations"][diff]["sends"]))
    exact = cc.check_request(OPENAPI, SCRAPE, good, sends, exact=True)
    assert any("every option set" in p for p in exact)


def test_the_checker_command_line(tmp_path: Path) -> None:
    def run(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(TOOLS / "check_contracts.py"), *args], capture_output=True,
                              text=True, check=False)

    assert run("coverage").returncode == 0
    assert run("manifest").returncode == 0
    assert run("compat").returncode == 0
    broken = tmp_path / "openapi.json"
    broken.write_text(json.dumps(_without(OPENAPI, "/v1/search", "post")))
    result = run("compat", "--openapi", str(broken))
    assert result.returncode == 1 and "POST /v1/search" in result.stderr
    recorded = tmp_path / "recorded.json"
    recorded.write_text(json.dumps([{"route": "POST /v1/search", "request": {
        "method": "POST", "path": "/v1/search", "body": {"query": "q", "nope": 1},
        "headers": {"Authorization": "Bearer k"}}}]))
    result = run("requests", str(recorded))
    assert result.returncode == 1 and "'nope'" in result.stderr
    assert run("compat", "--openapi", str(tmp_path / "missing.json")).returncode == 2
    contracts = tmp_path / "contracts"
    contracts.mkdir()
    (contracts / cc.ERROR_CATALOGUE).write_text(json.dumps({"codes": [{"code": "not_found", "status": 404}]}))
    result = run("coverage", "--contracts", str(contracts))
    assert result.returncode == 1 and f"{cc.ERROR_CATALOGUE}: " in result.stderr and "missing key" in result.stderr
    shutil.copyfile(cc.CONTRACTS / cc.ERROR_CATALOGUE, contracts / cc.ERROR_CATALOGUE)
    assert run("coverage", "--contracts", str(contracts)).returncode == 0


def _entry(code: str, http_status: int | None = 404, retryable: bool = False, *,
           description: str = "Nothing here.", surfaces: list[str] | None = None) -> dict:
    return {"code": code, "http_status": http_status, "retryable": retryable, "description": description,
            "surfaces": surfaces or ["apexapi"]}


def _catalogue(*entries: dict) -> dict:
    """A catalogue in the backend's format: schema version, field and surface glossaries, the errors list."""
    return {"schema_version": 1,
            "fields": {"code": "The code.", "http_status": "Its status.", "retryable": "Resend?", "surfaces": "Where."},
            "surfaces": {"apexapi": "An ApexAPI error.", "mcp": "An MCP error.", "result": "A failed result."},
            "errors": list(entries or [_entry("not_found"), _entry("rate_limited", 429, True)])}


def test_the_vendored_error_catalogue_is_read_from_its_errors_list() -> None:
    raw = cc.load_json(cc.CONTRACTS / cc.ERROR_CATALOGUE)
    codes = cc.error_catalogue_codes(raw)
    assert list(codes) == [entry["code"] for entry in raw["errors"]]
    assert not set(codes) & {"schema_version", "fields", "surfaces", "errors"}     # never a top-level key
    assert codes["rate_limited"]["http_status"] == 429 and codes["rate_limited"]["retryable"] is True
    assert codes["submission_failed"]["retryable"] is False and codes["settlement_failed"]["retryable"] is False


def _set(path: tuple, value: object):
    def mutate(catalogue: dict) -> dict:
        node = catalogue
        for key in path[:-1]:
            node = node[key]
        node[path[-1]] = value
        return catalogue
    return mutate


def _drop(path: tuple):
    def mutate(catalogue: dict) -> dict:
        node = catalogue
        for key in path[:-1]:
            node = node[key]
        del node[path[-1]]
        return catalogue
    return mutate


REFUSED = [
    ("the guessed codes list", lambda c: {"codes": c["errors"]}, "missing key"),
    ("a bare list", lambda c: c["errors"], "must be a JSON object"),
    ("a code-to-entry map", lambda c: {e["code"]: e for e in c["errors"]}, "missing key"),
    ("an extra top-level key", _set(("codes",), []), "unexpected key 'codes'"),
    ("no surfaces glossary", _drop(("surfaces",)), "missing key 'surfaces'"),
    ("an unknown schema version", _set(("schema_version",), 2), "schema_version"),
    ("a boolean schema version", _set(("schema_version",), True), "schema_version"),
    ("fields that are not a map", _set(("fields",), ["code"]), "'fields'"),
    ("a field no entry has", _set(("fields", "severity"), "How bad."), "'severity'"),
    ("an empty surfaces glossary", _set(("surfaces",), {}), "'surfaces'"),
    ("an errors map", _set(("errors",), {"not_found": {}}), "'errors' must be a non-empty list"),
    ("no errors", _set(("errors",), []), "'errors' must be a non-empty list"),
    ("an entry that is not an object", _set(("errors", 0), "not_found"), r"errors\[0\]"),
    ("an entry with an extra key", _set(("errors", 0, "status"), 404), "unexpected key 'status'"),
    ("an entry without retryable", _drop(("errors", 0, "retryable")), "missing key 'retryable'"),
    ("a code that is not a string", _set(("errors", 0, "code"), 404), "'code'"),
    ("a code that is not snake_case", _set(("errors", 0, "code"), "Not Found"), "'code'"),
    ("a duplicate code", _set(("errors", 1, "code"), "not_found"), "duplicate code 'not_found'"),
    ("a status as text", _set(("errors", 0, "http_status"), "404"), "http_status"),
    ("a boolean status", _set(("errors", 0, "http_status"), True), "http_status"),
    ("a status out of range", _set(("errors", 0, "http_status"), 99), "http_status"),
    ("retryable as text", _set(("errors", 0, "retryable"), "false"), "retryable"),
    ("retryable as a number", _set(("errors", 0, "retryable"), 0), "retryable"),
    ("an empty description", _set(("errors", 0, "description"), " "), "description"),
    ("surfaces as text", _set(("errors", 0, "surfaces"), "apexapi"), "surfaces"),
    ("no surfaces", _set(("errors", 0, "surfaces"), []), "surfaces"),
    ("an unknown surface", _set(("errors", 0, "surfaces"), ["apexapi", "fax"]), "unknown surface 'fax'"),
    ("a repeated surface", _set(("errors", 0, "surfaces"), ["apexapi", "apexapi"]), "surfaces"),
    ("an API error without a status", _set(("errors", 0, "http_status"), None), "apexapi"),
]


@pytest.mark.parametrize(("mutate", "message"), [(m, msg) for _, m, msg in REFUSED], ids=[n for n, _, _ in REFUSED])
def test_an_error_catalogue_of_any_other_shape_is_refused(mutate, message: str) -> None:
    assert cc.error_catalogue_codes(_catalogue()).keys() == {"not_found", "rate_limited"}
    with pytest.raises(cc.CatalogueError, match=message):
        cc.error_catalogue_codes(mutate(_catalogue()))


SDK_ONLY = {"status": None, "retryable": False, "source": "sdk", "summary": "Raised by the SDKs, not the API."}


def test_the_error_catalogue_gate(tmp_path: Path) -> None:
    contracts = tmp_path / "contracts"
    contracts.mkdir()

    def gate(catalogue: object, error_codes: dict) -> list[str]:
        (contracts / cc.ERROR_CATALOGUE).write_text(json.dumps(catalogue))
        return cc.check_error_catalogue({"error_codes": error_codes}, contracts)

    known = {"not_found": {"status": 404, "retryable": False}, "rate_limited": {"status": 429, "retryable": True},
             "render_not_supported": SDK_ONLY}
    assert gate(_catalogue(), known) == []
    assert gate(_catalogue(_entry("not_found"), _entry("rate_limited", 429, True), _entry("a_new_code", 418)),
                known) == ["error code 'a_new_code' is in the catalogue but not in coverage.json error_codes"]
    assert gate(_catalogue(), {**known, "not_found": {"status": 410, "retryable": False}}) == [
        "error code 'not_found': the catalogue says http_status 404, coverage.json says status 410"]
    assert gate(_catalogue(), {**known, "rate_limited": {"status": 429, "retryable": False}}) == [
        "error code 'rate_limited': the catalogue says retryable true, coverage.json says false"]
    assert gate(_catalogue(), {**known, "rate_limited": {"status": 429}}) == [
        "error code 'rate_limited': coverage.json needs retryable true or false"]
    assert gate(_catalogue(), {**known, "gone_code": {"status": 400, "retryable": False}}) == [
        "error code 'gone_code' is in coverage.json but not in the catalogue (an SDK-only code says \"source\": \"sdk\")"]
    assert gate(_catalogue(), {**known, "not_found": {**SDK_ONLY, "status": 404}}) == [
        "error code 'not_found' is in the catalogue, so coverage.json must not mark it \"source\": \"sdk\""]
    (problem,) = gate({"codes": [{"code": "not_found", "status": 404}]}, known)
    assert problem.startswith(f"{cc.ERROR_CATALOGUE}: ") and "missing key" in problem


def test_the_errors_doc_shows_status_retryability_and_the_catalogue_description() -> None:
    catalogue = cc.error_catalogue_codes(_catalogue(
        _entry("not_found", description="Nothing here."),
        _entry("rate_limited", 429, True, description="Slow down | then retry."),
        _entry("fetch_failed", None, True, description="The page could not be fetched.", surfaces=["result"]),
        _entry("internal_error", 500, True, description="Unexpected.", surfaces=["apexapi", "result"]),
        _entry("key_revoked", None, False, description="Revoked.", surfaces=["mcp"])))
    coverage = {"error_codes": {"not_found": {"status": 404, "retryable": False},
                                "rate_limited": {"status": 429, "retryable": True},
                                "fetch_failed": {"status": None, "retryable": True},
                                "internal_error": {"status": 500, "retryable": True},
                                "key_revoked": {"status": None, "retryable": False},
                                "render_not_supported": SDK_ONLY}}
    table = gen_error_docs.render(coverage, catalogue)
    rows = [line for line in table.splitlines() if line.startswith("| `")]
    assert rows == [
        "| `not_found` | 404 | no | API | `NotFoundError` | `ErrorCode.NOT_FOUND` | Nothing here. |",
        "| `rate_limited` | 429 | yes | API | `RateLimitError` | `ErrorCode.RATE_LIMITED` | Slow down \\| then retry. |",
        "| `internal_error` | 500 | yes | API, result | `ServerError` | `ErrorCode.INTERNAL_ERROR` | Unexpected. |",
        "| `fetch_failed` | none | yes | result | - | `ErrorCode.FETCH_FAILED` | The page could not be fetched. |",
        "| `key_revoked` | none | no | MCP | - | `ErrorCode.KEY_REVOKED` | Revoked. |",
        "| `render_not_supported` | none | no | SDK | `ScrawlError` | `ErrorCode.RENDER_NOT_SUPPORTED` | "
        "Raised by the SDKs, not the API. |",
    ]
    assert "vendored error catalogue" in table


def test_the_errors_doc_marks_the_codes_never_retried_for_you() -> None:
    doc = (REPO / "docs" / "errors.md").read_text(encoding="utf-8")
    for code in ("settlement_failed", "submission_failed"):
        (row,) = [line for line in doc.splitlines() if line.startswith(f"| `{code}` |")]
        assert row.split(" | ")[2] == "no", row
    (row,) = [line for line in doc.splitlines() if line.startswith("| `rate_limited` |")]
    assert row.split(" | ")[1:3] == ["429", "yes"]


def test_docs_errors_table_is_generated_and_current() -> None:
    assert gen_error_docs.main(["--check"]) == 0


def _bundle(tmp_path: Path, files: dict[str, bytes], **manifest: object) -> Path:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    for name, data in files.items():
        (bundle / name).write_bytes(data)
    listed = {name: {"sha256": hashlib.sha256(data).hexdigest()} for name, data in files.items()}
    (bundle / "MANIFEST.json").write_text(json.dumps({"files": listed, "source": {"backend_version": "9.9.9"},
                                                      **manifest}))
    return bundle


def test_sync_refuses_a_bundle_that_does_not_verify(tmp_path: Path) -> None:
    openapi = (REPO / "contracts" / "apexapi_openapi.json").read_bytes()
    bundle = _bundle(tmp_path, {"apexapi_openapi.json": openapi})
    sync_contracts.verify_bundle(bundle)
    (bundle / "apexapi_openapi.json").write_bytes(openapi + b" ")
    with pytest.raises(sync_contracts.BundleError, match="does not match"):
        sync_contracts.verify_bundle(bundle)
    shutil.rmtree(bundle)
    bundle = _bundle(tmp_path, {"apexapi_openapi.json": openapi})
    (bundle / "extra.json").write_text("{}")
    with pytest.raises(sync_contracts.BundleError, match="not listed"):
        sync_contracts.verify_bundle(bundle)
    shutil.rmtree(bundle)
    with pytest.raises(sync_contracts.BundleError, match="lacks apexapi_openapi.json"):
        sync_contracts.verify_bundle(_bundle(tmp_path, {"mcp_tools.json": b"[]"}))
    shutil.rmtree(tmp_path / "bundle")
    with pytest.raises(sync_contracts.BundleError, match="digest does not match"):
        sync_contracts.verify_bundle(_bundle(tmp_path, {"apexapi_openapi.json": openapi},
                                             digest_algorithm=cc.DIGEST_ALGORITHM, digest="sha256:" + "0" * 64))
    shutil.rmtree(tmp_path / "bundle")
    bundle = _bundle(tmp_path, {"apexapi_openapi.json": openapi})
    manifest = json.loads((bundle / "MANIFEST.json").read_text())
    manifest["files"]["../escape.json"] = {"sha256": "0" * 64}
    (bundle / "MANIFEST.json").write_text(json.dumps(manifest))
    with pytest.raises(sync_contracts.BundleError, match="plain file names"):
        sync_contracts.verify_bundle(bundle)


def test_sync_refuses_an_error_catalogue_it_cannot_read(tmp_path: Path) -> None:
    openapi = (REPO / "contracts" / "apexapi_openapi.json").read_bytes()
    guessed = json.dumps({"codes": [{"code": "not_found", "status": 404}]}).encode()
    with pytest.raises(sync_contracts.BundleError, match="apexapi_errors.json.*missing key"):
        sync_contracts.verify_bundle(_bundle(tmp_path, {"apexapi_openapi.json": openapi, "apexapi_errors.json": guessed}))
    shutil.rmtree(tmp_path / "bundle")
    listed, _ = sync_contracts.verify_bundle(_bundle(tmp_path, {
        "apexapi_openapi.json": openapi, "apexapi_errors.json": json.dumps(_catalogue()).encode()}))
    assert sorted(listed) == ["apexapi_errors.json", "apexapi_openapi.json"]


def test_sync_replaces_the_contracts_and_writes_a_verifiable_manifest(tmp_path: Path) -> None:
    openapi = (REPO / "contracts" / "apexapi_openapi.json").read_bytes()
    errors = json.dumps(_catalogue()).encode()
    bundle = _bundle(tmp_path, {"apexapi_openapi.json": openapi, "apexapi_errors.json": errors})
    target = tmp_path / "contracts"
    target.mkdir()
    (target / "stale.json").write_text("{}")
    manifest = sync_contracts.sync(bundle, target, update_sdks=False)
    assert sorted(p.name for p in target.iterdir()) == ["MANIFEST.json", "apexapi_errors.json", "apexapi_openapi.json"]
    assert cc.verify_manifest(target) == []
    assert manifest["source"] == {"backend_version": "9.9.9"}
    assert manifest["digest"] == cc.contract_digest({name: entry["sha256"] for name, entry in manifest["files"].items()})


def test_the_digest_is_reproducible_with_sha256sum() -> None:
    manifest = json.loads((REPO / "contracts" / "MANIFEST.json").read_text())
    listing = "".join(f"{manifest['files'][name]['sha256']}  {name}\n" for name in sorted(manifest["files"]))
    assert manifest["digest"] == "sha256:" + hashlib.sha256(listing.encode()).hexdigest()
    # The command docs/compatibility.md gives, run as written: the documentation must not drift from the digest.
    if not (shutil.which("sha256sum") and shutil.which("sh")):
        pytest.skip("sha256sum is not installed")
    doc = (REPO / "docs" / "compatibility.md").read_text(encoding="utf-8")
    (command,) = [line for line in doc.splitlines() if line.startswith("cd contracts && ")]
    printed = subprocess.run(["sh", "-c", command], cwd=REPO, capture_output=True, text=True, check=True).stdout
    assert manifest["digest"] == "sha256:" + printed.split()[0]
