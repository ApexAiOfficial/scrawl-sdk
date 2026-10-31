"""The ``scrawl`` CLI: every command against its route, exit codes, downloads, AI keys and ``doctor``."""

from __future__ import annotations

import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
from conftest import COVERAGE, Recorder, body, make_client

from scrawl import Scrawl, cli
from scrawl.cli import main as cli_main

PAGE = "https://e.example/page"
COVERED = {route: entry for route, entry in COVERAGE["operations"].items() if "excluded" not in entry}


# -- every command calls its route with contract-valid requests ------------------------------------

def fake_client(fake: Any, **kwargs: Any) -> Scrawl:
    """A client whose transport is the in-memory fake ApexAPI (contract-checked requests and answers)."""
    from fake_apexapi import API_KEY

    def handler(request: httpx.Request) -> httpx.Response:
        reply = fake.handle(request.method, request.url.raw_path.decode(), dict(request.headers), request.content)
        if reply.raw is not None:
            return httpx.Response(reply.status, content=reply.raw, headers=reply.headers)
        content = b"" if reply.body is None else json.dumps(reply.body).encode()
        headers = {**reply.headers, **({"Content-Type": "application/json"} if reply.body is not None else {})}
        return httpx.Response(reply.status, content=content, headers=headers)

    return Scrawl(API_KEY, base_url="https://scrawl.test", http_client=httpx.Client(transport=httpx.MockTransport(handler)),
                  **kwargs)


def _argv(route: str, tmp: Path) -> list[str]:
    return {
        "POST /v1/scrape": ["scrape", PAGE, "--format", "markdown", "--format", "json", "--instruction", "name",
                            "--profile", "p", "--browser", "--wait-for", "100", "--wait", "5"],
        "GET /v1/scrape/{job_id}/content": ["result", "j1", "--wait", "5"],
        "POST /v1/map": ["map", PAGE, "--limit", "5", "--wait", "5"],
        "POST /v1/scrape/batch": ["batch", PAGE, "https://b.example/", "--format", "json", "--instruction", "x",
                                  "--wait", "30"],
        "GET /v1/scrape/batch/{batch_id}": ["batch-status", "b1", "--wait", "5"],
        "POST /v1/extract": ["extract", "j1", "--instruction", "name", "--profile", "p"],
        "POST /v1/ask": ["ask", "Which lamp is cheapest?", "--dataset", "d1", "--profile", "p"],
        "GET /v1/ai/providers": ["ai", "providers", "list"],
        "PUT /v1/ai/providers/{profile}": ["ai", "providers", "set", "p", "--provider", "example", "--model", "m",
                                           "--base-url", "https://ai.example/v1"],
        "DELETE /v1/ai/providers/{profile}": ["ai", "providers", "remove", "p"],
        "POST /v1/ai/providers/{profile}/default": ["ai", "providers", "default", "p"],
        "POST /v1/ai/providers/{profile}/test": ["ai", "providers", "test", "p"],
        "GET /v1/ai/usage": ["ai", "providers", "usage", "--days", "7"],
        "POST /v1/crawls": ["crawl", "example-target", "--export-format", "csv", "--max-items", "5",
                            "--max-seconds", "60"],
        "GET /v1/jobs/{job_id}": ["job", "j1", "--wait", "5"],
        "GET /v1/jobs": ["jobs", "--limit", "5", "--status", "RUNNING", "--cursor", "c"],
        "POST /v1/jobs/{job_id}/cancel": ["cancel", "j1"],
        "GET /v1/artifacts/{job_id}": ["artifacts", "list", "j1"],
        "GET /v1/artifacts/{job_id}/{filename}": ["artifacts", "download", "j1", "response.html", "--out", str(tmp)],
        "GET /v1/datasets": ["datasets", "--limit", "5"],
        "GET /v1/datasets/{dataset_id}": ["datasets", "get", "d1"],
        "GET /v1/datasets/{dataset_id}/versions": ["datasets", "versions", "d1", "--limit", "5", "--status",
                                                   "completed"],
        "POST /v1/datasets/{dataset_id}/active-version": ["datasets", "activate", "d1", "v-1"],
        "GET /v1/datasets/{dataset_id}/diff": ["datasets", "diff", "d1", "v-1", "v-2", "--limit", "3"],
        "GET /v1/datasets/{dataset_id}/fields": ["datasets", "fields", "d1", "--version", "v-2"],
        "POST /v1/datasets/{dataset_id}/query": ["datasets", "query", "d1", "--where", "price", "lt", "20",
                                                 "--version", "v-2", "--limit", "5"],
        "POST /v1/datasets/{dataset_id}/extract": ["datasets", "extract", "d1", "--instruction", "x",
                                                   "--max-records", "5"],
        "PUT /v1/datasets/{dataset_id}/records/{record_id}/quarantine": ["datasets", "quarantine", "d1", "r1",
                                                                         "--reason", "spam"],
        "DELETE /v1/datasets/{dataset_id}/records/{record_id}/quarantine": ["datasets", "release", "d1", "r1"],
        "POST /v1/search": ["search", "lamp", "--limit", "3"],
        "GET /v1/documents/{document_id}": ["document", "doc-1"],
        "GET /v1/credits/balance": ["balance"],
        "GET /v1/health": ["doctor"],
        "POST /v1/assets": ["assets", PAGE, "--class", "images", "--max-credits", "5", "--wait", "0"],
        "POST /v1/assets/quote": ["assets-quote", PAGE, "--class", "documents", "--max-items", "3"],
        "GET /v1/assets/{job_id}": ["assets-result", "aj1", "--view", "skipped"],
        "GET /v1/assets/{job_id}/files/{asset_id}": ["assets-result", "aj1", "--out", str(tmp)],
    }[route]


