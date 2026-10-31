"""Scrawl Python SDK: requests, retries, idempotency, waits, pagination, base URL safety (mock transport)."""

from __future__ import annotations

import json

import httpx
import pytest
from conftest import Recorder, body, make_async_client, make_client

from scrawl import (
    AsyncScrawl,
    ConfigurationError,
    RateLimitError,
    Scrawl,
    ScrawlError,
    ServerError,
    ValidationError,
)

PAGE = "https://e.example/page"


def test_scrape_sends_auth_body_and_an_idempotency_key() -> None:
    rec = Recorder(httpx.Response(200, json={"job_id": "j1", "status": "completed", "url": "https://e.example/",
                                             "markdown": "# Hi"}))
    page = make_client(rec).scrape("https://e.example/", formats=["markdown", "json"], instruction="title")
    request = rec.requests[0]
    assert request.method == "POST" and request.url.path == "/v1/scrape"
    assert request.headers["Authorization"] == "Bearer sk-test" and request.headers["Idempotency-Key"]
    assert request.headers["User-Agent"].startswith("scrawl-python/")
    assert body(request) == {"url": "https://e.example/", "formats": ["markdown", "json"], "instruction": "title",
                             "wait_seconds": 30}
    assert page.markdown == "# Hi" and page["status"] == "completed"
    with pytest.raises(AttributeError):
        page.markdwn                                            # typos are not silently None


def test_pending_is_a_result_not_an_error_and_wait_for_scrape_uses_server_waits() -> None:
    rec = Recorder(httpx.Response(202, json={"job_id": "j2", "status": "pending", "url": "u"}),
                   httpx.Response(202, json={"job_id": "j2", "status": "pending", "url": "u"}),
                   httpx.Response(200, json={"job_id": "j2", "status": "completed", "url": "u", "markdown": "x"}))
    c = make_client(rec)
    assert c.scrape("https://e.example/").status == "pending"
    done = c.wait_for_scrape("j2", timeout=120)
    assert done.markdown == "x"
    assert rec.requests[1].url.path == "/v1/scrape/j2/content" and rec.requests[1].url.params["wait_seconds"] == "60"


def test_errors_carry_the_api_code_request_id_and_retry_after() -> None:
    envelope = {"error": {"code": "too_many_active_jobs", "message": "Too many active jobs"}}
    rec = Recorder(httpx.Response(429, json=envelope, headers={"Retry-After": "5", "X-Request-ID": "rq1"}))
    with pytest.raises(RateLimitError) as caught:
        make_client(rec, max_retries=0).get_job("j")
    assert caught.value.code == "too_many_active_jobs" and caught.value.retry_after == 5.0
    assert caught.value.request_id == "rq1" and "too_many_active_jobs" in str(caught.value)


def test_retries_idempotent_submits_and_gets_but_never_a_plain_post_or_a_4xx(monkeypatch) -> None:
    monkeypatch.setattr("scrawl._client.time.sleep", lambda s: None)
    rec = Recorder(httpx.Response(503), httpx.Response(200, json={"job_id": "j", "status": "completed", "url": "u"}))
    c = make_client(rec)
    c.scrape("https://e.example/")
    assert len(rec.requests) == 2
    assert rec.requests[0].headers["Idempotency-Key"] == rec.requests[1].headers["Idempotency-Key"]  # same work
    rec2 = Recorder(httpx.Response(503), httpx.Response(200, json={}))
    with pytest.raises(ServerError):
        make_client(rec2).extract("j", instruction="x")         # a POST without a key is not retried
    assert len(rec2.requests) == 1
    rec3 = Recorder(httpx.Response(422, json={"detail": "bad"}))
    with pytest.raises(ValidationError):
        make_client(rec3).scrape("https://e.example/")
    assert len(rec3.requests) == 1


