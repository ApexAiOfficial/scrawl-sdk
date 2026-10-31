"""Shared test helpers: a recording mock transport, the repository's contract tools, the fake ApexAPI."""

from __future__ import annotations

import json
import sys
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from scrawl import AsyncScrawl, Scrawl

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "tools"
sys.path.insert(0, str(TOOLS))

import check_contracts  # noqa: E402

OPENAPI = check_contracts.load_json(check_contracts.OPENAPI)
COVERAGE = check_contracts.load_json(check_contracts.COVERAGE)


class Recorder:
    """A mock ApexAPI transport: queued responses (then ``{}``), every request recorded."""

    def __init__(self, *responses: httpx.Response) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not self.responses:
            return httpx.Response(200, json={})
        return self.responses.pop(0)


def make_client(recorder: Any, **kwargs: Any) -> Scrawl:
    return Scrawl("sk-test", base_url="https://scrawl.test",
                  http_client=httpx.Client(transport=httpx.MockTransport(recorder)), **kwargs)


def make_async_client(recorder: Any, **kwargs: Any) -> AsyncScrawl:
    return AsyncScrawl("sk-test", base_url="https://scrawl.test",
                       http_client=httpx.AsyncClient(transport=httpx.MockTransport(recorder)), **kwargs)


def body(request: httpx.Request) -> dict:
    return json.loads(request.content) if request.content else {}


def as_recorded(request: httpx.Request) -> dict[str, Any]:
    """An httpx request in the shape ``check_contracts.check_request`` takes."""
    query: dict[str, Any] = {}
    for key, value in request.url.params.multi_items():
        query[key] = [*query[key], value] if key in query and isinstance(query[key], list) else \
            [query[key], value] if key in query else value
    return {"method": request.method, "path": request.url.raw_path.split(b"?")[0].decode(), "query": query,
            "body": json.loads(request.content) if request.content else None, "headers": dict(request.headers)}


@pytest.fixture
def fake_api() -> Iterator[tuple[str, Any]]:
    """The fake ApexAPI on a loopback port: (base URL, the FakeApexAPI with its recorded problems)."""
    from fake_apexapi import make_server

    server, fake = make_server(0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", fake
    finally:
        server.shutdown()
        server.server_close()