@pytest.mark.parametrize("route", sorted(COVERED))
def test_each_covered_operation_is_reachable_from_the_cli(route: str, tmp_path: Path, monkeypatch, capsys) -> None:
    from fake_apexapi import NOW, FakeApexAPI

    monkeypatch.setenv("SCRAWL_AI_API_KEY", "sk-ai-test-key")
    fake = FakeApexAPI()
    fake.profiles["p"] = {"profile": "p", "provider": "example", "model": "m", "base_url": "https://ai.example/v1",
                          "key_fingerprint": "sha256:0", "is_default": True, "created_at": NOW, "updated_at": NOW}
    code = cli_main(_argv(route, tmp_path), client=fake_client(fake))
    out = capsys.readouterr()
    assert code == 0, out.err
    assert route in {item["route"] for item in fake.requests}
    assert fake.problems == []
    assert "sk-ai-test-key" not in out.out + out.err


def test_the_cli_documents_its_exit_codes() -> None:
    doc = cli.__doc__ or ""
    for code in range(6):
        assert re.search(rf"^\s+{code}\s+\S", doc, re.M), code
    assert (cli.EXIT_OK, cli.EXIT_FAILED, cli.EXIT_USAGE, cli.EXIT_CONFIG, cli.EXIT_PENDING, cli.EXIT_ERROR) == \
        (0, 1, 2, 3, 4, 5)


# -- scrape, map, batch, ask, crawl -----------------------------------------------------------------

def test_cli_prints_markdown_and_maps_exit_codes(capsys) -> None:
    rec = Recorder(httpx.Response(200, json={"job_id": "j", "status": "completed", "url": "u", "markdown": "# Page"}),
                   httpx.Response(200, json={"job_id": "j", "status": "failed", "url": "u", "error": "Not a text page"}),
                   httpx.Response(401, json={"detail": "bad key", "code": "unauthorized"}))
    c = make_client(rec, max_retries=0)
    assert cli_main(["scrape", "https://e.example/"], client=c) == 0 and capsys.readouterr().out.strip() == "# Page"
    assert cli_main(["scrape", "https://e.example/x.png"], client=c) == 1
    assert cli_main(["jobs"], client=c) == 3                      # authentication -> 3
    assert cli_main(["job", "x"], client=make_client(Recorder(httpx.Response(422, json={"detail": "bad"})),
                                                     max_retries=0)) == 5   # another API error -> 5


def test_cli_strips_terminal_control_characters(capsys) -> None:
    rec = Recorder(httpx.Response(200, json={"job_id": "j", "status": "completed", "url": "u",
                                             "markdown": "ok\x1b]8;;evil\x07 done"}))
    assert cli_main(["scrape", "https://e.example/"], client=make_client(rec)) == 0
    assert "\x1b" not in capsys.readouterr().out


def test_cli_configuration_problems_exit_3_without_sending_anything(monkeypatch, capsys) -> None:
    monkeypatch.delenv("SCRAWL_API_KEY", raising=False)
    monkeypatch.delenv("SCRAWL_ALLOW_INSECURE_HTTP", raising=False)
    monkeypatch.setenv("SCRAWL_BASE_URL", "http://scrawl-lan.test:8088")
    assert cli_main(["jobs"]) == 3
    assert "plain HTTP" in capsys.readouterr().err
    rec = Recorder()
    no_key = Scrawl(base_url="https://scrawl.test", http_client=httpx.Client(transport=httpx.MockTransport(rec)))
    assert cli_main(["jobs"], client=no_key) == 3 and rec.requests == []
    assert "SCRAWL_API_KEY" in capsys.readouterr().err


def test_batch_status_exit_codes(capsys) -> None:
    def batch(status: str, items: list[str]) -> httpx.Response:
        return httpx.Response(200, json={"batch_id": "b1", "status": status, "total": len(items),
                                         "items": [{"url": "u", "status": s} for s in items]})

    assert cli_main(["batch-status", "b1"], client=make_client(Recorder(batch("completed", ["completed"])))) == 0
    assert cli_main(["batch-status", "b1"], client=make_client(Recorder(batch("completed", ["failed"])))) == 1
    assert cli_main(["batch-status", "b1"], client=make_client(Recorder(batch("running", ["pending"])))) == 4
    rec = Recorder(batch("running", ["pending"]), batch("completed", ["completed"]))
    assert cli_main(["batch-status", "b1", "--wait", "30"], client=make_client(rec)) == 0
    assert 25 <= int(rec.requests[0].url.params["wait_seconds"]) <= 30       # a server-side wait, not polling


