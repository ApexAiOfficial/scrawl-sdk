"""The browser engine option in the Python SDK and CLI, and its downgrade guard (mock transport)."""

from __future__ import annotations

import inspect
import json

import httpx
import pytest
from conftest import OPENAPI, Recorder

from scrawl import AsyncScrawl, ErrorCode, Scrawl, ScrawlError
from scrawl.cli import main as cli_main

PAGE = {"job_id": "j1", "status": "completed", "url": "https://e.example/", "markdown": "# Hi"}


def _client(rec: Recorder) -> Scrawl:
    return Scrawl("sk-test", base_url="https://scrawl.test", max_retries=0,
                  http_client=httpx.Client(transport=httpx.MockTransport(rec)))


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content)


def test_bodies_omit_the_engine_options_unless_they_are_set() -> None:
    rec = Recorder(httpx.Response(200, json={**PAGE, "engine": "static"}),
                   httpx.Response(200, json={"status": "completed", "links": [], "engine": "static"}),
                   httpx.Response(202, json={"batch_id": "b", "status": "running"}),
                   httpx.Response(200, json={**PAGE, "engine": "browser"}),
                   httpx.Response(200, json={"status": "completed", "links": [], "engine": "browser"}),
                   httpx.Response(202, json={"batch_id": "b", "status": "running"}))
    c = _client(rec)
    c.scrape("https://e.example/")
    c.map("https://e.example/")
    c.batch_scrape(["https://e.example/"])
    for request in rec.requests:
        assert "engine" not in _body(request) and "wait_for_ms" not in _body(request)
    c.scrape("https://e.example/", engine="browser", wait_for_ms=750)
    c.map("https://e.example/", engine="browser")
    c.batch_scrape(["https://e.example/"], engine="browser", wait_for_ms=0)
    scrape, map_, batch = (_body(request) for request in rec.requests[3:])
    assert (scrape["engine"], scrape["wait_for_ms"], map_["engine"], batch["engine"], batch["wait_for_ms"]) == \
        ("browser", 750, "browser", "browser", 0)
    assert "wait_for_ms" not in map_


@pytest.mark.parametrize("echo", [{"engine": "static"}, {}])
@pytest.mark.parametrize("status", ["completed", "failed"])
def test_a_downgraded_finished_result_raises_render_not_supported(echo: dict, status: str) -> None:
    for call in (lambda c: c.scrape("https://e.example/", engine="browser"),
                 lambda c: c.map("https://e.example/", engine="browser")):
        c = _client(Recorder(httpx.Response(200, json={**PAGE, "status": status, **echo})))
        with pytest.raises(ScrawlError) as raised:
            call(c)
        assert raised.value.code == ErrorCode.RENDER_NOT_SUPPORTED == "render_not_supported"


def test_the_guard_passes_a_browser_echo_a_pending_result_and_static_requests() -> None:
    rec = Recorder(httpx.Response(200, json={**PAGE, "engine": "browser", "final_url": "https://e.example/x",
                                             "browser": {"settle": "network_quiet"}}),
                   httpx.Response(202, json={"job_id": "j2", "status": "pending"}),
                   httpx.Response(200, json={**PAGE}))
    c = _client(rec)
    page = c.scrape("https://e.example/", engine="browser")
    assert (page.engine, page.final_url, page.browser.settle) == ("browser", "https://e.example/x", "network_quiet")
    assert c.scrape("https://e.example/", engine="browser").status == "pending"   # not finished: no verdict yet
    assert c.scrape("https://e.example/").markdown == "# Hi"                       # static: never checked


async def test_the_async_client_has_the_same_options_and_guard() -> None:
    rec = Recorder(httpx.Response(200, json={**PAGE, "engine": "static"}))
    async with AsyncScrawl("k", base_url="https://x.test", max_retries=0,
                           http_client=httpx.AsyncClient(transport=httpx.MockTransport(rec))) as c:
        with pytest.raises(ScrawlError, match="render_not_supported"):
            await c.scrape("https://e.example/", engine="browser", wait_for_ms=100)
    assert _body(rec.requests[0])["wait_for_ms"] == 100


def test_the_sdk_takes_every_request_field_of_scrape_map_and_batch() -> None:
    schemas = OPENAPI["components"]["schemas"]
    for path, method, positional in (("/v1/scrape", Scrawl.scrape, "url"), ("/v1/map", Scrawl.map, "url"),
                                     ("/v1/scrape/batch", Scrawl.batch_scrape, "urls")):
        ref = OPENAPI["paths"][path]["post"]["requestBody"]["content"]["application/json"]["schema"]["$ref"]
        fields = set(schemas[ref.rsplit("/", 1)[-1]]["properties"]) - {positional}
        assert fields <= set(inspect.signature(method).parameters), (path, fields)
        assert {"engine", "wait_for_ms"} <= fields


def test_the_cli_flags(capsys) -> None:
    rec = Recorder(httpx.Response(200, json={**PAGE, "engine": "browser"}),
                   httpx.Response(200, json={"status": "completed", "links": ["https://e.example/a"], "engine": "browser"}),
                   httpx.Response(202, json={"batch_id": "b", "status": "running"}),
                   httpx.Response(200, json={**PAGE}))
    c = _client(rec)
    assert cli_main(["scrape", "https://e.example/", "--browser", "--wait-for", "500"], client=c) == 0
    assert cli_main(["map", "https://e.example/", "--browser"], client=c) == 0
    assert cli_main(["--json", "batch", "https://e.example/", "--browser", "--wait", "0"], client=c) == 4
    assert cli_main(["scrape", "https://e.example/"], client=c) == 0
    bodies = [_body(request) for request in rec.requests]
    assert (bodies[0]["engine"], bodies[0]["wait_for_ms"], bodies[1]["engine"], bodies[2]["engine"]) == \
        ("browser", 500, "browser", "browser")
    assert "engine" not in bodies[3]


