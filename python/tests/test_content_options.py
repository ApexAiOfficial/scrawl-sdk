"""CE-8: ``only_main_content``, ``include_tags`` and ``exclude_tags`` on scrape and batch_scrape (mock transport)."""

from __future__ import annotations

import inspect
import json

import httpx
import pytest

from scrawl import AsyncScrawl, Scrawl, ValidationError

OPTIONS = ("only_main_content", "include_tags", "exclude_tags")
PAGE = {"job_id": "j1", "status": "completed", "url": "https://e.example/", "markdown": "# Hi"}
BATCH = {"batch_id": "b1", "status": "running"}


class Recorder:
    def __init__(self, *responses: httpx.Response) -> None:
        self.responses, self.requests = list(responses), []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return self.responses.pop(0) if self.responses else httpx.Response(200, json=PAGE)

    @property
    def bodies(self) -> list[dict]:
        return [json.loads(request.content) for request in self.requests]


def _client(rec: Recorder) -> Scrawl:
    return Scrawl("sk-test", base_url="https://scrawl.test", max_retries=0,
                  http_client=httpx.Client(transport=httpx.MockTransport(rec)))


def test_bodies_omit_the_content_options_unless_they_are_set() -> None:
    rec = Recorder()
    c = _client(rec)
    c.scrape("https://e.example/")
    c.batch_scrape(["https://e.example/"])
    c.scrape("https://e.example/", only_main_content=None, include_tags=None, exclude_tags=None)
    c.batch_scrape(["https://e.example/"], only_main_content=None, include_tags=None, exclude_tags=None)
    assert len(rec.bodies) == 4
    for body in rec.bodies:
        assert not set(OPTIONS) & set(body), body
    # A request without them is byte-identical to one that passes them as None.
    assert rec.requests[0].content == rec.requests[2].content
    assert rec.requests[1].content == rec.requests[3].content


def test_scrape_and_batch_scrape_send_the_passed_options_by_their_contract_names() -> None:
    rec = Recorder()
    c = _client(rec)
    c.scrape("https://e.example/", only_main_content=False, include_tags=["article", ".post > p"],
             exclude_tags=["nav", "#cookie-banner"])
    c.batch_scrape(["https://e.example/a", "https://e.example/b"], only_main_content=True, include_tags=["main"],
                   exclude_tags=["aside", "[role=banner]"])
    scrape, batch = rec.bodies
    assert (scrape["only_main_content"], scrape["include_tags"], scrape["exclude_tags"]) == \
        (False, ["article", ".post > p"], ["nav", "#cookie-banner"])
    assert (batch["only_main_content"], batch["include_tags"], batch["exclude_tags"]) == \
        (True, ["main"], ["aside", "[role=banner]"])
    assert batch["urls"] == ["https://e.example/a", "https://e.example/b"]


def test_each_option_is_independent_and_false_is_not_dropped() -> None:
    rec = Recorder()
    c = _client(rec)
    c.scrape("https://e.example/", only_main_content=False)
    c.scrape("https://e.example/", include_tags=["article"])
    c.scrape("https://e.example/", exclude_tags=["nav"])
    c.batch_scrape(["https://e.example/"], only_main_content=False)
    only_main, include, exclude, batch = rec.bodies
    assert only_main["only_main_content"] is False and not {"include_tags", "exclude_tags"} & set(only_main)
    assert include["include_tags"] == ["article"] and not {"only_main_content", "exclude_tags"} & set(include)
    assert exclude["exclude_tags"] == ["nav"] and not {"only_main_content", "include_tags"} & set(exclude)
    assert batch["only_main_content"] is False and not {"include_tags", "exclude_tags"} & set(batch)


def test_the_options_ride_along_with_the_engine_and_the_server_validates_the_selectors() -> None:
    rec = Recorder(httpx.Response(200, json={**PAGE, "engine": "browser"}),
                   httpx.Response(422, json={"error": {"code": "invalid_request", "message": "bad selector"}}))
    c = _client(rec)
    c.scrape("https://e.example/", engine="browser", wait_for_ms=250, include_tags=["main"])
    body = rec.bodies[0]
    assert (body["engine"], body["wait_for_ms"], body["include_tags"]) == ("browser", 250, ["main"])
    # The SDK does not re-implement the selector validation: whatever is passed is sent, and the 422 is the answer.
    with pytest.raises(ValidationError) as raised:
        c.scrape("https://e.example/", include_tags=["div:has(p)"])
    assert raised.value.code == "invalid_request"
    assert rec.bodies[1]["include_tags"] == ["div:has(p)"]


def test_map_and_the_job_follow_ups_do_not_take_the_content_options() -> None:
    for method in (Scrawl.map, Scrawl.scrape_result, Scrawl.wait_for_scrape):
        assert not set(OPTIONS) & set(inspect.signature(method).parameters), method
    for method in (Scrawl.scrape, Scrawl.batch_scrape, AsyncScrawl.scrape, AsyncScrawl.batch_scrape):
        parameters = inspect.signature(method).parameters
        assert set(OPTIONS) <= set(parameters), method
        assert all(parameters[name].default is None for name in OPTIONS), method


async def test_the_async_client_sends_the_same_options() -> None:
    rec = Recorder(httpx.Response(200, json=PAGE), httpx.Response(200, json=PAGE),
                   httpx.Response(202, json=BATCH), httpx.Response(202, json=BATCH))
    async with AsyncScrawl("k", base_url="https://scrawl.test", max_retries=0,
                           http_client=httpx.AsyncClient(transport=httpx.MockTransport(rec))) as c:
        await c.scrape("https://e.example/")
        await c.scrape("https://e.example/", only_main_content=False, include_tags=["article"], exclude_tags=["nav"])
        await c.batch_scrape(["https://e.example/"])
        await c.batch_scrape(["https://e.example/"], only_main_content=False, include_tags=["main"],
                             exclude_tags=["footer"])
    plain_scrape, scrape, plain_batch, batch = rec.bodies
    assert not set(OPTIONS) & (set(plain_scrape) | set(plain_batch))
    assert (scrape["only_main_content"], scrape["include_tags"], scrape["exclude_tags"]) == \
        (False, ["article"], ["nav"])
    assert (batch["only_main_content"], batch["include_tags"], batch["exclude_tags"]) == \
        (False, ["main"], ["footer"])