def test_network_errors_retry_then_raise(monkeypatch) -> None:
    monkeypatch.setattr("scrawl._client.time.sleep", lambda s: None)
    calls = []

    def boom(request):
        calls.append(request)
        raise httpx.ConnectError("refused")

    c = Scrawl("k", base_url="https://x.test", http_client=httpx.Client(transport=httpx.MockTransport(boom)),
               max_retries=2)
    with pytest.raises(ScrawlError, match="Connection failed"):
        c.get_job("j")
    assert len(calls) == 3


def test_paths_and_queries_for_the_rest_of_the_surface() -> None:
    rec = Recorder()
    c = make_client(rec)
    c.map("https://e.example/", limit=5)
    c.batch_scrape(["https://a.example/", "https://b.example/"])
    c.batch_status("b123", wait_seconds=10)
    c.crawl("lab", max_items=10)
    c.list_jobs(limit=5, status="RUNNING")
    c.cancel_job("j/../x")
    c.diff_versions("d1", "v1", "v2", limit=3)
    c.query_dataset("d1", [{"field": "price", "op": "lt", "value": 10}], limit=2)
    c.quarantine_record("d1", "r1", reason="spam")
    c.release_record("d1", "r1")
    c.search("lamp", limit=3)
    seen = [(r.method, r.url.path, dict(r.url.params)) for r in rec.requests]
    assert seen[0][:2] == ("POST", "/v1/map") and seen[1][:2] == ("POST", "/v1/scrape/batch")
    assert seen[2] == ("GET", "/v1/scrape/batch/b123", {"wait_seconds": "10"})
    assert seen[4] == ("GET", "/v1/jobs", {"limit": "5", "status": "RUNNING"})
    assert rec.requests[5].url.raw_path == b"/v1/jobs/j%2F..%2Fx/cancel"   # path segments are escaped
    assert seen[6] == ("GET", "/v1/datasets/d1/diff", {"from": "v1", "to": "v2", "limit": "3"})
    assert (seen[8][0], seen[9][0]) == ("PUT", "DELETE") and seen[10][:2] == ("POST", "/v1/search")
    assert all("Idempotency-Key" in rec.requests[i].headers for i in (0, 1, 3))


def test_paginate_follows_cursors() -> None:
    rec = Recorder(httpx.Response(200, json={"datasets": [{"dataset_id": "a"}], "next_cursor": "c1"}),
                   httpx.Response(200, json={"datasets": [{"dataset_id": "b"}], "next_cursor": None}))
    c = make_client(rec)
    assert [d.dataset_id for d in c.paginate(c.list_datasets, limit=1)] == ["a", "b"]
    assert rec.requests[1].url.params["cursor"] == "c1"


def test_missing_api_key_is_a_configuration_error_but_health_needs_none(monkeypatch) -> None:
    monkeypatch.delenv("SCRAWL_API_KEY", raising=False)
    rec = Recorder(httpx.Response(200, json={"status": "ok"}))
    c = Scrawl(base_url="https://x.test", http_client=httpx.Client(transport=httpx.MockTransport(rec)))
    assert c.health().status == "ok" and "Authorization" not in rec.requests[0].headers
    with pytest.raises(ConfigurationError, match="SCRAWL_API_KEY"):
        c.list_jobs()
    assert len(rec.requests) == 1                                # nothing was sent without a key


def test_api_fields_win_over_dict_methods() -> None:
    from scrawl import ScrawlObject
    from scrawl._objects import wrap

    batch = wrap({"items": [{"url": "u"}], "keys": 3})
    assert batch.items == [{"url": "u"}] and batch.keys == 3 and dict.items(batch)
    assert isinstance(batch, ScrawlObject)


def test_to_dict_gives_plain_json_serialisable_data() -> None:
    """``json.dumps`` calls ``.items()``: on a batch that is the ``items`` field, so serialise ``to_dict()``."""
    from scrawl._objects import wrap

    batch = wrap({"batch_id": "b1", "items": [{"url": "u", "result": {"items": [1]}}]})
    plain = batch.to_dict()
    assert type(plain) is dict and type(plain["items"][0]) is dict and type(plain["items"][0]["result"]) is dict
    assert json.loads(json.dumps(plain)) == {"batch_id": "b1", "items": [{"url": "u", "result": {"items": [1]}}]}


