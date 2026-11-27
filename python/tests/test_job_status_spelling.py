"""A job's status reaches you as the server sent it; the SDK's own logic reads either spelling.

``pending``, ``running``, ``completed``, ``failed``, ``cancelled`` and ``orphaned`` are what the API's ``JobStatus``
promises today. Servers before that change sent ``COMPLETED`` from the job and dataset routes. This release (a patch)
never rewrites a status: code written for 0.1.4 sees exactly what it saw before, against either server. The SDK's own
waits and the CLI's exit codes read either spelling. Comparing with the lower case is the way forward; the upper case
is deprecated and a later minor release may stop reading it.
"""

from __future__ import annotations

import json

import httpx
import pytest

from scrawl import AsyncScrawl, Scrawl
from scrawl.cli import main as cli_main

UPPER = ["PENDING", "RUNNING", "COMPLETED", "FAILED", "CANCELLED", "ORPHANED"]


def _client(*bodies: dict) -> Scrawl:
    queue = [httpx.Response(200, json=body) for body in bodies]
    return Scrawl("sk-test", base_url="https://scrawl.test",
                  http_client=httpx.Client(transport=httpx.MockTransport(lambda request: queue.pop(0))))


def _async_client(*bodies: dict) -> AsyncScrawl:
    queue = [httpx.Response(200, json=body) for body in bodies]
    return AsyncScrawl("sk-test", base_url="https://scrawl.test",
                       http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda request: queue.pop(0))))


@pytest.mark.parametrize("given", UPPER)
def test_a_job_status_is_passed_through_in_either_spelling(given: str) -> None:
    for sent in (given, given.lower()):
        assert _client({"job_id": "j1", "status": sent}).get_job("j1").status == sent


def test_every_job_and_dataset_route_passes_the_status_through() -> None:
    c = _client({"jobs": [{"job_id": "a", "status": "RUNNING"}, {"job_id": "b", "status": "completed"}],
                 "next_cursor": None},
                {"job_id": "a", "cancelled": True, "status": "CANCELLED"},
                {"job_id": "c", "dataset_id": "d", "status": "pending"},
                {"job_id": "e", "status": "PENDING"},
                {"count": 2, "versions": [{"version_id": "v1", "status": "COMPLETED"},
                                          {"version_id": "v2", "status": "orphaned"}], "next_cursor": None},
                {"crawl_id": "s1", "status": "RUNNING", "done": False, "pages": []})
    assert [job.status for job in c.list_jobs().jobs] == ["RUNNING", "completed"]
    assert c.cancel_job("a").status == "CANCELLED"
    assert c.crawl("lab").status == "pending"
    assert c.extract_dataset("d", instruction="titles").status == "PENDING"
    assert [version.status for version in c.list_versions("d").versions] == ["COMPLETED", "orphaned"]
    assert c.site_crawl_status("s1").status == "RUNNING"


@pytest.mark.parametrize("finished", ["COMPLETED", "completed", "FAILED", "failed", "CANCELLED", "orphaned"])
def test_wait_for_job_stops_on_a_finished_job_in_either_spelling(finished: str) -> None:
    c = _client({"job_id": "j1", "status": "PENDING"}, {"job_id": "j1", "status": "running"},
                {"job_id": "j1", "status": finished})
    assert c.wait_for_job("j1").status == finished


@pytest.mark.parametrize(("status", "code"), [("COMPLETED", 0), ("completed", 0), ("FAILED", 1), ("cancelled", 1),
                                              ("RUNNING", 4), ("pending", 4)])
def test_the_cli_exit_codes_read_either_spelling(status: str, code: int, capsys, monkeypatch) -> None:
    clock = iter(range(0, 10**6, 100))                                  # each look at the clock: 100 s later
    monkeypatch.setattr("scrawl._client.time.monotonic", lambda: next(clock))
    c = _client({"job_id": "j1", "dataset_id": "d1", "dataset_version_id": "v1", "status": "PENDING"},
                {"job_id": "j1", "status": status})
    assert cli_main(["crawl", "t", "--wait", "1"], client=c) == code
    assert json.loads(capsys.readouterr().out)["job"]["status"] == status


@pytest.mark.parametrize(("status", "code"), [("COMPLETED", 0), ("completed", 0), ("FAILED", 1), ("cancelled", 1)])
def test_a_finished_site_crawl_exits_by_its_status_in_either_spelling(status: str, code: int, capsys) -> None:
    c = _client({"crawl_id": "s1", "status": status, "done": True, "pages": []})
    assert cli_main(["site-crawl-status", "s1"], client=c) == code
    assert json.loads(capsys.readouterr().out)["status"] == status


@pytest.mark.asyncio
async def test_the_async_client_passes_the_status_through_the_same_way() -> None:
    c = _async_client({"job_id": "j1", "status": "ORPHANED"},
                      {"jobs": [{"job_id": "j1", "status": "failed"}], "next_cursor": None},
                      {"job_id": "j2", "status": "RUNNING"}, {"job_id": "j2", "status": "COMPLETED"})
    assert (await c.get_job("j1")).status == "ORPHANED"
    assert [job.status for job in (await c.list_jobs()).jobs] == ["failed"]
    assert (await c.wait_for_job("j2")).status == "COMPLETED"
    await c.close()
