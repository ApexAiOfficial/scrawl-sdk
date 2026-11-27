"""SCCLD1 CC-2: the site crawl and curation methods send what the API reads (mock transport)."""

from __future__ import annotations

import asyncio
import json

import httpx

from scrawl import AsyncScrawl, Scrawl

CRAWL = {"crawl_id": "c1", "status": "RUNNING", "done": False, "pages": [], "counts": {}}


class Recorder:
    def __init__(self, *responses: httpx.Response) -> None:
        self.responses, self.requests = list(responses), []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0) if self.responses else httpx.Response(200, json=CRAWL)


def _client(rec: Recorder) -> Scrawl:
    return Scrawl("sk-test", base_url="https://scrawl.test", max_retries=0,
                  http_client=httpx.Client(transport=httpx.MockTransport(rec)))


def test_crawl_site_sends_only_what_is_set_with_an_idempotency_key() -> None:
    rec = Recorder()
    c = _client(rec)
    started = c.crawl_site("https://e.example/")
    c.crawl_site("https://e.example/", max_pages=10, max_depth=1, engine="browser", wait_for_ms=500,
                 only_main_content=False, include_tags=["main"], exclude_tags=["nav"], resume_from="c0",
                 idempotency_key="k-1")
    first, second = rec.requests
    assert (first.method, first.url.path) == ("POST", "/v1/site-crawls")
    assert json.loads(first.content) == {"url": "https://e.example/"} and first.headers["Idempotency-Key"]
    assert json.loads(second.content) == {"url": "https://e.example/", "max_pages": 10, "max_depth": 1,
                                          "engine": "browser", "wait_for_ms": 500, "only_main_content": False,
                                          "include_tags": ["main"], "exclude_tags": ["nav"], "resume_from": "c0"}
    assert second.headers["Idempotency-Key"] == "k-1"
    assert started.status == "RUNNING"                   # a job status reaches you as the server sent it


def test_site_crawl_status_pages_and_waits() -> None:
    rec = Recorder()
    _client(rec).site_crawl_status("c1", wait_seconds=5, limit=10, cursor="x")
    request = rec.requests[0]
    assert (request.method, request.url.path) == ("GET", "/v1/site-crawls/c1")
    assert dict(request.url.params) == {"wait_seconds": "5", "limit": "10", "cursor": "x"}


def test_wait_for_site_crawl_returns_once_the_version_is_final() -> None:
    rec = Recorder(httpx.Response(200, json=CRAWL), httpx.Response(200, json={**CRAWL, "status": "COMPLETED",
                                                                              "done": True}))
    done = _client(rec).wait_for_site_crawl("c1", timeout=120)
    assert done.done is True and done.status == "COMPLETED" and len(rec.requests) == 2


def test_curation_methods_send_the_operation_and_page_the_list() -> None:
    rec = Recorder(httpx.Response(201, json={"curation_id": "u1"}), httpx.Response(201, json={"curation_id": "u2"}),
                   httpx.Response(200, json={"curations": [], "next_cursor": None}))
    c = _client(rec)
    c.curate_dataset("d1", "remove", record_ids=["r1", "r2"])
    c.curate_dataset("d1", "reextract", version_id="v1", include_tags=["h1"])
    c.list_curations("d1", limit=5, cursor="x")
    remove, reextract, listed = rec.requests
    assert (remove.method, remove.url.path) == ("POST", "/v1/datasets/d1/curate")
    assert json.loads(remove.content) == {"operation": "remove", "record_ids": ["r1", "r2"]}
    assert json.loads(reextract.content) == {"operation": "reextract", "version_id": "v1", "include_tags": ["h1"]}
    assert (listed.method, listed.url.path) == ("GET", "/v1/datasets/d1/curations")
    assert dict(listed.url.params) == {"limit": "5", "cursor": "x"}


def test_the_async_client_sends_the_same_requests() -> None:
    rec = Recorder(httpx.Response(202, json=CRAWL), httpx.Response(200, json=CRAWL),
                   httpx.Response(201, json={"curation_id": "u1"}), httpx.Response(200, json={"curations": []}))

    async def run() -> None:
        async with AsyncScrawl("sk-test", base_url="https://scrawl.test", max_retries=0,
                               http_client=httpx.AsyncClient(transport=httpx.MockTransport(rec))) as c:
            await c.crawl_site("https://e.example/", max_pages=3)
            await c.site_crawl_status("c1")
            await c.curate_dataset("d1", "dedupe", field="title")
            await c.list_curations("d1")

    asyncio.run(run())
    assert [(r.method, r.url.path) for r in rec.requests] == [
        ("POST", "/v1/site-crawls"), ("GET", "/v1/site-crawls/c1"), ("POST", "/v1/datasets/d1/curate"),
        ("GET", "/v1/datasets/d1/curations")]
    assert json.loads(rec.requests[0].content) == {"url": "https://e.example/", "max_pages": 3}
    assert json.loads(rec.requests[2].content) == {"operation": "dedupe", "field": "title"}