def test_results_with_an_items_field_copy_deepcopy_and_pickle() -> None:
    """The default reduction calls ``obj.items()``, the field on a batch: copies and pickles must not."""
    import copy
    import pickle

    from scrawl import ScrawlObject
    from scrawl._objects import wrap

    batch = wrap({"batch_id": "b1", "status": "completed", "items": [{"url": "u", "result": {"items": [1]}}]})
    for clone in (copy.copy(batch), copy.deepcopy(batch), pickle.loads(pickle.dumps(batch))):
        assert type(clone) is ScrawlObject and clone == batch and clone.items[0].result.items == [1]
        assert isinstance(clone["items"][0], ScrawlObject)
    deep = copy.deepcopy(batch)
    deep["items"][0]["url"] = "changed"
    assert batch["items"][0]["url"] == "u"                        # a deep copy shares nothing
    shallow = copy.copy(batch)
    assert shallow["items"] is batch["items"]                    # a shallow copy shares the values


async def test_async_client_mirrors_the_sync_one() -> None:
    rec = Recorder(httpx.Response(200, json={"job_id": "j", "status": "completed", "url": "u", "markdown": "m"}))
    async with make_async_client(rec) as c:
        page = await c.scrape("https://e.example/")
    assert page.markdown == "m" and rec.requests[0].headers["Idempotency-Key"]


def test_ids_that_would_walk_to_another_route_are_refused_before_any_request() -> None:
    seen: list[str] = []
    client = Scrawl("k", base_url="https://api.test", http_client=httpx.Client(
        transport=httpx.MockTransport(lambda request: seen.append(request.url.path) or httpx.Response(200, json={}))))
    for bad in ("..", ".", ""):
        with pytest.raises(ScrawlError, match="Invalid path segment"):
            client.get_job(bad)
        with pytest.raises(ScrawlError, match="Invalid path segment"):
            client.download_artifact("j1", bad)
    assert seen == []


