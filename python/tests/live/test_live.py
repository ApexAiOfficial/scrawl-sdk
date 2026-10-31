"""Live compatibility suite: every covered ApexAPI operation against a real Scrawl server.

Skipped unless both are set:
  SCRAWL_LIVE_BASE_URL      the server, e.g. https://scrawl.example or http://127.0.0.1:8088
  SCRAWL_LIVE_API_KEY       a key with the default scopes (scrape:write, jobs:read, artifacts:read, credits:read)
Deterministic targets and optional areas (each area is skipped, with its reason, until its variables are set):
  SCRAWL_LIVE_TARGET_URL    a stable page the server may fetch (required for anything that fetches)
  SCRAWL_LIVE_CRAWL_TARGET  a crawl target the key may run (crawl, datasets, search, documents, quarantine)
  SCRAWL_LIVE_AI_PROVIDER, SCRAWL_LIVE_AI_API_KEY [SCRAWL_LIVE_AI_MODEL, SCRAWL_LIVE_AI_BASE_URL]
                            your own AI provider (profiles, JSON scrape, extract, ask, dataset extraction);
                            the key needs ai:configure and ai:use
  SCRAWL_LIVE_ASSETS=1      the server allows asset extraction with egress for this key
  SCRAWL_LIVE_BROWSER=1     the server has browser rendering enabled

``covers(...)`` names the operations each test exercises; a unit test checks that together they name every
covered operation in coverage.json, so the suite cannot silently fall behind the SDK.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Callable, Iterator
from typing import Any

import pytest

from scrawl import (
    AuthenticationError,
    ConflictError,
    ErrorCode,
    NotFoundError,
    Scrawl,
    ScrawlError,
)
from scrawl.cli import main as cli_main

BASE_URL = os.environ.get("SCRAWL_LIVE_BASE_URL", "")
API_KEY = os.environ.get("SCRAWL_LIVE_API_KEY", "")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not (BASE_URL and API_KEY), reason="set SCRAWL_LIVE_BASE_URL and SCRAWL_LIVE_API_KEY"),
]


def covers(*routes: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Record the operations a live test exercises (read statically by the coverage test)."""
    def mark(test: Callable[..., Any]) -> Callable[..., Any]:
        test.covers = routes  # type: ignore[attr-defined]
        return test
    return mark


def need(*names: str) -> list[str]:
    values = [os.environ.get(name, "") for name in names]
    missing = [name for name, value in zip(names, values) if not value]
    if missing:
        pytest.skip(f"set {', '.join(missing)}")
    return values


@pytest.fixture(scope="module")
def client() -> Iterator[Scrawl]:
    with Scrawl(API_KEY, base_url=BASE_URL, timeout=90) as live:
        yield live


@pytest.fixture(scope="module")
def page(client: Scrawl) -> Any:
    """One completed scrape of the target page, shared by the tests that read its job."""
    (target,) = need("SCRAWL_LIVE_TARGET_URL")
    result = client.scrape(target, formats=["markdown", "links"], wait_seconds=60)
    if result.status == "pending":
        result = client.wait_for_scrape(result.job_id, timeout=300)
    assert result.status == "completed", result.get("error")
    return result


@covers("GET /v1/health", "GET /v1/jobs")
def test_health_auth_and_the_setup_check(client: Scrawl, monkeypatch) -> None:
    assert client.health().status == "ok"
    assert isinstance(client.list_jobs(limit=1), dict)
    with Scrawl("sk_live_suite_wrong_key", base_url=BASE_URL, max_retries=0) as wrong:
        with pytest.raises(AuthenticationError) as refused:
            wrong.list_jobs(limit=1)
    assert refused.value.status == 401
    monkeypatch.setenv("SCRAWL_BASE_URL", BASE_URL)
    monkeypatch.setenv("SCRAWL_API_KEY", API_KEY)
    assert cli_main(["doctor"]) == 0


@covers("GET /v1/jobs/{job_id}")
def test_an_unknown_id_is_a_404(client: Scrawl) -> None:
    with pytest.raises(NotFoundError) as missing:
        client.get_job(f"missing-{uuid.uuid4().hex}")
    assert missing.value.status == 404 and missing.value.code == ErrorCode.NOT_FOUND