def test_ask_prints_the_answer_and_its_sources(capsys) -> None:
    answer = {"answer": "19.50 EUR [1]", "answerable": True, "sources_considered": 2, "provider": "x", "model": "y",
              "usage": {}, "citations": [{"tag": "1", "title": "Lamp", "url": "https://shop.example/lamp",
                                          "dataset_id": "d1", "document_id": "doc-1"}]}
    rec = Recorder(httpx.Response(200, json=answer), httpx.Response(200, json=answer))
    c = make_client(rec)
    assert cli_main(["ask", "How much is the lamp?", "--dataset", "d1"], client=c) == 0
    out = capsys.readouterr().out
    assert out.startswith("19.50 EUR [1]") and "[1] Lamp https://shop.example/lamp" in out
    assert body(rec.requests[0]) == {"question": "How much is the lamp?", "dataset_id": "d1"}
    assert cli_main(["--json", "ask", "How much is the lamp?"], client=c) == 0
    assert json.loads(capsys.readouterr().out)["citations"][0]["tag"] == "1"


def _job(status: str) -> httpx.Response:
    return httpx.Response(200, json={"job_id": "c1", "command": "crawl", "args": [], "status": status,
                                     "engine_id": "e", "artifacts_url": "", "result_url": ""})


LAUNCH = {"job_id": "c1", "status": "PENDING", "crawl_target": "t", "dataset_id": "d1", "dataset_version_id": "v2",
          "dataset_artifact": "items.jsonl", "export_format": "jsonlines", "max_items": 5, "max_seconds": 60,
          "links": {}}


def test_crawl_starts_and_optionally_waits_for_the_job(capsys, monkeypatch) -> None:
    rec = Recorder(httpx.Response(202, json=LAUNCH))
    assert cli_main(["crawl", "t", "--max-items", "5"], client=make_client(rec)) == 0
    assert json.loads(capsys.readouterr().out)["dataset_id"] == "d1"
    assert body(rec.requests[0]) == {"crawl_target": "t", "max_items": 5} and rec.requests[0].headers["Idempotency-Key"]
    clock = iter(range(0, 10**6, 100))                                  # each look at the clock: 100 s later
    monkeypatch.setattr("scrawl._client.time.monotonic", lambda: next(clock))
    for status, code in (("COMPLETED", 0), ("FAILED", 1), ("CANCELLED", 1), ("RUNNING", 4)):
        rec = Recorder(httpx.Response(202, json=LAUNCH), _job(status))
        assert cli_main(["crawl", "t", "--wait", "120"], client=make_client(rec)) == code, status
        assert len(rec.requests) == 2
        printed = json.loads(capsys.readouterr().out)
        assert printed["job"]["status"] == status and printed["dataset_version_id"] == "v2"


# -- datasets -------------------------------------------------------------------------------------------

def test_datasets_without_an_action_still_lists(capsys) -> None:
    rec = Recorder()
    c = make_client(rec)
    assert cli_main(["datasets"], client=c) == 0
    assert cli_main(["datasets", "--limit", "5", "--cursor", "c1"], client=c) == 0
    assert cli_main(["datasets", "list", "--limit", "7"], client=c) == 0
    assert [dict(r.url.params) for r in rec.requests] == [{"limit": "20"}, {"limit": "5", "cursor": "c1"},
                                                          {"limit": "7"}]
    assert all(r.url.path == "/v1/datasets" for r in rec.requests)


def test_datasets_query_parses_where_clauses_and_a_filters_file(tmp_path, capsys) -> None:
    rec = Recorder()
    c = make_client(rec)
    assert cli_main(["datasets", "query", "d1", "--where", "price", "lt", "20", "--where", "sku", "exists", "true",
                     "--where", "name", "eq", "Desk lamp", "--where", "tag", "in", '["a", "b"]'], client=c) == 0
    assert body(rec.requests[0])["filters"] == [
        {"field": "price", "op": "lt", "value": 20}, {"field": "sku", "op": "exists", "value": True},
        {"field": "name", "op": "eq", "value": "Desk lamp"}, {"field": "tag", "op": "in", "value": ["a", "b"]}]
    filters = tmp_path / "filters.json"
    filters.write_text(json.dumps([{"field": "price", "op": "gte", "value": 5}]))
    assert cli_main(["datasets", "query", "d1", "--filters-file", str(filters), "--where", "price", "lte", "9"],
                    client=c) == 0
    assert body(rec.requests[1])["filters"] == [{"field": "price", "op": "gte", "value": 5},
                                                {"field": "price", "op": "lte", "value": 9}]
    assert cli_main(["datasets", "query", "d1", "--where", "price", "below", "9"], client=c) == 2
    assert "op must be one of" in capsys.readouterr().err
    assert len(rec.requests) == 2


def test_datasets_extract_can_wait_for_its_job(tmp_path, capsys) -> None:
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps({"type": "object", "properties": {"price": {"type": "number"}}}))
    launch = {"job_id": "c1", "status": "PENDING", "source_dataset_id": "d1", "source_version_id": "v1",
              "target_dataset_id": "d2", "target_version_id": "v9", "links": {}}
    rec = Recorder(httpx.Response(202, json=launch), _job("COMPLETED"))
    assert cli_main(["datasets", "extract", "d1", "--schema", str(schema), "--profile", "p", "--version", "v1",
                     "--max-records", "10", "--wait", "60"], client=make_client(rec)) == 0
    sent = body(rec.requests[0])
    assert sent == {"schema": {"type": "object", "properties": {"price": {"type": "number"}}}, "profile": "p",
                    "version_id": "v1", "max_records": 10}
    assert rec.requests[0].headers["Idempotency-Key"] and rec.requests[1].url.path == "/v1/jobs/c1"
    assert json.loads(capsys.readouterr().out)["target_version_id"] == "v9"