def test_the_guard_covers_the_pending_then_poll_path() -> None:
    pending = httpx.Response(202, json={"job_id": "j1", "status": "pending", "url": "https://e.example/"})
    downgraded = httpx.Response(200, json={**PAGE, "engine": "static"})
    c = _client(Recorder(pending, downgraded))
    assert c.scrape("https://e.example/", engine="browser", wait_seconds=0).status == "pending"
    with pytest.raises(ScrawlError, match="render_not_supported"):
        c.wait_for_scrape("j1", timeout=5, engine="browser")
    c = _client(Recorder(downgraded))
    with pytest.raises(ScrawlError, match="render_not_supported"):
        c.scrape_result("j1", engine="browser")
    assert _client(Recorder(downgraded)).scrape_result("j1").markdown == "# Hi"   # no expectation: no check


def test_the_cli_polls_a_pending_browser_scrape_with_the_guard(capsys) -> None:
    rec = Recorder(httpx.Response(202, json={"job_id": "j1", "status": "pending", "url": "https://e.example/"}),
                   httpx.Response(200, json={**PAGE, "engine": "static"}))
    assert cli_main(["scrape", "https://e.example/", "--browser", "--wait", "90"], client=_client(rec)) == 5
    assert "render_not_supported" in capsys.readouterr().err


def test_a_pending_browser_scrape_tells_you_how_to_keep_the_guard(capsys) -> None:
    rec = Recorder(httpx.Response(202, json={"job_id": "j1", "status": "pending", "url": "https://e.example/"}))
    assert cli_main(["scrape", "https://e.example/", "--browser", "--wait", "5"], client=_client(rec)) == 4
    assert "scrawl result j1 --browser" in capsys.readouterr().err


def test_cli_result_keeps_the_downgrade_guard(capsys) -> None:
    """``scrawl result JOB --browser`` (with or without --wait) refuses a result another engine produced."""
    downgraded = httpx.Response(200, json={**PAGE, "engine": "static"})
    assert cli_main(["result", "j1", "--browser"], client=_client(Recorder(downgraded))) == 5
    assert "render_not_supported" in capsys.readouterr().err
    rec = Recorder(httpx.Response(202, json={"job_id": "j1", "status": "pending", "url": "u"}), downgraded)
    assert cli_main(["result", "j1", "--browser", "--wait", "30"], client=_client(rec)) == 5
    assert "render_not_supported" in capsys.readouterr().err
    browser = httpx.Response(200, json={**PAGE, "engine": "browser"})
    assert cli_main(["result", "j1", "--browser"], client=_client(Recorder(browser))) == 0
    capsys.readouterr()
    assert cli_main(["result", "j1"], client=_client(Recorder(downgraded))) == 0      # static scrape: no check
    assert all("engine" not in r.url.params for r in rec.requests)                   # client-side only


def test_wait_for_without_browser_is_a_usage_error(capsys) -> None:
    assert cli_main(["scrape", "https://e.example/", "--wait-for", "500"], client=_client(Recorder())) == 2
    assert "--wait-for needs --browser" in capsys.readouterr().err


def _batch(*engines: str | None, status: str = "completed") -> httpx.Response:
    items = [{"url": f"https://e.example/{i}", "status": "completed", "job_id": f"j{i}",
              "result": {**PAGE, "job_id": f"j{i}", **({"engine": engine} if engine else {})}}
             for i, engine in enumerate(engines)]
    return httpx.Response(200, json={"batch_id": "b1", "status": status, "total": len(items), "items": items})


def test_cli_batch_keeps_the_downgrade_guard(capsys) -> None:
    """``scrawl batch --browser`` (and ``batch-status --browser``) refuse items another engine rendered."""
    started = httpx.Response(202, json={"batch_id": "b1", "status": "running", "total": 2})
    for downgraded in (_batch("browser", "static"), _batch("browser", None)):
        rec = Recorder(started, downgraded)
        assert cli_main(["batch", "https://e.example/0", "https://e.example/1", "--browser", "--wait", "30"],
                        client=_client(rec)) == 5
        out = capsys.readouterr()
        assert "render_not_supported" in out.err and json.loads(out.out)["batch_id"] == "b1"   # nothing is lost
    assert cli_main(["batch-status", "b1", "--browser"], client=_client(Recorder(_batch("static")))) == 5
    assert "render_not_supported" in capsys.readouterr().err
    assert cli_main(["batch-status", "b1", "--browser"], client=_client(Recorder(_batch("browser", "browser")))) == 0
    capsys.readouterr()
    assert cli_main(["batch-status", "b1"], client=_client(Recorder(_batch("static")))) == 0      # static: no check
    capsys.readouterr()
    pending = httpx.Response(200, json={"batch_id": "b1", "status": "running", "total": 1,
                                        "items": [{"url": "https://e.example/0", "status": "pending", "result": None}]})
    assert cli_main(["batch-status", "b1", "--browser"], client=_client(Recorder(pending))) == 4   # no verdict yet
    capsys.readouterr()
    early = _batch("static", status="running")                     # one item already finished, by the wrong engine
    assert cli_main(["batch-status", "b1", "--browser"], client=_client(Recorder(early))) == 5