@covers("POST /v1/scrape", "GET /v1/scrape/{job_id}/content", "GET /v1/jobs/{job_id}", "GET /v1/artifacts/{job_id}",
        "GET /v1/artifacts/{job_id}/{filename}")
def test_scrape_result_job_and_artifacts(client: Scrawl, page: Any) -> None:
    assert page.markdown and page.untrusted_external_content is True
    again = client.scrape_result(page.job_id, formats=["links"])
    assert again.status == "completed" and isinstance(again.links, list)
    assert client.get_job(page.job_id).job_id == page.job_id
    artifacts = client.list_artifacts(page.job_id).artifacts
    assert artifacts, "a completed scrape job lists its artifacts"
    first = artifacts[0]
    data = client.download_artifact(page.job_id, first.name)
    assert isinstance(data, bytes) and len(data) == first.size_bytes


@covers("POST /v1/map")
def test_map(client: Scrawl) -> None:
    (target,) = need("SCRAWL_LIVE_TARGET_URL")
    site = client.map(target, limit=20, wait_seconds=60)
    assert site.status in ("completed", "pending") and isinstance(site.get("links") or [], list)


@covers("POST /v1/scrape/batch", "GET /v1/scrape/batch/{batch_id}")
def test_batch(client: Scrawl) -> None:
    (target,) = need("SCRAWL_LIVE_TARGET_URL")
    started = client.batch_scrape([target])
    done = client.wait_for_batch(started.batch_id, timeout=300)
    assert done.status == "completed" and done["items"][0].status == "completed"


@covers("POST /v1/jobs/{job_id}/cancel")
def test_cancel(client: Scrawl) -> None:
    (target,) = need("SCRAWL_LIVE_TARGET_URL")
    started = client.scrape(target, wait_seconds=0)
    try:
        result = client.cancel_job(started.job_id)
    except ConflictError:                               # it already finished: nothing to cancel
        return
    assert result.job_id == started.job_id and isinstance(result.cancelled, bool)


@covers("GET /v1/credits/balance")
def test_balance(client: Scrawl) -> None:
    assert isinstance(client.credit_balance(), dict)


@pytest.fixture(scope="module")
def ai_profile(client: Scrawl) -> Iterator[str]:
    provider, key = need("SCRAWL_LIVE_AI_PROVIDER", "SCRAWL_LIVE_AI_API_KEY")
    name = f"live{uuid.uuid4().hex[:8]}"
    info = client.set_ai_provider(name, provider=provider, api_key=key,
                                  model=os.environ.get("SCRAWL_LIVE_AI_MODEL") or None,
                                  base_url=os.environ.get("SCRAWL_LIVE_AI_BASE_URL") or None)
    assert info.profile == name and key not in str(info)
    try:
        yield name
    finally:
        client.delete_ai_provider(name)


@covers("PUT /v1/ai/providers/{profile}", "GET /v1/ai/providers", "POST /v1/ai/providers/{profile}/default",
        "POST /v1/ai/providers/{profile}/test", "GET /v1/ai/usage", "POST /v1/extract",
        "DELETE /v1/ai/providers/{profile}")
def test_byo_ai_profile_json_scrape_and_extract(client: Scrawl, ai_profile: str, page: Any) -> None:
    assert ai_profile in [p.profile for p in client.list_ai_providers().profiles]
    assert client.set_default_ai_provider(ai_profile).is_default is True
    assert client.test_ai_provider(ai_profile).ok is True
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    product = client.scrape(page.url, formats=["json"], schema=schema, profile=ai_profile, wait_seconds=60)
    if product.status == "pending":
        product = client.wait_for_scrape(product.job_id)
    assert product.status == "completed" and isinstance(product.json, dict)
    extracted = client.extract(page.job_id, "response.html", instruction="The page title", profile=ai_profile)
    assert "data" in extracted
    assert isinstance(client.ai_usage(days=1).totals, list)


@pytest.fixture(scope="module")
def dataset(client: Scrawl) -> dict[str, Any]:
    """Two completed crawls of the same target: a dataset with (at least) two versions."""
    (target,) = need("SCRAWL_LIVE_CRAWL_TARGET")
    launches = []
    for _ in range(2):
        launch = client.crawl(target, max_items=20, max_seconds=300)
        job = client.wait_for_job(launch.job_id, timeout=900)
        assert str(job.status).upper() == "COMPLETED", job
        launches.append(launch)
    return {"dataset_id": launches[-1].dataset_id, "versions": [launch.dataset_version_id for launch in launches]}