# -- AI providers: the key never travels on the command line ----------------------------------------

def test_ai_providers_set_reads_the_key_from_an_env_var_or_stdin(monkeypatch, capsys) -> None:
    rec = Recorder()
    c = make_client(rec)
    monkeypatch.setenv("SCRAWL_AI_API_KEY", "sk-ai-from-default-env")
    assert cli_main(["ai", "providers", "set", "main", "--provider", "example"], client=c) == 0
    monkeypatch.setenv("MY_AI_KEY", "sk-ai-from-named-env")
    assert cli_main(["ai", "providers", "set", "main", "--provider", "example", "--key-env", "MY_AI_KEY"],
                    client=c) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("sk-ai-from-stdin\n"))
    assert cli_main(["ai", "providers", "set", "main", "--provider", "example", "--key-stdin"], client=c) == 0
    assert [body(r)["api_key"] for r in rec.requests] == ["sk-ai-from-default-env", "sk-ai-from-named-env",
                                                          "sk-ai-from-stdin"]
    assert all(r.method == "PUT" and r.url.path == "/v1/ai/providers/main" for r in rec.requests)
    out = capsys.readouterr()
    assert "sk-ai-from" not in out.out + out.err


def test_ai_providers_set_without_a_key_is_a_configuration_error(monkeypatch, capsys) -> None:
    monkeypatch.delenv("SCRAWL_AI_API_KEY", raising=False)
    rec = Recorder()
    assert cli_main(["ai", "providers", "set", "main", "--provider", "example"], client=make_client(rec)) == 3
    assert "SCRAWL_AI_API_KEY" in capsys.readouterr().err
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert cli_main(["ai", "providers", "set", "main", "--provider", "x", "--key-stdin"], client=make_client(rec)) == 3
    assert rec.requests == []


def test_a_key_passed_as_an_argument_is_refused_and_never_echoed(capsys) -> None:
    for argv in (["ai", "providers", "set", "main", "--provider", "x", "--api-key", "sk-leaked-123"],
                 ["ai", "providers", "set", "main", "--provider", "x", "sk-leaked-123"]):
        with pytest.raises(SystemExit) as usage:
            cli_main(argv, client=make_client(Recorder()))
        assert usage.value.code == 2
        assert "sk-leaked-123" not in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli_main(["ai", "providers", "set", "main", "--provider", "x", "--key-env", "not a name"])
    capsys.readouterr()


def test_ai_providers_test_exits_1_when_the_provider_fails_and_remove_reports(capsys) -> None:
    failing = {"profile": "p", "provider": "x", "model": "m", "ok": False, "model_listed": None, "latency_ms": 5,
               "error": "invalid key", "error_kind": "auth"}
    rec = Recorder(httpx.Response(200, json=failing), httpx.Response(204))
    c = make_client(rec)
    assert cli_main(["ai", "providers", "test", "p"], client=c) == 1
    capsys.readouterr()
    assert cli_main(["ai", "providers", "remove", "p"], client=c) == 0
    assert json.loads(capsys.readouterr().out) == {"profile": "p", "removed": True}
    assert [(r.method, r.url.path) for r in rec.requests] == [("POST", "/v1/ai/providers/p/test"),
                                                              ("DELETE", "/v1/ai/providers/p")]


# -- doctor --------------------------------------------------------------------------------------------

def _health_then(*responses: httpx.Response) -> Recorder:
    return Recorder(httpx.Response(200, json={"service": "ApexAPI", "status": "ok"}), *responses)


def test_doctor_reports_a_ready_setup(capsys) -> None:
    rec = _health_then(httpx.Response(200, json={"jobs": []}))
    assert cli_main(["doctor"], client=make_client(rec)) == 0
    out = capsys.readouterr()
    for check in ("base_url", "tls", "reachable", "auth"):
        assert re.search(rf"^ok\s+{check}\b", out.out, re.M), (check, out.out)
    assert "sk-test" not in out.out + out.err
    assert [r.url.path for r in rec.requests] == ["/v1/health", "/v1/jobs"]
    assert "Authorization" not in rec.requests[0].headers


def test_doctor_json_and_auth_failures(capsys) -> None:
    rec = _health_then(httpx.Response(401, json={"detail": "Invalid API key", "code": "unauthorized"}))
    assert cli_main(["--json", "doctor"], client=make_client(rec, max_retries=0)) == 3
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] is False and [c["status"] for c in report["checks"]] == ["ok", "ok", "ok", "fail"]
    rec = _health_then(httpx.Response(403, json={"detail": "missing scope", "code": "forbidden"}))
    assert cli_main(["--json", "doctor"], client=make_client(rec, max_retries=0)) == 0
    assert json.loads(capsys.readouterr().out)["checks"][-1]["status"] == "warn"


