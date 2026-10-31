"""Scrawl API clients (sync ``Scrawl`` and ``AsyncScrawl``) over the versioned ApexAPI contract.

Every endpoint is defined once (``_Endpoints``) as a request description; the sync and async clients
only differ in how they send it. Submits that start work (scrape, map, batch, crawl, dataset and
asset extraction) carry an ``Idempotency-Key`` — generated unless you pass one — so a retry after a network
error or a 429/5xx never starts the work twice. Other POSTs are never retried, and neither is any response
whose error code the backend's error catalogue marks not retryable (``_errors.RETRYABLE``).

The base URL comes from the argument or ``SCRAWL_BASE_URL``; without either, the client talks to a
Scrawl server on this machine (``http://127.0.0.1:8088``). There is no built-in remote default.
"""

from __future__ import annotations

import asyncio
import os
import random
import re
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from ._errors import (
    APIConnectionError,
    APITimeoutError,
    ConfigurationError,
    ErrorCode,
    ScrawlError,
    code_of,
    error_for,
    never_retry,
)
from ._objects import ScrawlObject, wrap
from ._version import __version__

DEFAULT_BASE_URL = "http://127.0.0.1:8088"      # a Scrawl server on this machine; remote servers need SCRAWL_BASE_URL
RETRY_STATUSES = frozenset({429, 502, 503, 504})
_LIST_KEYS = ("datasets", "versions", "jobs", "entries", "records", "results", "items", "assets", "skipped")
_ASSETS_ACTIVE = frozenset({"pending", "running"})
_JOBS_ACTIVE = frozenset({"PENDING", "RUNNING"})
#: What an API key may contain: visible ASCII, the characters an HTTP header value can carry as a token.
_KEY_CHARS = re.compile(r"[\x21-\x7e]+")


@dataclass(frozen=True)
class _Request:
    method: str
    path: str
    params: dict[str, Any] = field(default_factory=dict)
    json: Any = None
    idempotency_key: str | None = None
    raw: bool = False
    auth: bool = True
    #: The engine the caller asked for; a finished result that echoes another one is a downgrade.
    expect_engine: str | None = None