@covers("POST /v1/crawls", "GET /v1/datasets", "GET /v1/datasets/{dataset_id}", "GET /v1/datasets/{dataset_id}/versions",
        "GET /v1/datasets/{dataset_id}/fields", "POST /v1/datasets/{dataset_id}/query",
        "GET /v1/datasets/{dataset_id}/diff", "POST /v1/datasets/{dataset_id}/active-version", "POST /v1/search",
        "GET /v1/documents/{document_id}", "PUT /v1/datasets/{dataset_id}/records/{record_id}/quarantine",
        "DELETE /v1/datasets/{dataset_id}/records/{record_id}/quarantine")
def test_crawl_into_datasets_and_query(client: Scrawl, dataset: dict[str, Any]) -> None:
    dataset_id, (older, newer) = dataset["dataset_id"], dataset["versions"]
    assert dataset_id in [d.dataset_id for d in client.paginate(client.list_datasets, limit=50)]
    assert client.get_dataset(dataset_id).dataset.dataset_id == dataset_id
    assert {older, newer} <= {v.version_id for v in client.paginate(client.list_versions, dataset_id)}
    fields = client.dataset_fields(dataset_id, version=newer).fields
    assert fields, "a crawl publishes records with fields"
    rows = client.query_dataset(dataset_id, [{"field": fields[0].path, "op": "exists", "value": True}],
                                version_id=newer, limit=5)
    assert rows.records
    diff = client.diff_versions(dataset_id, older, newer)
    assert set(diff.totals) >= {"added", "removed", "changed"}
    assert client.activate_version(dataset_id, older).dataset.active_version_id == older
    assert client.activate_version(dataset_id, newer).dataset.active_version_id == newer
    hits = client.search(rows.records[0].title or fields[0].path, limit=5).results
    if hits:
        assert client.get_document(hits[0].id).id == hits[0].id
    record_id = rows.records[0].record_id
    assert client.quarantine_record(dataset_id, record_id, reason="live suite").quarantined is True
    assert client.release_record(dataset_id, record_id).quarantined is False


@covers("POST /v1/datasets/{dataset_id}/extract", "POST /v1/ask")
def test_ai_over_datasets(client: Scrawl, dataset: dict[str, Any], ai_profile: str) -> None:
    launch = client.extract_dataset(dataset["dataset_id"], instruction="The title of each record", profile=ai_profile,
                                    max_records=5)
    job = client.wait_for_job(launch.job_id, timeout=900)
    assert str(job.status).upper() == "COMPLETED", job
    answer = client.ask("What is in this dataset?", dataset_id=dataset["dataset_id"], profile=ai_profile)
    assert isinstance(answer.answer, str) and isinstance(answer.citations, list)


@covers("POST /v1/assets/quote", "POST /v1/assets", "GET /v1/assets/{job_id}", "GET /v1/assets/{job_id}/files/{asset_id}")
def test_assets(client: Scrawl) -> None:
    target, _ = need("SCRAWL_LIVE_TARGET_URL", "SCRAWL_LIVE_ASSETS")
    quote = client.quote_assets(target, classes=["images", "documents"], max_items=5)
    assert quote.egress_ready is True, "SCRAWL_LIVE_ASSETS=1 needs a key with usable egress"
    job = client.extract_assets(target, classes=["images", "documents"], max_items=5)
    result = client.wait_for_assets(job.job_id, timeout=600)
    assert result.status == "completed", result.get("failure_reason")
    for asset in client.paginate(client.get_assets, job.job_id):
        data = client.download_asset(job.job_id, asset.asset_id)
        assert hashlib.sha256(data).hexdigest() == asset.sha256
        break


def test_browser_rendering(client: Scrawl) -> None:
    target, _ = need("SCRAWL_LIVE_TARGET_URL", "SCRAWL_LIVE_BROWSER")
    try:
        rendered = client.scrape(target, engine="browser", wait_seconds=60)
    except ScrawlError as exc:
        pytest.fail(f"SCRAWL_LIVE_BROWSER=1 but the server refused: {exc}")
    if rendered.status == "pending":
        rendered = client.wait_for_scrape(rendered.job_id, engine="browser")
    assert rendered.engine == "browser"