def test_doctor_without_a_key_or_a_server(monkeypatch, capsys) -> None:
    monkeypatch.delenv("SCRAWL_API_KEY", raising=False)
    rec = _health_then()
    no_key = Scrawl(base_url="https://scrawl.test", http_client=httpx.Client(transport=httpx.MockTransport(rec)))
    assert cli_main(["doctor"], client=no_key) == 3
    assert re.search(r"^fail\s+auth\s+no API key", capsys.readouterr().out, re.M)
    monkeypatch.setattr("scrawl._client.time.sleep", lambda s: None)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    down = Scrawl("k", base_url="https://scrawl.test", http_client=httpx.Client(transport=httpx.MockTransport(refused)))
    assert cli_main(["doctor"], client=down) == 5
    assert re.search(r"^fail\s+reachable\s+Connection failed", capsys.readouterr().out, re.M)

    def bad_certificate(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed")

    tls = Scrawl("k", base_url="https://scrawl.test", http_client=httpx.Client(transport=httpx.MockTransport(bad_certificate)))
    assert cli_main(["doctor"], client=tls) == 3
    assert re.search(r"^fail\s+tls\s+TLS failed", capsys.readouterr().out, re.M)


def test_doctor_flags_configuration_before_any_request(monkeypatch, capsys) -> None:
    monkeypatch.delenv("SCRAWL_ALLOW_INSECURE_HTTP", raising=False)
    monkeypatch.setenv("SCRAWL_BASE_URL", "http://scrawl-lan.test:8088")
    assert cli_main(["doctor"]) == 3
    assert re.search(r"^fail\s+base_url\s+Refusing", capsys.readouterr().out, re.M)
    insecure = Scrawl("k", base_url="http://scrawl-lan.test:8088", allow_insecure_http=True,
                      http_client=httpx.Client(transport=httpx.MockTransport(_health_then(httpx.Response(200, json={})))))
    assert cli_main(["doctor"], client=insecure) == 0
    assert re.search(r"^warn\s+tls\s+plain HTTP to a remote host", capsys.readouterr().out, re.M)


# -- artifacts: checked against the list, never overwriting ------------------------------------------

HTML = b"<html><body>hello</body></html>"


def _listing(*entries: dict) -> httpx.Response:
    return httpx.Response(200, json={"job_id": "j1", "artifacts": list(entries)})


def _entry(name: str = "response.html", data: bytes = HTML, **extra: Any) -> dict:
    return {"name": name, "type": "html", "size_bytes": len(data), "download_url": f"/v1/artifacts/j1/{name}", **extra}


def test_artifacts_download_writes_every_listed_file_once(tmp_path, capsys) -> None:
    other = b'{"a": 1}'
    rec = Recorder(_listing(_entry(), _entry("data.json", other, type="json", sha256=hashlib.sha256(other).hexdigest())),
                   httpx.Response(200, content=HTML), httpx.Response(200, content=other))
    assert cli_main(["artifacts", "download", "j1", "--out", str(tmp_path)], client=make_client(rec)) == 0
    assert (tmp_path / "response.html").read_bytes() == HTML and (tmp_path / "data.json").read_bytes() == other
    report = json.loads(capsys.readouterr().out)
    assert [f["verified"] for f in report["files"]] == [["size"], ["size", "sha256"]]
    assert report["files"][0]["sha256"] == hashlib.sha256(HTML).hexdigest()
    rec = Recorder(_listing(_entry()), httpx.Response(200, content=HTML))
    assert cli_main(["artifacts", "download", "j1", "--out", str(tmp_path)], client=make_client(rec)) == 2
    assert (tmp_path / "response.html").read_bytes() == HTML                  # never overwritten


def test_artifacts_download_refuses_a_file_that_does_not_match_its_listing(tmp_path, capsys) -> None:
    rec = Recorder(_listing(_entry(data=HTML + b"x")), httpx.Response(200, content=HTML))
    assert cli_main(["artifacts", "download", "j1", "--out", str(tmp_path)], client=make_client(rec)) == 1
    assert "not written" in capsys.readouterr().err and not list(tmp_path.iterdir())
    rec = Recorder(_listing(_entry(sha256="0" * 64)), httpx.Response(200, content=HTML))
    assert cli_main(["artifacts", "download", "j1", "--out", str(tmp_path)], client=make_client(rec)) == 1
    assert "sha256 mismatch" in capsys.readouterr().err and not list(tmp_path.iterdir())
    rec = Recorder(_listing(_entry()))
    assert cli_main(["artifacts", "download", "j1", "secret.txt", "--out", str(tmp_path)], client=make_client(rec)) == 1
    assert "not in job" in capsys.readouterr().err and len(rec.requests) == 1


def test_artifacts_download_markdown_and_hostile_names(tmp_path, capsys) -> None:
    rec = Recorder(_listing(_entry()), httpx.Response(200, content=b"# hello\n"))
    assert cli_main(["artifacts", "download", "j1", "response.html", "--format", "markdown", "--out", str(tmp_path)],
                    client=make_client(rec)) == 0
    assert (tmp_path / "response.md").read_bytes() == b"# hello\n"
    assert rec.requests[1].url.params["format"] == "markdown"
    assert json.loads(capsys.readouterr().out)["files"][0]["verified"] == []
    hostile = "..\\..\\evil\x1b.sh"
    rec = Recorder(_listing(_entry(hostile, b"x")), httpx.Response(200, content=b"x"))
    out = tmp_path / "out"
    assert cli_main(["artifacts", "download", "j1", "--out", str(out)], client=make_client(rec)) == 0
    written = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*") if p.is_file())
    assert written == ["out/evil.sh", "response.md"]                       # the whole tree: nothing else, nowhere else
    assert not (tmp_path.parent / "evil.sh").exists() and not (tmp_path / "evil.sh").exists()


# -- assets (unchanged behaviour) ---------------------------------------------------------------------

ASSET_JOB = {"job_id": "aj1", "status": "pending", "url": PAGE, "classes": ["images"], "estimated_credits": 3,
             "reserved_credits": None, "max_credits": None, "metered": False,
             "links": {"job": "/v1/jobs/aj1", "assets": "/v1/assets/aj1"}}


def asset_item(asset_id: str, data: bytes, *, filename: str | None = "photo.png", asset_class: str = "images",
               sha256: str | None = None) -> dict:
    return {"asset_id": asset_id, "asset_class": asset_class, "mime_type": "image/png", "size_bytes": len(data),
            "sha256": sha256 or hashlib.sha256(data).hexdigest(), "original_url": f"{PAGE}/{filename}",
            "final_url": None, "filename": filename, "download_url": f"/v1/assets/aj1/files/{asset_id}"}


def asset_result(status: str, *, assets: list | None = None, skipped: list | None = None, view: str = "assets",
                 partial: bool = False, next_cursor: str | None = None) -> dict:
    return {"job_id": "aj1", "status": status, "url": PAGE, "classes": ["images"], "partial": partial,
            "partial_reason": "job_timeout" if partial else None, "error_code": None, "failure_reason": None,
            "counts": {"discovered": 3, "stored": len(assets or []), "skipped": len(skipped or []), "duplicates": 0,
                       "skipped_omitted": 0},
            "total_fetched_bytes": 0, "total_stored_bytes": 0, "files_available": status == "completed",
            "billing": {"metered": False, "estimated_credits": None, "reserved_credits": None,
                        "charged_credits": None, "state": "unmetered"},
            "view": view, "assets": (assets or []) if view == "assets" else None,
            "skipped": (skipped or []) if view == "skipped" else None, "next_cursor": next_cursor,
            "untrusted_external_content": True, "links": {"self": "/v1/assets/aj1"}}


class AssetAPI:
    """A mock ApexAPI for asset jobs: the submit, RESULTS in order (the last repeats), FILES by asset id."""

    def __init__(self, *results: dict, files: dict[str, bytes] | None = None) -> None:
        self.results = list(results)
        self.files = files or {}
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.method == "POST":
            return httpx.Response(202, json=ASSET_JOB)
        if "/files/" in path:
            data = self.files[path.rsplit("/", 1)[1]]
            return httpx.Response(200, content=data, headers={"Content-Type": "application/octet-stream",
                                                              "X-Asset-SHA256": hashlib.sha256(data).hexdigest(),
                                                              "X-Untrusted-External-Content": "true"})
        return httpx.Response(200, json=self.results.pop(0) if len(self.results) > 1 else self.results[0])

    def downloads(self) -> list[str]:
        return [r.url.path for r in self.requests if "/files/" in r.url.path]


def test_cli_assets_exit_codes(capsys) -> None:
    for status, code in (("completed", 0), ("failed", 1), ("cancelled", 1), ("orphaned", 1), ("pending", 4),
                         ("running", 4)):
        api = AssetAPI(asset_result(status))
        assert cli_main(["assets", PAGE, "--wait", "0"], client=make_client(api)) == code, status
        assert json.loads(capsys.readouterr().out)["status"] == status          # the result is printed as JSON
    api = AssetAPI(asset_result("completed", partial=True))
    assert cli_main(["assets", PAGE, "--class", "images", "--class", "video", "--max-items", "5",
                     "--max-credits", "9"], client=make_client(api)) == 0       # partial is still completed
    assert body(api.requests[0]) == {"url": PAGE, "classes": ["images", "video"], "max_items": 5, "max_credits": 9}
    assert api.requests[1].url.params["wait_seconds"] == "60"
    for status, code in (("completed", 0), ("pending", 4), ("failed", 1)):
        assert cli_main(["assets-result", "aj1"], client=make_client(AssetAPI(asset_result(status)))) == code
    api = AssetAPI(asset_result("completed", view="skipped"))
    assert cli_main(["assets-result", "aj1", "--view", "skipped", "--wait", "30"], client=make_client(api)) == 0
    assert api.requests[-1].url.params["view"] == "skipped"
    rec = Recorder(httpx.Response(200, json={"metered": False, "estimated_credits": 0, "egress_ready": True}))
    assert cli_main(["assets-quote", PAGE, "--class", "documents"], client=make_client(rec)) == 0
    assert rec.requests[0].url.path == "/v1/assets/quote" and "Idempotency-Key" not in rec.requests[0].headers
    egress = httpx.Response(400, json={"error": {"code": "egress_required", "message": "add a proxy"}})
    assert cli_main(["assets", PAGE], client=make_client(Recorder(egress), max_retries=0)) == 5
    capsys.readouterr()
    with pytest.raises(SystemExit) as usage:
        cli_main(["assets", PAGE, "--class", "archives"])
    assert usage.value.code == 2


def test_cli_assets_out_writes_verified_files_and_pages_every_asset(tmp_path, capsys) -> None:
    one, two = b"\x89PNG one", b"GIF89a two"
    api = AssetAPI(asset_result("completed", assets=[asset_item("a" * 32, one)], partial=True, next_cursor="c1"),
                   asset_result("completed", assets=[asset_item("b" * 32, two, filename="anim.gif")]),
                   files={"a" * 32: one, "b" * 32: two})
    out = tmp_path / "out"
    assert cli_main(["assets", PAGE, "--out", str(out)], client=make_client(api)) == 0
    assert (out / "images" / f"{'a' * 12}-photo.png").read_bytes() == one
    assert (out / "images" / f"{'b' * 12}-anim.gif").read_bytes() == two
    printed = json.loads(capsys.readouterr().out)
    assert [a["asset_id"] for a in printed["assets"]] == ["a" * 32, "b" * 32] and printed["next_cursor"] is None


def test_cli_assets_result_out_downloads_a_finished_job_later(tmp_path, capsys) -> None:
    data = b"\x89PNG later"
    api = AssetAPI(asset_result("completed", assets=[asset_item("c" * 32, data)]), files={"c" * 32: data})
    assert cli_main(["assets-result", "aj1", "--out", str(tmp_path)], client=make_client(api)) == 0
    assert (tmp_path / "images" / f"{'c' * 12}-photo.png").read_bytes() == data
    assert cli_main(["assets-result", "aj1", "--view", "skipped", "--out", str(tmp_path)],
                    client=make_client(AssetAPI(asset_result("completed")))) == 2


def test_cli_assets_hash_mismatch_writes_nothing_and_exits_1(tmp_path, capsys) -> None:
    api = AssetAPI(asset_result("completed", assets=[asset_item("a" * 32, b"expected", sha256="0" * 64)]),
                   files={"a" * 32: b"tampered"})
    out = tmp_path / "out"
    assert cli_main(["assets", PAGE, "--out", str(out)], client=make_client(api)) == 1
    assert "sha256" in capsys.readouterr().err
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]
    api = AssetAPI(asset_result("completed", assets=[asset_item("a" * 32, b"x")]), files={"a" * 32: b"x"})
    api.results[0]["assets"][0]["sha256"] = None                       # unverifiable is not written either
    assert cli_main(["assets", PAGE, "--out", str(out)], client=make_client(api)) == 1
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]