def _clean(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _seg(value: str) -> str:
    text = str(value)
    # URL normalization resolves "." and ".." segments: never let an id walk to another route.
    if text in ("", ".", ".."):
        raise ScrawlError(f"Invalid path segment: {text!r}")
    return quote(text, safe="")


def _key(value: str | None) -> str:
    return value or uuid.uuid4().hex


def _engine(engine: str | None, wait_for_ms: int | None) -> dict[str, Any]:
    """The engine options for a body, only when set (a static request's body is unchanged)."""
    return _clean({"engine": engine, "wait_for_ms": wait_for_ms})


def _check_engine(request: _Request, result: Any) -> Any:
    """The downgrade guard: ``browser`` was asked for, but a finished result says another engine rendered it."""
    if request.expect_engine == "browser" and isinstance(result, ScrawlObject) \
            and result.get("status") in ("completed", "failed") and result.get("engine") != "browser":
        raise ScrawlError("The server did not render this page in a browser (it may predate the browser engine)",
                          code=ErrorCode.RENDER_NOT_SUPPORTED.value, details={"engine": result.get("engine")})
    return result


class _Endpoints:
    """The ApexAPI surface. Each method returns the result (sync) or an awaitable (async)."""

    _t: _Transport

    def _call(self, request: _Request) -> Any:  # pragma: no cover - provided by the clients
        raise NotImplementedError

    def _wait(self, seconds: int) -> int:
        """A server-side wait that finishes inside this client's request timeout (≤ 60, the API cap)."""
        if not seconds or seconds <= 0:
            return seconds
        return max(1, min(int(seconds), 60, int(self._t.timeout) - 5))

    # -- scrape / map / batch ------------------------------------------------------------------
    def scrape(self, url: str, *, formats: list[str] | None = None, schema: dict | None = None,
               instruction: str | None = None, profile: str | None = None, wait_seconds: int = 30,
               engine: str | None = None, wait_for_ms: int | None = None,
               idempotency_key: str | None = None) -> Any:
        """Scrape one URL. ``status`` is ``completed``, ``pending`` (poll ``scrape_result``) or ``failed``.

        ``"json"`` in ``formats`` extracts with your own AI provider (``schema``, ``instruction``, ``profile``) and
        needs a key with the ``ai:use`` scope as well as ``scrape:write``.

        ``engine="browser"`` renders the page in a sandboxed browser first (only where the server enables it), waiting
        ``wait_for_ms`` more after it settles. A finished result from a server that did not render it raises
        ``ScrawlError(code="render_not_supported")``.
        """
        body = _clean({"url": url, "formats": formats or ["markdown"], "schema": schema,
                       "instruction": instruction, "profile": profile, "wait_seconds": self._wait(wait_seconds),
                       **_engine(engine, wait_for_ms)})
        return self._call(_Request("POST", "/v1/scrape", json=body, idempotency_key=_key(idempotency_key),
                                   expect_engine=engine))

    def scrape_result(self, job_id: str, *, wait_seconds: int = 0, formats: list[str] | None = None,
                      engine: str | None = None) -> Any:
        """A scrape job's result in the formats it asked for (or re-rendered as markdown/links/html).

        Pass the ``engine`` the scrape asked for to keep the downgrade guard on a pending job's follow-up.
        """
        params = _clean({"wait_seconds": self._wait(wait_seconds) or None,
                         "formats": ",".join(formats) if formats else None})
        return self._call(_Request("GET", f"/v1/scrape/{_seg(job_id)}/content", params=params, expect_engine=engine))

    def map(self, url: str, *, limit: int = 100, wait_seconds: int = 30, engine: str | None = None,
            wait_for_ms: int | None = None, idempotency_key: str | None = None) -> Any:
        """Same-host URLs of a site: the start page's links plus its sitemap.

        ``engine="browser"`` renders the start page in a browser first, with the same downgrade guard as
        ``scrape``.
        """
        body = {"url": url, "limit": limit, "wait_seconds": self._wait(wait_seconds), **_engine(engine, wait_for_ms)}
        return self._call(_Request("POST", "/v1/map", json=body, idempotency_key=_key(idempotency_key),
                                   expect_engine=engine))

    def batch_scrape(self, urls: list[str], *, formats: list[str] | None = None, schema: dict | None = None,
                     instruction: str | None = None, profile: str | None = None, engine: str | None = None,
                     wait_for_ms: int | None = None, idempotency_key: str | None = None) -> Any:
        """Start a batch of up to 20 URLs; poll ``batch_status`` (or use ``wait_for_batch``).

        ``"json"`` in ``formats`` needs the ``ai:use`` scope as well as ``scrape:write``, as for ``scrape``.
        ``engine="browser"`` renders every URL in a browser first, one at a time.
        """
        body = _clean({"urls": list(urls), "formats": formats or ["markdown"], "schema": schema,
                       "instruction": instruction, "profile": profile, **_engine(engine, wait_for_ms)})
        return self._call(_Request("POST", "/v1/scrape/batch", json=body, idempotency_key=_key(idempotency_key)))

    def batch_status(self, batch_id: str, *, wait_seconds: int = 0) -> Any:
        """A batch's items and their results."""
        params = _clean({"wait_seconds": self._wait(wait_seconds) or None})
        return self._call(_Request("GET", f"/v1/scrape/batch/{_seg(batch_id)}", params=params))

    # -- AI --------------------------------------------------------------------------------------
    def extract(self, job_id: str, artifact: str = "response.html", *, schema: dict | None = None,
                instruction: str | None = None, profile: str | None = None) -> Any:
        """Extract JSON from a finished job's artifact with your own AI provider."""
        body = _clean({"job_id": job_id, "artifact": artifact, "schema": schema, "instruction": instruction,
                       "profile": profile})
        return self._call(_Request("POST", "/v1/extract", json=body))

    def ask(self, question: str, *, dataset_id: str | None = None, profile: str | None = None) -> Any:
        """Answer a question from your datasets, with citations."""
        body = _clean({"question": question, "dataset_id": dataset_id, "profile": profile})
        return self._call(_Request("POST", "/v1/ask", json=body))

    def list_ai_providers(self) -> Any:
        """Your configured AI provider profiles (never the keys)."""
        return self._call(_Request("GET", "/v1/ai/providers"))

    def set_ai_provider(self, profile: str, *, provider: str, api_key: str, model: str | None = None,
                        base_url: str | None = None) -> Any:
        """Create or replace an AI provider profile (the key is stored encrypted, never returned)."""
        body = _clean({"provider": provider, "api_key": api_key, "model": model, "base_url": base_url})
        return self._call(_Request("PUT", f"/v1/ai/providers/{_seg(profile)}", json=body))

    def delete_ai_provider(self, profile: str) -> Any:
        """Delete an AI provider profile."""
        return self._call(_Request("DELETE", f"/v1/ai/providers/{_seg(profile)}"))

    def set_default_ai_provider(self, profile: str) -> Any:
        """Make a profile your default."""
        return self._call(_Request("POST", f"/v1/ai/providers/{_seg(profile)}/default"))

    def test_ai_provider(self, profile: str) -> Any:
        """Check a profile can reach its provider."""
        return self._call(_Request("POST", f"/v1/ai/providers/{_seg(profile)}/test"))

    def ai_usage(self, *, days: int = 30) -> Any:
        """Your AI calls and tokens by provider, model and feature."""
        return self._call(_Request("GET", "/v1/ai/usage", params={"days": days}))

    # -- crawls and jobs -------------------------------------------------------------------------
    def crawl(self, crawl_target: str, *, export_format: str | None = None, max_items: int | None = None,
              max_seconds: int | None = None, idempotency_key: str | None = None) -> Any:
        """Start a bounded crawl that publishes a new dataset version."""
        body = _clean({"crawl_target": crawl_target, "export_format": export_format, "max_items": max_items,
                       "max_seconds": max_seconds})
        return self._call(_Request("POST", "/v1/crawls", json=body, idempotency_key=_key(idempotency_key)))

    def get_job(self, job_id: str, *, wait_seconds: int = 0) -> Any:
        """A job's state; ``wait_seconds`` (≤60) returns as soon as it finishes."""
        params = _clean({"wait_seconds": self._wait(wait_seconds) or None})
        return self._call(_Request("GET", f"/v1/jobs/{_seg(job_id)}", params=params))

    def list_jobs(self, *, limit: int | None = None, status: str | None = None, cursor: str | None = None) -> Any:
        """Your jobs, newest first (``next_cursor`` pages)."""
        return self._call(_Request("GET", "/v1/jobs", params=_clean({"limit": limit, "status": status,
                                                                      "cursor": cursor})))

    def cancel_job(self, job_id: str) -> Any:
        """Cancel a pending or running job (another process's job: ``cancelled`` false, requested).

        Needs the scope that starts that kind of job: ``ai:use`` for a dataset extraction, else ``scrape:write``.
        """
        return self._call(_Request("POST", f"/v1/jobs/{_seg(job_id)}/cancel"))

    def list_artifacts(self, job_id: str) -> Any:
        """A job's artifacts."""
        return self._call(_Request("GET", f"/v1/artifacts/{_seg(job_id)}"))

    def download_artifact(self, job_id: str, filename: str, *, format: str | None = None) -> Any:
        """One artifact's bytes (``format="markdown"`` converts HTML)."""
        return self._call(_Request("GET", f"/v1/artifacts/{_seg(job_id)}/{_seg(filename)}",
                                   params=_clean({"format": format}), raw=True))

    # -- assets -----------------------------------------------------------------------------------
    def quote_assets(self, url: str, *, classes: list[str] | None = None, max_items: int | None = None,
                     max_bytes: int | None = None, max_credits: int | None = None) -> Any:
        """What extracting a page's assets would hold, your credits and egress readiness (starts nothing)."""
        body = _clean({"url": url, "classes": classes, "max_items": max_items, "max_bytes": max_bytes,
                       "max_credits": max_credits})
        return self._call(_Request("POST", "/v1/assets/quote", json=body))

    def extract_assets(self, url: str, *, classes: list[str] | None = None, max_items: int | None = None,
                       max_bytes: int | None = None, max_credits: int | None = None,
                       idempotency_key: str | None = None) -> Any:
        """Start extracting a page's assets (images, video, audio, documents, data, web_assets); a job."""
        body = _clean({"url": url, "classes": classes, "max_items": max_items, "max_bytes": max_bytes,
                       "max_credits": max_credits})
        return self._call(_Request("POST", "/v1/assets", json=body, idempotency_key=_key(idempotency_key)))

    def get_assets(self, job_id: str, *, view: str | None = None, limit: int | None = None,
                   cursor: str | None = None, wait_seconds: int = 0) -> Any:
        """An asset job's state and one page of its stored assets (``view="skipped"``: what it skipped, why)."""
        params = _clean({"view": view, "limit": limit, "cursor": cursor,
                         "wait_seconds": self._wait(wait_seconds) or None})
        return self._call(_Request("GET", f"/v1/assets/{_seg(job_id)}", params=params))

    def download_asset(self, job_id: str, asset_id: str) -> Any:
        """One stored asset's bytes: untrusted content, compare its ``sha256`` before you use it."""
        return self._call(_Request("GET", f"/v1/assets/{_seg(job_id)}/files/{_seg(asset_id)}", raw=True))

    # -- datasets ---------------------------------------------------------------------------------
    def list_datasets(self, *, limit: int | None = None, cursor: str | None = None) -> Any:
        """Your datasets (``next_cursor`` pages)."""
        return self._call(_Request("GET", "/v1/datasets", params=_clean({"limit": limit, "cursor": cursor})))

    def get_dataset(self, dataset_id: str) -> Any:
        """A dataset's manifest and active version."""
        return self._call(_Request("GET", f"/v1/datasets/{_seg(dataset_id)}"))

    def list_versions(self, dataset_id: str, *, limit: int | None = None, cursor: str | None = None,
                      status: str | None = None) -> Any:
        """A dataset's versions, newest first."""
        return self._call(_Request("GET", f"/v1/datasets/{_seg(dataset_id)}/versions",
                                   params=_clean({"limit": limit, "cursor": cursor, "status": status})))

    def activate_version(self, dataset_id: str, version_id: str) -> Any:
        """Make a completed version the active one."""
        return self._call(_Request("POST", f"/v1/datasets/{_seg(dataset_id)}/active-version",
                                   json={"version_id": version_id}))

    def diff_versions(self, dataset_id: str, from_version: str, to_version: str, *, limit: int | None = None,
                      cursor: str | None = None) -> Any:
        """Added / removed / changed records between two versions."""
        params = _clean({"from": from_version, "to": to_version, "limit": limit, "cursor": cursor})
        return self._call(_Request("GET", f"/v1/datasets/{_seg(dataset_id)}/diff", params=params))

    def dataset_fields(self, dataset_id: str, *, version: str | None = None) -> Any:
        """Fields discovered in a version: paths, types, presence, examples."""
        return self._call(_Request("GET", f"/v1/datasets/{_seg(dataset_id)}/fields",
                                   params=_clean({"version": version})))

    def query_dataset(self, dataset_id: str, filters: list[dict], *, version_id: str | None = None,
                      limit: int | None = None, cursor: str | None = None) -> Any:
        """Typed filters (eq, ne, lt, lte, gt, gte, contains, in, exists) over a version's records."""
        body = _clean({"filters": filters, "version_id": version_id, "limit": limit, "cursor": cursor})
        return self._call(_Request("POST", f"/v1/datasets/{_seg(dataset_id)}/query", json=body))

    def extract_dataset(self, dataset_id: str, *, schema: dict | None = None, instruction: str | None = None,
                        profile: str | None = None, version_id: str | None = None, max_records: int | None = None,
                        idempotency_key: str | None = None) -> Any:
        """Extract a structured dataset version from a dataset with your own AI provider (a job)."""
        body = _clean({"schema": schema, "instruction": instruction, "profile": profile, "version_id": version_id,
                       "max_records": max_records})
        return self._call(_Request("POST", f"/v1/datasets/{_seg(dataset_id)}/extract", json=body,
                                   idempotency_key=_key(idempotency_key)))

    def quarantine_record(self, dataset_id: str, record_id: str, *, reason: str | None = None) -> Any:
        """Hide a record from retrieval (reversible with ``release_record``)."""
        return self._call(_Request("PUT", f"/v1/datasets/{_seg(dataset_id)}/records/{_seg(record_id)}/quarantine",
                                   json=_clean({"reason": reason})))

    def release_record(self, dataset_id: str, record_id: str) -> Any:
        """Undo a quarantine."""
        return self._call(_Request("DELETE",
                                   f"/v1/datasets/{_seg(dataset_id)}/records/{_seg(record_id)}/quarantine"))

    def search(self, query: str, *, limit: int | None = None) -> Any:
        """Search your active dataset versions."""
        return self._call(_Request("POST", "/v1/search", json=_clean({"query": query, "limit": limit})))

    def get_document(self, document_id: str) -> Any:
        """One indexed record with provenance."""
        return self._call(_Request("GET", f"/v1/documents/{_seg(document_id)}"))

    # -- account ------------------------------------------------------------------------------------
    def credit_balance(self) -> Any:
        """Your credits (hosted) or unmetered (self-hosted)."""
        return self._call(_Request("GET", "/v1/credits/balance"))

    def health(self) -> Any:
        """Service health (no authentication needed)."""
        return self._call(_Request("GET", "/v1/health", auth=False))


def is_loopback(host: str) -> bool:
    """True for ``localhost``, ``*.localhost``, ``::1`` and ``127.x.x.x`` (plain HTTP stays on this machine)."""
    return _is_loopback(host)


def _is_loopback(host: str) -> bool:
    host = host.lower()
    return (host in ("localhost", "::1") or host.endswith(".localhost")
            or (host.startswith("127.") and host.count(".") == 3 and host.replace(".", "").isdigit()))


def _check_base_url(base_url: str, allow_insecure_http: bool) -> None:
    parts = urlsplit(base_url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ConfigurationError(f"Base URL must be an http(s) URL: {base_url!r}")
    if parts.scheme == "http" and not _is_loopback(parts.hostname) and not allow_insecure_http:
        raise ConfigurationError(f"Refusing to send the API key over plain HTTP to {parts.netloc}: use https:// "
                          "(or allow_insecure_http=True / SCRAWL_ALLOW_INSECURE_HTTP=1 on a trusted network)")


def _json_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _is_error_envelope(body: Any) -> bool:
    return isinstance(body, dict) and isinstance(body.get("error"), dict) and bool(body["error"].get("code"))


class _Transport:
    """Configuration, headers, retry policy and response decoding shared by both clients."""

    def __init__(self, api_key: str | None, base_url: str | None, timeout: float, max_retries: int,
                 allow_insecure_http: bool | None = None) -> None:
        # A key read from a file or a CRLF .env file keeps its line ending: trim it rather than send it.
        self.api_key = str(api_key or os.environ.get("SCRAWL_API_KEY") or "").strip() or None
        self.base_url = (base_url or os.environ.get("SCRAWL_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        if allow_insecure_http is None:
            allow_insecure_http = os.environ.get("SCRAWL_ALLOW_INSECURE_HTTP") == "1"
        _check_base_url(self.base_url, allow_insecure_http)
        self.timeout = timeout
        self.max_retries = max(0, int(max_retries))

    def headers(self, request: _Request) -> dict[str, str]:
        headers = {"User-Agent": f"scrawl-python/{__version__}", "Accept": "application/json"}
        if request.auth:
            if not self.api_key:
                raise ConfigurationError("No API key: pass api_key=... or set SCRAWL_API_KEY")
            if not _KEY_CHARS.fullmatch(self.api_key):
                # Never quote the key: an HTTP library refusing it would put the whole value in its message.
                raise ConfigurationError("The API key contains spaces, control or non-ASCII characters that an HTTP "
                                         "header cannot carry (not shown); check api_key=... or SCRAWL_API_KEY")
            headers["Authorization"] = f"Bearer {self.api_key}"
        if request.idempotency_key:
            headers["Idempotency-Key"] = request.idempotency_key
        return headers

    def failure(self, exc: httpx.HTTPError) -> ScrawlError:
        """The error for a request that got no response, with the API key scrubbed from the library's text."""
        text = str(exc)
        if self.api_key:                                 # as text, and as the repr of the header's bytes
            for form in {self.api_key, repr(self.api_key.encode("utf-8", "replace"))[2:-1]}:
                text = text.replace(form, "***")
        if isinstance(exc, httpx.TimeoutException):
            return APITimeoutError(f"Request timed out: {text}")
        return APIConnectionError(f"Connection failed: {text}")

    def retryable(self, request: _Request) -> bool:
        return request.method == "GET" or request.idempotency_key is not None

    def retry_response(self, request: _Request, response: httpx.Response) -> bool:
        """429 always; 502/503/504 for GETs, and for submits only when a proxy (not Scrawl) answered.

        Never when the error code is one the catalogue marks not retryable, whatever the status: a resend
        after ``submission_failed`` or ``settlement_failed`` may charge twice. Scrawl's own 5xx on a keyed
        submit is final too: its key now stores that outcome, so a retry would only replay a generic failure
        instead of this error.
        """
        if response.status_code < 400:
            return False
        body = _json_body(response)                    # only error bodies are parsed here: they are small
        if never_retry(code_of(body)):
            return False
        if response.status_code == 429:
            return True
        if response.status_code not in RETRY_STATUSES:
            return False
        return request.method == "GET" or not _is_error_envelope(body)

    def replay_deadline(self, request: _Request) -> float:
        """Until when a keyed submit waits out 409s from its still-running first attempt."""
        wait = (request.json or {}).get("wait_seconds", 60) if isinstance(request.json, dict) else 60
        return time.monotonic() + float(wait or 0) + 15.0

    def waits_for_replay(self, request: _Request, response: httpx.Response, deadline: float) -> bool:
        return (response.status_code == 409 and request.idempotency_key is not None and time.monotonic() < deadline
                and not never_retry(code_of(_json_body(response))))

    def delay(self, attempt: int, response: httpx.Response | None) -> float:
        retry_after = _retry_after(response) if response is not None else None
        if retry_after is not None:
            return min(retry_after, 60.0)
        return min(0.5 * (2 ** attempt) + random.uniform(0, 0.25), 20.0)

    def decode(self, request: _Request, response: httpx.Response) -> Any:
        if response.status_code >= 400:
            try:
                body = response.json()
            except ValueError:
                body = {"detail": response.text[:500]}
            raise error_for(response.status_code, body, request_id=response.headers.get("X-Request-ID"),
                            retry_after=_retry_after(response))
        if request.raw:
            return response.content
        if response.status_code == 204 or not response.content:
            return None
        try:
            data = response.json()
        except ValueError:
            raise ScrawlError("The API returned a response that is not JSON", status=response.status_code,
                              request_id=response.headers.get("X-Request-ID")) from None
        return _check_engine(request, wrap(data))


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    try:
        return max(0.0, float(value)) if value is not None else None
    except ValueError:
        return None


def _items(page: Any) -> list[Any]:
    for key in _LIST_KEYS:
        value = page.get(key) if isinstance(page, dict) else None
        if isinstance(value, list):
            return value
    return []


class Scrawl(_Endpoints):
    """Synchronous Scrawl client. ``with Scrawl() as client: client.scrape("https://example.com")``."""

    def __init__(self, api_key: str | None = None, *, base_url: str | None = None, timeout: float = 90.0,
                 max_retries: int = 2, http_client: httpx.Client | None = None,
                 allow_insecure_http: bool | None = None) -> None:
        self._t = _Transport(api_key, base_url, timeout, max_retries, allow_insecure_http)
        self._http = http_client or httpx.Client(timeout=timeout)
        self.base_url = self._t.base_url

    def __enter__(self) -> Scrawl:
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close the connection pool."""
        self._http.close()

    def _call(self, request: _Request) -> Any:
        attempt = 0
        replay_deadline = self._t.replay_deadline(request)
        while True:
            response = None
            headers = self._t.headers(request)
            try:
                response = self._http.request(request.method, self._t.base_url + request.path,
                                              params=request.params or None, json=request.json, headers=headers)
            except httpx.HTTPError as exc:
                error: ScrawlError | None = self._t.failure(exc)
            else:
                if self._t.waits_for_replay(request, response, replay_deadline):
                    time.sleep(max(1.0, self._t.delay(0, response)))
                    attempt += 1
                    continue
                if not (self._t.retryable(request) and attempt < self._t.max_retries
                        and self._t.retry_response(request, response)):
                    return self._t.decode(request, response)
                error = None
            if error is not None and not (self._t.retryable(request) and attempt < self._t.max_retries):
                raise error
            time.sleep(self._t.delay(attempt, response))
            attempt += 1

    def wait_for_scrape(self, job_id: str, *, timeout: float = 300.0, engine: str | None = None) -> ScrawlObject:
        """Block until a pending scrape settles (server-side waits, no tight polling); ENGINE as for scrape_result."""
        deadline = time.monotonic() + timeout
        while True:
            result = self.scrape_result(job_id, wait_seconds=int(min(60, max(1, deadline - time.monotonic()))),
                                        engine=engine)
            if result.status != "pending" or time.monotonic() >= deadline:
                return result

    def wait_for_batch(self, batch_id: str, *, timeout: float = 600.0) -> ScrawlObject:
        """Block until every item of a batch has settled (or TIMEOUT)."""
        deadline = time.monotonic() + timeout
        while True:
            status = self.batch_status(batch_id, wait_seconds=int(min(60, max(1, deadline - time.monotonic()))))
            if status.status == "completed" or time.monotonic() >= deadline:
                return status

    def wait_for_assets(self, job_id: str, *, timeout: float = 600.0) -> ScrawlObject:
        """Block until an asset job settles: completed, failed, cancelled or orphaned (or the timeout)."""
        deadline = time.monotonic() + timeout
        while True:
            result = self.get_assets(job_id, wait_seconds=int(min(60, max(1, deadline - time.monotonic()))))
            if result.status not in _ASSETS_ACTIVE or time.monotonic() >= deadline:
                return result

    def wait_for_job(self, job_id: str, *, timeout: float = 1800.0) -> ScrawlObject:
        """Block until a job (a crawl, a dataset extraction...) leaves PENDING/RUNNING (or the timeout)."""
        deadline = time.monotonic() + timeout
        while True:
            job = self.get_job(job_id, wait_seconds=int(min(60, max(1, deadline - time.monotonic()))))
            if str(job.status).upper() not in _JOBS_ACTIVE or time.monotonic() >= deadline:
                return job

    def paginate(self, method: Any, *args: Any, **kwargs: Any) -> Iterator[Any]:
        """Iterate every item of a cursor-paged list method: ``client.paginate(client.list_datasets)``."""
        cursor = kwargs.pop("cursor", None)
        while True:
            page = method(*args, cursor=cursor, **kwargs)
            yield from _items(page)
            cursor = page.get("next_cursor")
            if not cursor:
                return


class AsyncScrawl(_Endpoints):
    """Asynchronous Scrawl client. ``async with AsyncScrawl() as client: await client.scrape(url)``."""

    def __init__(self, api_key: str | None = None, *, base_url: str | None = None, timeout: float = 90.0,
                 max_retries: int = 2, http_client: httpx.AsyncClient | None = None,
                 allow_insecure_http: bool | None = None) -> None:
        self._t = _Transport(api_key, base_url, timeout, max_retries, allow_insecure_http)
        self._http = http_client or httpx.AsyncClient(timeout=timeout)
        self.base_url = self._t.base_url

    async def __aenter__(self) -> AsyncScrawl:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the connection pool."""
        await self._http.aclose()

    async def _call(self, request: _Request) -> Any:  # type: ignore[override]
        attempt = 0
        replay_deadline = self._t.replay_deadline(request)
        while True:
            response = None
            headers = self._t.headers(request)
            try:
                response = await self._http.request(request.method, self._t.base_url + request.path,
                                                    params=request.params or None, json=request.json,
                                                    headers=headers)
            except httpx.HTTPError as exc:
                error: ScrawlError | None = self._t.failure(exc)
            else:
                if self._t.waits_for_replay(request, response, replay_deadline):
                    await asyncio.sleep(max(1.0, self._t.delay(0, response)))
                    attempt += 1
                    continue
                if not (self._t.retryable(request) and attempt < self._t.max_retries
                        and self._t.retry_response(request, response)):
                    return self._t.decode(request, response)
                error = None
            if error is not None and not (self._t.retryable(request) and attempt < self._t.max_retries):
                raise error
            await asyncio.sleep(self._t.delay(attempt, response))
            attempt += 1

    async def wait_for_scrape(self, job_id: str, *, timeout: float = 300.0,
                              engine: str | None = None) -> ScrawlObject:
        """Wait until a pending scrape settles (server-side waits); ENGINE as for scrape_result."""
        deadline = time.monotonic() + timeout
        while True:
            result = await self.scrape_result(job_id, wait_seconds=int(min(60, max(1, deadline - time.monotonic()))),
                                              engine=engine)
            if result.status != "pending" or time.monotonic() >= deadline:
                return result

    async def wait_for_batch(self, batch_id: str, *, timeout: float = 600.0) -> ScrawlObject:
        """Wait until every item of a batch has settled (or TIMEOUT)."""
        deadline = time.monotonic() + timeout
        while True:
            status = await self.batch_status(batch_id, wait_seconds=int(min(60, max(1, deadline - time.monotonic()))))
            if status.status == "completed" or time.monotonic() >= deadline:
                return status

    async def wait_for_assets(self, job_id: str, *, timeout: float = 600.0) -> ScrawlObject:
        """Wait until an asset job settles: completed, failed, cancelled or orphaned (or the timeout)."""
        deadline = time.monotonic() + timeout
        while True:
            result = await self.get_assets(job_id, wait_seconds=int(min(60, max(1, deadline - time.monotonic()))))
            if result.status not in _ASSETS_ACTIVE or time.monotonic() >= deadline:
                return result

    async def wait_for_job(self, job_id: str, *, timeout: float = 1800.0) -> ScrawlObject:
        """Wait until a job (a crawl, a dataset extraction...) leaves PENDING/RUNNING (or the timeout)."""
        deadline = time.monotonic() + timeout
        while True:
            job = await self.get_job(job_id, wait_seconds=int(min(60, max(1, deadline - time.monotonic()))))
            if str(job.status).upper() not in _JOBS_ACTIVE or time.monotonic() >= deadline:
                return job

    async def paginate(self, method: Any, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        """Iterate every item of a cursor-paged list method."""
        cursor = kwargs.pop("cursor", None)
        while True:
            page = await method(*args, cursor=cursor, **kwargs)
            for item in _items(page):
                yield item
            cursor = page.get("next_cursor")
            if not cursor:
                return
