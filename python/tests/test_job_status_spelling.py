"""A job's status has one spelling, the lower case; the SDK still reads the upper case older servers send.

``pending``, ``running``, ``completed``, ``failed``, ``cancelled`` and ``orphaned`` are what the API's ``JobStatus``
promises. Servers before that change sent ``COMPLETED`` from the job and dataset routes; the SDK turns those six
words into the lower case on the responses that carry a job's status, so code written against the one spelling
works with either server. Other statuses (a scrape's, an asset's, a proxy pool entry's) are never touched.
"""

from __future__ import annotations

import httpx
import pytest

from scrawl import AsyncScrawl, Scrawl

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
def test_a_job_reads_either_spelling_and_exposes_the_lower_case(given: str) -> None:
    for sent in (given, given.lower()):
        assert _client({"job_id": "j1", "status": sent}).get_job("j1").status == given.lower()


def test_every_job_and_dataset_route_exposes_the_lower_case() -> None:
    c = _client({"jobs": [{"job_id": "a", "status": "RUNNING"}, {"job_id": "b", "status": "completed"}],
                 "next_cursor": None},
                {"job_id": "a", "cancelled": True, "status": "CANCELLED"},
                {"job_id": "c", "dataset_id": "d", "status": "PENDING"},
                {"job_id": "e", "status": "PENDING"},
                {"count": 2, "versions": [{"version_id": "v1", "status": "COMPLETED"},
                                          {"version_id": "v2", "status": "ORPHANED"}], "next_cursor": None},
                {"dataset": {"dataset_id": "d"}, "versions": [{"version_id": "v1", "status": "FAILED"}]})
    assert [job.status for job in c.list_jobs().jobs] == ["running", "completed"]
    assert c.cancel_job("a").status == "cancelled"
    assert c.crawl("lab").status == "pending"
    assert c.extract_dataset("d", instruction="titles").status == "pending"
    assert [version.status for version in c.list_versions("d").versions] == ["completed", "orphaned"]
    assert [version.status for version in c.get_dataset("d").versions] == ["failed"]


def test_statuses_that_are_not_a_job_status_are_left_as_sent() -> None:
    c = _client({"job_id": "j1", "status": "completed", "assets": [{"asset_id": "a1", "status": "FAILED"}]},
                {"entries": [{"entry_id": "p1", "status": "ACTIVE"}]},
                {"job_id": "j2", "status": "QUEUED"})
    assets = c.get_assets("j1")
    assert assets.assets[0].status == "FAILED"                         # an asset's own status, not the job's
    assert c.list_proxy_pool().entries[0].status == "ACTIVE"
    assert c.get_job("j2").status == "QUEUED"                          # not one of the six: never guessed at


@pytest.mark.asyncio
async def test_the_async_client_reads_either_spelling_the_same_way() -> None:
    c = _async_client({"job_id": "j1", "status": "ORPHANED"},
                      {"jobs": [{"job_id": "j1", "status": "FAILED"}], "next_cursor": None},
                      {"count": 1, "versions": [{"version_id": "v1", "status": "RUNNING"}], "next_cursor": None})
    assert (await c.get_job("j1")).status == "orphaned"
    assert [job.status for job in (await c.list_jobs()).jobs] == ["failed"]
    assert [version.status for version in (await c.list_versions("d")).versions] == ["running"]
    await c.close()