def test_cli_assets_never_overwrites_an_existing_file(tmp_path) -> None:
    data = b"\x89PNG new"
    api = AssetAPI(asset_result("completed", assets=[asset_item("a" * 32, data)]), files={"a" * 32: data})
    existing = tmp_path / "images" / f"{'a' * 12}-photo.png"
    existing.parent.mkdir()
    existing.write_bytes(b"mine")
    assert cli_main(["assets", PAGE, "--out", str(tmp_path)], client=make_client(api)) == 2
    assert existing.read_bytes() == b"mine"


def test_cli_asset_names_stay_inside_the_out_directory(tmp_path) -> None:
    hostile = {"c" * 32: ("../../escape.sh", "images"), "d" * 32: ("/etc/passwd", "documents"),
               "e" * 32: ("..\\..\\win.bat", "data"), "f" * 32: ("a\x1b]8;;x\x07\n.txt", "../../web_assets"),
               "0" * 32: ("..", "audio"), "1" * 32: (None, "video"), "../../../../x": ("ok.png", "images")}
    items, files = [], {}
    for asset_id, (name, cls) in hostile.items():
        data = asset_id.encode()
        items.append(asset_item(asset_id, data, filename=name, asset_class=cls))
        files[asset_id.rsplit("/", 1)[-1]] = data
    api = AssetAPI(asset_result("completed", assets=items), files=files)
    out = tmp_path / "out"
    assert cli_main(["assets", PAGE, "--out", str(out)], client=make_client(api)) == 0
    written = sorted(p for p in tmp_path.rglob("*") if p.is_file())
    assert len(written) == len(hostile)
    for path in written:
        assert path.parent.parent == out                               # DIR/<class>/<name>, nothing deeper or outside
        assert path.parent.name in {"images", "video", "audio", "documents", "data", "web_assets", "other"}
        assert re.fullmatch(r"[A-Za-z0-9._-]{1,140}", path.name), path.name
        assert not path.name.startswith(".")