def _scripted(replies: list, monkeypatch) -> tuple[Scrawl, list[httpx.Request], list[float]]:
    """A client whose transport answers from REPLIES in order; sleeps are recorded, not slept."""
    sent: list[httpx.Request] = []
    slept: list[float] = []
    monkeypatch.setattr("scrawl._client.time.sleep", slept.append)

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        reply = replies.pop(0) if len(replies) > 1 else replies[0]
        if isinstance(reply, Exception):
            raise reply
        return reply

    client = Scrawl("k", base_url="https://api.test", http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return client, sent, slept


DONE = httpx.Response(200, json={"job_id": "j1", "status": "completed", "url": "https://e.example"})


def test_a_keyed_retry_that_meets_its_running_first_attempt_waits_for_the_replay(monkeypatch) -> None:
    conflict = httpx.Response(409, json={"error": {"code": "conflict", "message": "still in progress"}})
    client, sent, slept = _scripted([httpx.ConnectError("reset"), conflict, conflict, DONE], monkeypatch)
    assert client.scrape("https://e.example", wait_seconds=10).status == "completed"
    assert len(sent) == 4 and len({r.headers["Idempotency-Key"] for r in sent}) == 1
    assert all(seconds >= 1.0 for seconds in slept[1:])


def test_scrawls_own_5xx_on_a_keyed_submit_is_final_but_a_proxys_is_retried(monkeypatch) -> None:
    ai_down = httpx.Response(502, json={"error": {"code": "ai_provider_error", "message": "provider timed out"}})
    client, sent, _ = _scripted([ai_down, DONE], monkeypatch)
    with pytest.raises(ServerError) as caught:
        client.scrape("https://e.example", formats=["json"])
    assert caught.value.code == "ai_provider_error" and len(sent) == 1

    client, sent, _ = _scripted([httpx.Response(502, text="<html>Bad Gateway</html>"), DONE], monkeypatch)
    assert client.scrape("https://e.example").status == "completed" and len(sent) == 2

    unavailable = httpx.Response(503, json={"error": {"code": "unavailable", "message": "x"}})
    client, sent, _ = _scripted([unavailable, DONE], monkeypatch)
    client.get_job("j1")
    assert len(sent) == 2


@pytest.mark.parametrize("status", [409, 429, 500, 502, 503, 504])
@pytest.mark.parametrize("code", ["submission_failed", "settlement_failed"])
def test_a_code_the_catalogue_marks_not_retryable_is_never_retried(code: str, status: int, monkeypatch) -> None:
    """A resend after submission_failed or settlement_failed may charge twice: whatever the status, never resend."""
    for shape in ({"error": {"code": code, "message": "list your jobs first"}}, {"detail": "x", "code": code}):
        for call in (lambda c: c.get_job("j1"), lambda c: c.scrape("https://e.example")):
            client, sent, slept = _scripted([httpx.Response(status, json=shape), DONE], monkeypatch)
            with pytest.raises(ScrawlError) as caught:
                call(client)
            assert caught.value.code == code and len(sent) == 1 and slept == []


def test_gets_retry_a_5xx_only_when_its_code_is_retryable_or_unknown(monkeypatch) -> None:
    for code, status, attempts in (("ai_auth", 502, 1), ("browser_unavailable", 503, 1), ("ai_timeout", 502, 2),
                                   ("unavailable", 503, 2), ("a_code_added_later", 503, 2)):
        client, sent, _ = _scripted([httpx.Response(status, json={"error": {"code": code, "message": "x"}}), DONE],
                                    monkeypatch)
        if attempts == 1:
            with pytest.raises(ServerError):
                client.get_job("j1")
        else:
            assert client.get_job("j1").status == "completed"
        assert len(sent) == attempts, code


async def test_the_async_client_never_retries_a_non_retryable_code_either(monkeypatch) -> None:
    async def no_sleep(seconds: float) -> None:
        raise AssertionError("no retry was expected")

    monkeypatch.setattr("scrawl._client.asyncio.sleep", no_sleep)
    for status in (429, 503):
        rec = Recorder(httpx.Response(status, json={"error": {"code": "submission_failed", "message": "x"}}))
        async with make_async_client(rec) as client:
            with pytest.raises(ScrawlError) as caught:
                await client.scrape("https://e.example")
        assert caught.value.code == "submission_failed" and len(rec.requests) == 1


def test_server_side_waits_finish_inside_the_request_timeout(monkeypatch) -> None:
    client, sent, _ = _scripted([DONE], monkeypatch)
    client._t.timeout = 20.0
    client.scrape("https://e.example")                                   # default wait_seconds=30
    client.get_job("j1", wait_seconds=60)
    assert json.loads(sent[0].content)["wait_seconds"] == 15
    assert sent[1].url.params["wait_seconds"] == "15"


def test_the_api_key_is_never_sent_over_plain_http_to_a_remote_host(monkeypatch) -> None:
    monkeypatch.delenv("SCRAWL_ALLOW_INSECURE_HTTP", raising=False)
    for url in ("http://scrawl-lan.test:8088", "http://192.0.2.5", "http://scrawl.example"):
        with pytest.raises(ConfigurationError, match="plain HTTP"):
            Scrawl("k", base_url=url)
    for url in ("http://127.0.0.1:8088", "http://localhost:8088", "http://[::1]:8088", "http://api.localhost",
                "https://scrawl.example"):
        Scrawl("k", base_url=url).close()
    Scrawl("k", base_url="http://scrawl-lan.test", allow_insecure_http=True).close()
    with pytest.raises(ConfigurationError, match="http"):
        Scrawl("k", base_url="ftp://scrawl.example")
    monkeypatch.setenv("SCRAWL_ALLOW_INSECURE_HTTP", "1")
    Scrawl("k", base_url="http://scrawl-lan.test").close()


def test_without_a_base_url_the_client_talks_to_this_machine_only(monkeypatch) -> None:
    """No hard-coded remote host: the default is loopback, anything else must be configured."""
    monkeypatch.delenv("SCRAWL_BASE_URL", raising=False)
    client = Scrawl("k")
    assert client.base_url == "http://127.0.0.1:8088"
    client.close()
    monkeypatch.setenv("SCRAWL_BASE_URL", "https://scrawl.example/")
    client = Scrawl("k")
    assert client.base_url == "https://scrawl.example"
    client.close()


def test_wait_for_job_follows_a_job_until_it_leaves_pending_or_running() -> None:
    def job(status: str) -> httpx.Response:
        return httpx.Response(200, json={"job_id": "c1", "command": "crawl", "args": [], "status": status,
                                         "engine_id": "e", "artifacts_url": "", "result_url": ""})

    rec = Recorder(job("PENDING"), job("RUNNING"), job("COMPLETED"))
    done = make_client(rec).wait_for_job("c1")
    assert done.status == "COMPLETED" and len(rec.requests) == 3
    assert all(r.url.path == "/v1/jobs/c1" and r.url.params["wait_seconds"] == "60" for r in rec.requests)
    for status in ("FAILED", "CANCELLED", "ORPHANED"):
        rec = Recorder(job(status))
        assert make_client(rec).wait_for_job("c1").status == status and len(rec.requests) == 1
    rec = Recorder(job("RUNNING"))
    assert make_client(rec).wait_for_job("c1", timeout=0).status == "RUNNING" and len(rec.requests) == 1


async def test_async_wait_for_job_mirrors_the_sync_one() -> None:
    rec = Recorder(httpx.Response(200, json={"job_id": "c1", "status": "RUNNING"}),
                   httpx.Response(200, json={"job_id": "c1", "status": "COMPLETED"}))
    async with make_async_client(rec) as c:
        assert (await c.wait_for_job("c1")).status == "COMPLETED"
    assert len(rec.requests) == 2


# -- assets --------------------------------------------------------------------------------------

ASSET_JOB = {"job_id": "aj1", "status": "pending", "url": PAGE, "classes": ["images"], "estimated_credits": 3,
             "reserved_credits": None, "max_credits": None, "metered": False,
             "links": {"job": "/v1/jobs/aj1", "assets": "/v1/assets/aj1"}}


def test_asset_requests_have_their_shapes_and_only_extract_is_keyed() -> None:
    rec = Recorder()
    c = make_client(rec)
    c.quote_assets(PAGE, classes=["documents"], max_items=10, max_bytes=1_000_000, max_credits=50)
    c.extract_assets(PAGE, classes=["images", "video"], max_items=10, max_bytes=1_000_000, max_credits=50,
                     idempotency_key="key-6")
    c.extract_assets(PAGE)
    c.get_assets("aj1", view="skipped", limit=50, cursor="c", wait_seconds=5)
    c.get_assets("aj1")
    data = c.download_asset("aj1", "0123456789abcdef01234567")
    seen = [(r.method, r.url.path, dict(r.url.params)) for r in rec.requests]
    assert seen[0] == ("POST", "/v1/assets/quote", {}) and seen[1][:2] == seen[2][:2] == ("POST", "/v1/assets")
    assert body(rec.requests[0]) == {"url": PAGE, "classes": ["documents"], "max_items": 10, "max_bytes": 1_000_000,
                                     "max_credits": 50}
    assert body(rec.requests[1]) == {"url": PAGE, "classes": ["images", "video"], "max_items": 10,
                                     "max_bytes": 1_000_000, "max_credits": 50}
    assert body(rec.requests[2]) == {"url": PAGE}                       # server defaults: all classes, 100, 50 MiB
    assert seen[3] == ("GET", "/v1/assets/aj1", {"view": "skipped", "limit": "50", "cursor": "c", "wait_seconds": "5"})
    assert seen[4] == ("GET", "/v1/assets/aj1", {})
    assert seen[5] == ("GET", "/v1/assets/aj1/files/0123456789abcdef01234567", {}) and data == b"{}"   # raw bytes
    assert rec.requests[1].headers["Idempotency-Key"] == "key-6" and rec.requests[2].headers["Idempotency-Key"]
    assert not any("Idempotency-Key" in rec.requests[i].headers for i in (0, 3, 4, 5))
    with pytest.raises(ScrawlError, match="Invalid path segment"):
        c.download_asset("aj1", "..")
    assert len(rec.requests) == 6


def test_an_asset_quote_is_never_retried_but_an_extract_retries_with_its_key(monkeypatch) -> None:
    monkeypatch.setattr("scrawl._client.time.sleep", lambda s: None)
    rec = Recorder(httpx.Response(503), httpx.Response(200, json={}))
    with pytest.raises(ServerError):
        make_client(rec).quote_assets(PAGE)
    assert len(rec.requests) == 1
    rec = Recorder(httpx.Response(503), httpx.Response(202, json=ASSET_JOB))
    assert make_client(rec).extract_assets(PAGE).job_id == "aj1"
    assert len(rec.requests) == 2
    assert rec.requests[0].headers["Idempotency-Key"] == rec.requests[1].headers["Idempotency-Key"]   # same work


def _asset_result(status: str, **extra) -> dict:
    return {"job_id": "aj1", "status": status, "url": PAGE, "view": "assets", "assets": [], "skipped": None,
            "next_cursor": None, **extra}


def test_wait_for_assets_uses_server_waits_until_the_job_settles() -> None:
    rec = Recorder(*(httpx.Response(200, json=_asset_result(s)) for s in ("pending", "running", "completed")))
    done = make_client(rec).wait_for_assets("aj1")
    assert done.status == "completed" and len(rec.requests) == 3
    assert all(r.url.path == "/v1/assets/aj1" and r.url.params["wait_seconds"] == "60" for r in rec.requests)
    for status in ("failed", "cancelled", "orphaned"):
        rec = Recorder(httpx.Response(200, json=_asset_result(status)))
        assert make_client(rec).wait_for_assets("aj1").status == status and len(rec.requests) == 1
    rec = Recorder(httpx.Response(200, json=_asset_result("running")))
    assert make_client(rec).wait_for_assets("aj1", timeout=0).status == "running" and len(rec.requests) == 1


async def test_async_wait_for_assets_and_download_mirror_the_sync_ones() -> None:
    rec = Recorder(httpx.Response(200, json=_asset_result("pending")), httpx.Response(200, json=_asset_result("completed")),
                   httpx.Response(200, content=b"\x89PNG"))
    async with AsyncScrawl("k", base_url="https://x.test",
                           http_client=httpx.AsyncClient(transport=httpx.MockTransport(rec))) as c:
        done = await c.wait_for_assets("aj1")
        data = await c.download_asset("aj1", "a" * 32)
    assert done.status == "completed" and data == b"\x89PNG"
    assert [r.url.params.get("wait_seconds") for r in rec.requests[:2]] == ["60", "60"]


def test_paginate_iterates_the_requested_asset_view() -> None:
    skipped = {"url": f"{PAGE}/a.zip", "reason": "ARCHIVE_DEFERRED", "detail": "", "asset_class": None,
               "bytes_received": 0}
    rec = Recorder(httpx.Response(200, json=_asset_result("completed", view="skipped", assets=None, skipped=[skipped],
                                                          next_cursor="c1")),
                   httpx.Response(200, json=_asset_result("completed", view="skipped", assets=None,
                                                          skipped=[{**skipped, "url": f"{PAGE}/b.zip"}])))
    c = make_client(rec)
    assert [s.url for s in c.paginate(c.get_assets, "aj1", view="skipped")] == [f"{PAGE}/a.zip", f"{PAGE}/b.zip"]
    assert [dict(r.url.params) for r in rec.requests] == [{"view": "skipped"}, {"view": "skipped", "cursor": "c1"}]


# -- the API key never reaches an error message ----------------------------------------------------------

SECRET = "sk-live-secret-0123456789"


def test_a_key_with_surrounding_whitespace_is_trimmed() -> None:
    """A key read from a file or a CRLF .env keeps its line ending; it is trimmed, not sent (or echoed) as is."""
    for raw in (f"{SECRET}\n", f"{SECRET}\r\n", f"  {SECRET}\t"):
        rec = Recorder(httpx.Response(200, json={"jobs": []}))
        Scrawl(raw, base_url="https://scrawl.test", http_client=httpx.Client(transport=httpx.MockTransport(rec))).list_jobs()
        assert rec.requests[0].headers["Authorization"] == f"Bearer {SECRET}"


@pytest.mark.parametrize("bad", [f"{SECRET[:8]}\n{SECRET[8:]}", f"{SECRET[:8]}\x00{SECRET[8:]}",
                                 f"{SECRET[:8]} {SECRET[8:]}", f"{SECRET[:8]}é{SECRET[8:]}"])
def test_a_key_an_http_header_cannot_carry_is_a_configuration_error_that_never_shows_it(bad: str) -> None:
    rec = Recorder()
    client = Scrawl(bad, base_url="https://scrawl.test", http_client=httpx.Client(transport=httpx.MockTransport(rec)))
    with pytest.raises(ConfigurationError) as caught:
        client.list_jobs()
    assert rec.requests == []
    assert SECRET[8:] not in str(caught.value) and "SCRAWL_API_KEY" in str(caught.value)


def test_a_malformed_key_never_leaks_through_a_real_transport_error(fake_api) -> None:
    """Over a real socket, h11 refuses an illegal header value and quotes it: that text must not reach the user."""
    base_url, _ = fake_api
    with Scrawl(f"{SECRET[:8]}\n{SECRET[8:]}", base_url=base_url, max_retries=0) as client:
        with pytest.raises(ScrawlError) as caught:
            client.list_jobs()
    assert SECRET[8:] not in str(caught.value)


def test_transport_errors_are_scrubbed_of_the_key(monkeypatch) -> None:
    monkeypatch.setattr("scrawl._client.time.sleep", lambda s: None)

    def echoing(request: httpx.Request) -> httpx.Response:
        raise httpx.LocalProtocolError(f"Illegal header value {request.headers['Authorization']!r}")

    client = Scrawl(SECRET, base_url="https://scrawl.test", max_retries=1,
                    http_client=httpx.Client(transport=httpx.MockTransport(echoing)))
    with pytest.raises(ScrawlError) as caught:
        client.get_job("j1")
    assert SECRET not in str(caught.value) and SECRET not in caught.value.message


async def test_the_async_client_scrubs_and_validates_the_key_too() -> None:
    def echoing(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(f"refused {request.headers['Authorization']}")

    async with AsyncScrawl(SECRET, base_url="https://scrawl.test", max_retries=0,
                           http_client=httpx.AsyncClient(transport=httpx.MockTransport(echoing))) as client:
        with pytest.raises(ScrawlError) as caught:
            await client.get_job("j1")
    assert SECRET not in str(caught.value)
    async with AsyncScrawl(f"{SECRET}\x00", base_url="https://scrawl.test",
                           http_client=httpx.AsyncClient(transport=httpx.MockTransport(Recorder()))) as client:
        with pytest.raises(ConfigurationError):
            await client.list_jobs()


def test_a_success_body_that_is_not_json_is_a_scrawl_error() -> None:
    """A proxy or captive portal answering 200 with HTML is an API error, not a JSONDecodeError (CLI exit 5, not 2)."""
    rec = Recorder(httpx.Response(200, text="<html>Sign in to the Wi-Fi</html>", headers={"X-Request-ID": "rq9"}))
    with pytest.raises(ScrawlError, match="not JSON") as caught:
        make_client(rec).list_jobs()
    assert caught.value.status == 200 and caught.value.request_id == "rq9"
