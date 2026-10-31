#!/usr/bin/env python3
"""A small in-memory ApexAPI for tests and examples: canned, contract-shaped answers on loopback.

Every request it receives is checked with ``check_contracts.check_request`` against the vendored contract
and ``coverage.json``, and every JSON answer it gives with ``check_response``; the problems are kept and
served at ``GET /__fake__/problems`` so a test can fail on them. It is not a Scrawl server: nothing is
fetched, nothing is stored on disk, and it only listens on 127.0.0.1.

    python tools/fake_apexapi.py --port 0      # prints "listening http://127.0.0.1:PORT", serves until stopped

Conventions the examples and tests rely on:
  * the API key is ``sk_test_fake`` (any other key gets 401 ``unauthorized``);
  * job, dataset and document ids starting with ``missing`` get 404 ``not_found``;
  * a scrape of a URL containing ``rate-limited`` always gets 429 ``rate_limited`` with ``Retry-After: 0``;
  * a scrape of a URL containing ``flaky`` gets one proxy-style 503 per Idempotency-Key, then succeeds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_contracts import COVERAGE, OPENAPI, check_request, check_response, load_json, split_route  # noqa: E402

API_KEY = "sk_test_fake"
NOW = "2026-10-31T00:00:00Z"
HTML = (b"<!doctype html><html><head><title>Example lamp</title></head><body><h1>Example lamp</h1>"
        b"<p>A desk lamp. Price: 19.50 EUR. SKU: LAMP-1.</p></body></html>")
MARKDOWN = "# Example lamp\n\nA desk lamp. Price: 19.50 EUR. SKU: LAMP-1.\n"
ASSET = b"\x89PNG\r\n\x1a\nexample image bytes"


class Reply:
    def __init__(self, status: int, body: Any = None, *, raw: bytes | None = None,
                 headers: dict[str, str] | None = None) -> None:
        self.status, self.body, self.raw, self.headers = status, body, raw, headers or {}


def _error(status: int, code: str, message: str, headers: dict[str, str] | None = None) -> Reply:
    return Reply(status, {"error": {"code": code, "message": message, "request_id": "req-fake"}}, headers=headers)


def _template(path: str) -> re.Pattern[str]:
    parts = re.split(r"(\{[^}]+\})", path)
    return re.compile("^" + "".join(f"(?P<{p[1:-1]}>[^/]+)" if p.startswith("{") else re.escape(p)
                                    for p in parts) + "$")


class FakeApexAPI:
    """The request handling, independent of HTTP (so it can be driven directly too)."""

    def __init__(self, openapi_path: Path = OPENAPI, coverage_path: Path = COVERAGE) -> None:
        self.openapi = load_json(openapi_path)
        coverage = load_json(coverage_path)
        self.sends = {route: entry["sends"] for route, entry in coverage["operations"].items() if "sends" in entry}
        self.routes = [(split_route(route)[0], _template(split_route(route)[1]), route) for route in self.sends]
        self.problems: list[str] = []
        self.requests: list[dict[str, Any]] = []
        self.profiles: dict[str, dict[str, Any]] = {}
        self.flaky_seen: set[str] = set()
        self.lock = threading.Lock()

    # -- dispatch ----------------------------------------------------------------------------------
    def handle(self, method: str, raw_path: str, headers: dict[str, str], payload: bytes) -> Reply:
        parts = urlsplit(raw_path)
        query = {key: values if len(values) > 1 else values[0]
                 for key, values in parse_qs(parts.query, keep_blank_values=True).items()}
        try:
            body = json.loads(payload) if payload else None
        except ValueError:
            return Reply(422, {"detail": "body is not JSON", "code": "invalid_request"})
        for verb, pattern, route in self.routes:
            match = pattern.match(parts.path)
            if verb == method and match:
                break
        else:
            return Reply(404, {"detail": "Not Found", "code": "not_found"})
        request = {"method": method, "path": parts.path, "query": query, "body": body, "headers": headers}
        with self.lock:
            self.requests.append({"route": route, "request": request})
            self.problems.extend(check_request(self.openapi, route, request, self.sends[route]))
        lowered = {k.lower(): v for k, v in headers.items()}
        if self.sends[route].get("auth", True) and lowered.get("authorization") != f"Bearer {API_KEY}":
            return Reply(401, {"detail": "Invalid or missing API key", "code": "unauthorized"})
        params = {key: unquote(value) for key, value in match.groupdict().items()}
        for name in ("job_id", "dataset_id", "document_id", "batch_id"):
            if params.get(name, "").startswith("missing"):
                return _error(404, "not_found", f"{name} not found")
        reply = getattr(self, "_" + re.sub(r"[^a-z0-9]+", "_", route.lower()).strip("_"))(params, query, body or {},
                                                                                      lowered)
        if reply.raw is None and isinstance(reply.body, dict):
            with self.lock:
                self.problems.extend(check_response(self.openapi, route, reply.status, reply.body))
        return reply

    # -- scrape, map, batch ------------------------------------------------------------------------
    @staticmethod
    def _page(url: str, formats: list[str], engine: str, job_id: str = "job-scrape-1") -> dict[str, Any]:
        page: dict[str, Any] = {"job_id": job_id, "status": "completed", "url": url, "engine": engine,
                                "title": "Example lamp", "content_type": "text/html", "http_status": "200",
                                "elapsed_ms": 12, "truncated": False, "untrusted_external_content": True,
                                "_links": {"content": f"/v1/scrape/{job_id}/content"}}
        if "markdown" in formats:
            page["markdown"] = MARKDOWN
        if "links" in formats:
            page["links"] = [url.rstrip("/") + "/about"]
        if "html" in formats:
            page["html"] = HTML.decode()
        if "json" in formats:
            page["json"] = {"name": "Example lamp", "price": 19.5, "sku": "LAMP-1"}
            page["ai"] = {"provider": "example-ai", "model": "example-model", "input_tokens": 120, "output_tokens": 18}
        if engine == "browser":
            page["final_url"] = url
            page["browser"] = {"settle": "network_quiet", "wait_for_ms": 0, "redirects": 0}
        return page

    def _post_v1_scrape(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        url = body.get("url", "")
        if "rate-limited" in url:
            return _error(429, "rate_limited", "Too many requests", {"Retry-After": "0"})
        if "flaky" in url:
            key = headers.get("idempotency-key", "")
            with self.lock:
                first = key not in self.flaky_seen
                self.flaky_seen.add(key)
            if first:
                return Reply(503, raw=b"<html>503 Service Unavailable (proxy)</html>",
                             headers={"Content-Type": "text/html"})
        return Reply(200, self._page(url, body.get("formats") or ["markdown"], body.get("engine") or "static"))

    def _get_v1_scrape_job_id_content(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        formats = str(query.get("formats") or "markdown").split(",")
        return Reply(200, self._page("https://shop.example/lamp", formats, "static", params["job_id"]))

    def _post_v1_map(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        base = body.get("url", "https://shop.example/").rstrip("/")
        links = [f"{base}/", f"{base}/products/lamp", f"{base}/products/desk", f"{base}/about"]
        return Reply(200, {"url": body.get("url"), "status": "completed", "engine": body.get("engine") or "static",
                           "links": links[: int(body.get("limit") or 100)], "sources": {"page": 3, "sitemap": 1},
                           "job_ids": ["job-map-1"], "truncated": False, "warnings": [], "error": None,
                           "elapsed_ms": 20, "untrusted_external_content": True})

    def _batch(self, urls: list[str], formats: list[str], done: bool) -> dict[str, Any]:
        items = [{"url": url, "status": "completed" if done else "pending", "job_id": f"job-batch-{i}",
                  "result": self._page(url, formats, "static", f"job-batch-{i}") if done else None}
                 for i, url in enumerate(urls)]
        counts = {"completed": len(urls)} if done else {"pending": len(urls)}
        return {"batch_id": "batch-1", "status": "completed" if done else "running", "total": len(urls),
                "counts": counts, "items": items, "untrusted_external_content": True,
                "_links": {"self": "/v1/scrape/batch/batch-1"}}

    def _post_v1_scrape_batch(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        with self.lock:
            self.batch = (list(body.get("urls") or []), body.get("formats") or ["markdown"])
        return Reply(202, self._batch(*self.batch, done=False))

    def _get_v1_scrape_batch_batch_id(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        urls, formats = getattr(self, "batch", (["https://shop.example/lamp"], ["markdown"]))
        return Reply(200, self._batch(urls, formats, done=True))

    # -- AI ------------------------------------------------------------------------------------------
    def _post_v1_extract(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        return Reply(200, {"data": {"name": "Example lamp", "price": 19.5}, "provider": "example-ai",
                           "model": "example-model", "profile": body.get("profile"),
                           "source": {"job_id": body.get("job_id"), "artifact": body.get("artifact")},
                           "usage": {"input_tokens": 100, "output_tokens": 12}, "truncated": False,
                           "repaired": False, "warnings": [], "untrusted_external_content": True})

    def _post_v1_ask(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        citation = {"tag": "1", "document_id": "doc-1", "dataset_id": body.get("dataset_id") or "ds-1",
                    "title": "Example lamp", "url": "https://shop.example/products/lamp"}
        return Reply(200, {"answer": "The Example lamp costs 19.50 EUR [1].", "answerable": True,
                           "citations": [citation], "sources_considered": 3, "provider": "example-ai",
                           "model": "example-model", "usage": {"input_tokens": 300, "output_tokens": 20},
                           "untrusted_external_content": True})

    def _get_v1_ai_providers(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        return Reply(200, {"count": len(self.profiles), "profiles": list(self.profiles.values())})

    def _put_v1_ai_providers_profile(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        name = params["profile"]
        fingerprint = "sha256:" + hashlib.sha256(str(body.get("api_key", "")).encode()).hexdigest()[:16]
        info = {"profile": name, "provider": body.get("provider"), "model": body.get("model") or "example-model",
                "base_url": body.get("base_url") or "https://ai.example/v1", "key_fingerprint": fingerprint,
                "is_default": not self.profiles or self.profiles.get(name, {}).get("is_default", False),
                "created_at": NOW, "updated_at": NOW}
        with self.lock:
            self.profiles[name] = info
        return Reply(200, info)

    def _delete_v1_ai_providers_profile(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        with self.lock:
            removed = self.profiles.pop(params["profile"], None)
        return Reply(204) if removed else _error(404, "not_found", "No such AI profile")

    def _post_v1_ai_providers_profile_default(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        if params["profile"] not in self.profiles:
            return _error(404, "not_found", "No such AI profile")
        with self.lock:
            for name, info in self.profiles.items():
                info["is_default"] = name == params["profile"]
        return Reply(200, self.profiles[params["profile"]])

    def _post_v1_ai_providers_profile_test(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        info = self.profiles.get(params["profile"])
        if info is None:
            return _error(404, "not_found", "No such AI profile")
        return Reply(200, {"profile": info["profile"], "provider": info["provider"], "model": info["model"],
                           "ok": True, "model_listed": True, "latency_ms": 42, "error": None, "error_kind": None})

    def _get_v1_ai_usage(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        return Reply(200, {"days": int(query.get("days", 30)), "totals": [
            {"provider": "example-ai", "model": "example-model", "feature": "scrape_json", "calls": 3, "failed": 0,
             "input_tokens": 360, "output_tokens": 54}]})

    # -- crawls and jobs -------------------------------------------------------------------------------
    def _post_v1_crawls(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        return Reply(202, {"job_id": "job-crawl-1", "status": "PENDING", "crawl_target": body.get("crawl_target"),
                           "dataset_id": "ds-1", "dataset_version_id": "v-2", "dataset_artifact": "items.jsonl",
                           "export_format": body.get("export_format") or "jsonlines",
                           "max_items": body.get("max_items") or 10000, "max_seconds": body.get("max_seconds") or 1800,
                           "links": {"job": "/v1/jobs/job-crawl-1", "dataset": "/v1/datasets/ds-1"}})

    @staticmethod
    def _job(job_id: str, status: str = "COMPLETED") -> dict[str, Any]:
        return {"job_id": job_id, "command": "crawl", "args": ["example-target"], "status": status,
                "engine_id": "default", "artifacts_url": f"/v1/artifacts/{job_id}", "result_url": f"/v1/jobs/{job_id}",
                "source": "apexapi", "exit_code": 0, "started_at": NOW, "finished_at": NOW}

    def _get_v1_jobs_job_id(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        return Reply(200, self._job(params["job_id"]))

    def _get_v1_jobs(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        return Reply(200, {"jobs": [self._job("job-crawl-1")], "next_cursor": None})

    def _post_v1_jobs_job_id_cancel(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        return Reply(200, {"job_id": params["job_id"], "cancelled": True, "status": "CANCELLED", "message": None})

    def _get_v1_artifacts_job_id(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        job_id = params["job_id"]
        return Reply(200, {"job_id": job_id, "artifacts": [
            {"name": "response.html", "type": "html", "size_bytes": len(HTML),
             "download_url": f"/v1/artifacts/{job_id}/response.html"}]})

    def _get_v1_artifacts_job_id_filename(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        if params["filename"] != "response.html":
            return Reply(404, {"detail": "Artifact not found", "code": "not_found"})
        if query.get("format") == "markdown":
            return Reply(200, raw=MARKDOWN.encode(), headers={"Content-Type": "text/markdown; charset=utf-8"})
        return Reply(200, raw=HTML, headers={"Content-Type": "text/html"})

    # -- datasets --------------------------------------------------------------------------------------
    @staticmethod
    def _dataset(dataset_id: str = "ds-1", active: str = "v-2") -> dict[str, Any]:
        return {"dataset_id": dataset_id, "dataset_key": "example-target", "title": "Example shop",
                "crawl_target": "example-target", "active_version_id": active, "created_at": NOW, "updated_at": NOW}

    @staticmethod
    def _version(version_id: str, dataset_id: str = "ds-1") -> dict[str, Any]:
        return {"version_id": version_id, "dataset_id": dataset_id, "job_id": "job-crawl-1",
                "artifact_name": "items.jsonl", "status": "completed", "record_count": 2, "skipped_count": 0,
                "content_hash": "0" * 64, "schema_version": 1, "validation_state": "valid", "index_error": None,
                "is_published": True, "created_at": NOW, "finalized_at": NOW}

    def _get_v1_datasets(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        return Reply(200, {"count": 1, "datasets": [self._dataset()], "next_cursor": None})

    def _get_v1_datasets_dataset_id(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        return Reply(200, {"dataset": self._dataset(params["dataset_id"]),
                           "versions": [self._version("v-2"), self._version("v-1")]})

    def _get_v1_datasets_dataset_id_versions(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        return Reply(200, {"count": 2, "versions": [self._version("v-2"), self._version("v-1")], "next_cursor": None})

    def _post_v1_datasets_dataset_id_active_version(self, params: dict, query: dict, body: dict,
                                                    headers: dict) -> Reply:
        return Reply(200, {"dataset": self._dataset(params["dataset_id"], body.get("version_id", "v-2"))})

    def _get_v1_datasets_dataset_id_diff(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        entry = {"record_id": "rec-2", "change": "changed", "from_content_hash": "1" * 64,
                 "to_content_hash": "2" * 64, "quarantined": False}
        return Reply(200, {"entries": [entry], "totals": {"added": 0, "removed": 0, "changed": 1}, "next_cursor": None})

    def _get_v1_datasets_dataset_id_fields(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        return Reply(200, {"truncated": False, "fields": [
            {"path": "name", "types": ["string"], "present": 2, "examples": ["Example lamp"]},
            {"path": "price", "types": ["number"], "present": 2, "examples": [19.5]}]})

    def _post_v1_datasets_dataset_id_query(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        record = {"record_id": "rec-1", "title": "Example lamp", "text": "A desk lamp.",
                  "url": "https://shop.example/products/lamp", "record": {"name": "Example lamp", "price": 19.5},
                  "provenance": {"version_id": "v-2", "job_id": "job-crawl-1"}}
        return Reply(200, {"records": [record], "scanned": 2, "next_cursor": None})

    def _post_v1_datasets_dataset_id_extract(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        return Reply(202, {"job_id": "job-extract-1", "status": "PENDING", "source_dataset_id": params["dataset_id"],
                           "source_version_id": body.get("version_id") or "v-2", "target_dataset_id": "ds-2",
                           "target_version_id": "v-1", "links": {"job": "/v1/jobs/job-extract-1"}})

    def _put_v1_datasets_dataset_id_records_record_id_quarantine(self, params: dict, query: dict, body: dict,
                                                                 headers: dict) -> Reply:
        return Reply(200, {"dataset_id": params["dataset_id"], "record_id": params["record_id"], "quarantined": True,
                           "reason": body.get("reason")})

    def _delete_v1_datasets_dataset_id_records_record_id_quarantine(self, params: dict, query: dict, body: dict,
                                                                    headers: dict) -> Reply:
        return Reply(200, {"dataset_id": params["dataset_id"], "record_id": params["record_id"], "quarantined": False,
                           "reason": None})

    def _post_v1_search(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        return Reply(200, {"results": [{"id": "doc-1", "title": "Example lamp", "text": "A desk lamp.",
                                        "url": "https://shop.example/products/lamp"}]})

    def _get_v1_documents_document_id(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        return Reply(200, {"id": params["document_id"], "title": "Example lamp", "text": "A desk lamp.",
                           "url": "https://shop.example/products/lamp", "metadata": {"dataset_id": "ds-1"}})

    def _get_v1_credits_balance(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        return Reply(200, {"metered": False, "status": "unmetered"})

    def _get_v1_health(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        return Reply(200, {"service": "ApexAPI", "status": "ok"})

    # -- assets ------------------------------------------------------------------------------------------
    def _post_v1_assets_quote(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        classes = body.get("classes") or ["images", "video", "audio", "documents", "data", "web_assets"]
        return Reply(200, {"metered": False, "metering": "self_hosted_unmetered", "estimated_credits": 0,
                           "breakdown": {}, "job_mode": "standard", "classes": classes,
                           "max_items": body.get("max_items") or 100, "max_bytes": body.get("max_bytes") or 52428800,
                           "wall_clock_seconds": 300, "confirmation_required": False,
                           "max_credits": body.get("max_credits"), "within_budget": None, "credits_available": None,
                           "sufficient_credits": None, "egress_ready": True})

    def _post_v1_assets(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        return Reply(202, {"job_id": "job-assets-1", "status": "pending", "url": body.get("url"),
                           "classes": body.get("classes") or ["images"], "estimated_credits": 0,
                           "reserved_credits": None, "max_credits": body.get("max_credits"), "metered": False,
                           "links": {"job": "/v1/jobs/job-assets-1", "assets": "/v1/assets/job-assets-1"}})

    def _get_v1_assets_job_id(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        job_id, view = params["job_id"], query.get("view", "assets")
        asset = {"asset_id": "a" * 24, "asset_class": "images", "mime_type": "image/png", "size_bytes": len(ASSET),
                 "sha256": hashlib.sha256(ASSET).hexdigest(), "original_url": "https://shop.example/lamp.png",
                 "final_url": None, "filename": "lamp.png", "download_url": f"/v1/assets/{job_id}/files/{'a' * 24}"}
        return Reply(200, {"job_id": job_id, "status": "completed", "url": "https://shop.example/products/lamp",
                           "classes": ["images"], "partial": False, "partial_reason": None, "error_code": None,
                           "failure_reason": None, "counts": {"discovered": 1, "stored": 1, "skipped": 0,
                                                              "duplicates": 0, "skipped_omitted": 0},
                           "total_fetched_bytes": len(ASSET), "total_stored_bytes": len(ASSET),
                           "files_available": True, "billing": {"metered": False, "estimated_credits": None,
                                                                "reserved_credits": None, "charged_credits": None,
                                                                "state": "unmetered"},
                           "view": view, "assets": [asset] if view == "assets" else None,
                           "skipped": [] if view == "skipped" else None, "next_cursor": None,
                           "untrusted_external_content": True, "links": {"self": f"/v1/assets/{job_id}"}})

    def _get_v1_assets_job_id_files_asset_id(self, params: dict, query: dict, body: dict, headers: dict) -> Reply:
        return Reply(200, raw=ASSET, headers={"Content-Type": "application/octet-stream",
                                              "X-Asset-SHA256": hashlib.sha256(ASSET).hexdigest(),
                                              "X-Untrusted-External-Content": "true"})


def make_server(port: int = 0, fake: FakeApexAPI | None = None) -> tuple[ThreadingHTTPServer, FakeApexAPI]:
    """A loopback HTTP server over FAKE (call ``serve_forever`` or run it in a thread)."""
    fake = fake or FakeApexAPI()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:     # quiet
            return

        def _serve(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            payload = self.rfile.read(length) if length else b""
            if self.path == "/__fake__/problems":
                reply = Reply(200, {"problems": fake.problems, "requests": len(fake.requests)})
            else:
                reply = fake.handle(self.command, self.path, dict(self.headers.items()), payload)
            data = reply.raw if reply.raw is not None else (b"" if reply.body is None else json.dumps(reply.body).encode())
            self.send_response(reply.status)
            if reply.raw is None and reply.body is not None:
                self.send_header("Content-Type", "application/json")
            for name, value in reply.headers.items():
                self.send_header(name, value)
            self.send_header("X-Request-ID", "req-fake")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = do_HEAD = _serve

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    return server, fake


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="fake_apexapi", description="Serve a fake ApexAPI on 127.0.0.1.")
    parser.add_argument("--port", type=int, default=0, help="0 picks a free port")
    args = parser.parse_args(argv)
    server, _ = make_server(args.port)
    print(f"listening http://127.0.0.1:{server.server_address[1]}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