def test_cli_asset_files_never_follow_a_symlink_out_of_the_directory(tmp_path) -> None:
    data = b"\x89PNG"
    api = AssetAPI(asset_result("completed", assets=[asset_item("a" * 32, data)]), files={"a" * 32: data})
    out, elsewhere = tmp_path / "out", tmp_path / "elsewhere"
    out.mkdir()
    elsewhere.mkdir()
    (out / "images").symlink_to(elsewhere, target_is_directory=True)
    assert cli_main(["assets", PAGE, "--out", str(out)], client=make_client(api)) == 2
    assert list(elsewhere.iterdir()) == [] and api.downloads() == []


def test_cli_assets_an_interrupted_write_leaves_no_partial_file(tmp_path, monkeypatch) -> None:
    """A write that dies mid-file (disk full, kill) must not occupy the final name: a retry then succeeds."""
    import builtins

    data = b"\x89PNG whole"
    api = AssetAPI(asset_result("completed", assets=[asset_item("a" * 32, data)]), files={"a" * 32: data})
    real_open = builtins.open

    class _Full:
        def __init__(self, handle) -> None:  # type: ignore[no-untyped-def]
            self.handle = handle

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *exc) -> None:  # type: ignore[no-untyped-def]
            self.handle.close()

        def write(self, chunk) -> int:  # type: ignore[no-untyped-def]
            self.handle.write(chunk[:3])
            raise OSError(28, "No space left on device")

    def full_disk(path, mode="r", *args, **kwargs):  # type: ignore[no-untyped-def]
        handle = real_open(path, mode, *args, **kwargs)
        return _Full(handle) if "b" in mode and ("x" in mode or "w" in mode) else handle

    monkeypatch.setattr(builtins, "open", full_disk)
    assert cli_main(["assets", PAGE, "--out", str(tmp_path)], client=make_client(api)) == 2
    monkeypatch.setattr(builtins, "open", real_open)
    assert not [p for p in tmp_path.rglob("*") if p.is_file()], "no truncated or temporary file is left behind"
    api = AssetAPI(asset_result("completed", assets=[asset_item("a" * 32, data)]), files={"a" * 32: data})
    assert cli_main(["assets", PAGE, "--out", str(tmp_path)], client=make_client(api)) == 0
    assert (tmp_path / "images" / f"{'a' * 12}-photo.png").read_bytes() == data


def test_cli_assets_without_hard_links_still_never_overwrite(tmp_path, monkeypatch) -> None:
    """On a filesystem without hard links (exFAT, some network mounts) the write claims the name first."""
    import os

    def no_links(_src, _dst):  # type: ignore[no-untyped-def]
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr(os, "link", no_links)
    data = b"\x89PNG whole"
    api = AssetAPI(asset_result("completed", assets=[asset_item("a" * 32, data)]), files={"a" * 32: data})
    assert cli_main(["assets", PAGE, "--out", str(tmp_path / "fresh")], client=make_client(api)) == 0
    assert (tmp_path / "fresh" / "images" / f"{'a' * 12}-photo.png").read_bytes() == data
    existing = tmp_path / "taken" / "images" / f"{'a' * 12}-photo.png"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b"mine")
    api = AssetAPI(asset_result("completed", assets=[asset_item("a" * 32, data)]), files={"a" * 32: data})
    assert cli_main(["assets", PAGE, "--out", str(tmp_path / "taken")], client=make_client(api)) == 2
    assert existing.read_bytes() == b"mine"
    assert sorted(p.name for p in existing.parent.iterdir()) == [existing.name], "no temporary file is left"


# -- secrets and terminal safety ----------------------------------------------------------------------

LEAK = "sk-leaked-9876543210"


@pytest.mark.parametrize("argv", [
    ["ai", "providers", "set", "main", "--provider", "x", f"--key={LEAK}"],           # ambiguous abbreviation
    ["ai", "providers", "set", "main", "--provider", "x", f"--k={LEAK}"],
    ["ai", "providers", "set", "main", "--provider", "x", f"--key=a {LEAK}"],
    ["ai", "providers", "set", "main", "--provider", "x", f"--key-stdin={LEAK}"],     # a flag given a value
    [f"--json={LEAK}", "jobs"],
    ["ai", "providers", LEAK],                                                       # an invalid choice
    [LEAK],
    ["scrape", "https://e.example/", "--format", LEAK],
    ["jobs", "--limit", LEAK],                                                       # an invalid int
    ["jobs", "--limit", f"'{LEAK}\""],
])
def test_no_usage_error_echoes_an_argument(argv: list[str], capsys) -> None:
    with pytest.raises(SystemExit) as usage:
        cli_main(argv, client=make_client(Recorder()))
    assert usage.value.code == 2
    err = capsys.readouterr().err
    assert LEAK not in err and "error:" in err


def test_a_malformed_api_key_exits_3_without_showing_it(monkeypatch, capsys, fake_api) -> None:
    base_url, _ = fake_api
    monkeypatch.setenv("SCRAWL_BASE_URL", base_url)
    monkeypatch.setenv("SCRAWL_API_KEY", f"sk-\n{LEAK}")
    assert cli_main(["jobs"]) == 3
    assert LEAK not in capsys.readouterr().err
    assert cli_main(["doctor"]) == 3
    out = capsys.readouterr()
    assert re.search(r"^fail\s+auth\b", out.out, re.M) and LEAK not in out.out + out.err


def test_json_output_escapes_c1_controls_and_error_lines_are_stripped(capsys) -> None:
    hostile = "ok\x9b31mred\x7f \x1b[2J done é"
    rec = Recorder(httpx.Response(200, json={"job_id": "j", "status": "completed", "url": "u", "markdown": hostile}))
    assert cli_main(["result", "j"], client=make_client(rec)) == 0
    out = capsys.readouterr().out
    assert not re.search(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", out), repr(out)
    assert json.loads(out)["markdown"] == hostile and "é" in out                # still the same JSON
    rec = Recorder(httpx.Response(422, json={"detail": "bad \x1b]52;c;cHduZWQ=\x07 input \x9b2J"}))
    assert cli_main(["jobs"], client=make_client(rec, max_retries=0)) == 5
    err = capsys.readouterr().err
    assert not re.search(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", err.rstrip("\n")), repr(err)
