"""``local_fetch`` and ``scrape_local`` (ADR C-8 D2): the page is fetched from the customer's own machine with its own
client, robots.txt honoured by default, at most 5 redirects, the size limit before upload; then Scrawl renders it."""

from __future__ import annotations

import base64
import json

import httpx
import pytest
from scrawl import AsyncScrawl, Scrawl, ScrawlError

PAGE = b"<html><head><title>Members</title></head><body><p>12.50</p></body></html>"


def _site(robots: str | None = "User-agent: *\nDisallow: /private/\n", pages: dict | None = None):  # type: ignore[no-untyped-def]
    """A site: robots.txt (None: 404) and PAGES (path -> response); every request it saw."""
    seen: list[httpx.Request] = []
    pages = pages or {"/lamp": httpx.Response(200, content=PAGE, headers={"content-type": "text/html"})}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(404) if robots is None else httpx.Response(200, text=robots)
        return pages.get(request.url.path, httpx.Response(404))

    return seen, httpx.MockTransport(handler)


def _api():  # type: ignore[no-untyped-def]
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = json.loads(request.content)
        return httpx.Response(200, json={"job_id": "j1", "status": "completed", "url": body["url"],
                                         "markdown": "12.50", "origin": "client_fetched", "url_verified": False})

    return calls, Scrawl("sk-test", base_url="https://scrawl.test", http_client=httpx.Client(
        transport=httpx.MockTransport(handler)))


def test_local_fetch_fetches_with_its_own_client_and_submits_the_body_without_the_api_key() -> None:
    seen, site = _site()
    calls, client = _api()
    result = client.local_fetch("https://members.example/lamp", fetch_client=httpx.Client(transport=site),
                                formats=["markdown"])
    assert result.origin == "client_fetched" and result.url_verified is False
    assert [request.url.path for request in seen] == ["/robots.txt", "/lamp"]
    assert all("authorization" not in request.headers for request in seen)        # the key never goes to the site
    assert all(request.headers["user-agent"].startswith("ScrawlSDK/") for request in seen)
    [submit] = calls
    payload = json.loads(submit.content)
    assert submit.url.path == "/v1/scrape/local" and submit.headers["authorization"] == "Bearer sk-test"
    assert base64.b64decode(payload["body_base64"]) == PAGE and payload["content_type"] == "text/html"
    assert payload["http_status"] == 200 and payload["formats"] == ["markdown"] and "final_url" not in payload


def test_robots_txt_is_honoured_by_default_and_the_opt_out_is_explicit() -> None:
    pages = {"/private/report": httpx.Response(200, content=PAGE, headers={"content-type": "text/html"})}
    seen, site = _site(pages=pages)
    calls, client = _api()
    with pytest.raises(ScrawlError) as refused:
        client.local_fetch("https://members.example/private/report", fetch_client=httpx.Client(transport=site))
    assert refused.value.code == "robots_disallowed" and calls == []
    assert [request.url.path for request in seen] == ["/robots.txt"]                # the page was never fetched
    client.local_fetch("https://members.example/private/report", fetch_client=httpx.Client(transport=site),
                       respect_robots=False)
    assert len(calls) == 1


def test_an_unavailable_robots_txt_refuses_and_a_missing_one_allows() -> None:
    _seen, broken = _site(robots=None)
    calls, client = _api()
    client.local_fetch("https://members.example/lamp", fetch_client=httpx.Client(transport=broken))
    assert len(calls) == 1

    def down(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503) if request.url.path == "/robots.txt" else httpx.Response(200, content=PAGE)

    with pytest.raises(ScrawlError) as refused:
        client.local_fetch("https://members.example/lamp", fetch_client=httpx.Client(transport=httpx.MockTransport(down)))
    assert refused.value.code == "robots_unavailable" and len(calls) == 1


def test_redirects_are_followed_at_most_five_times_and_each_hop_is_checked() -> None:
    hops = {f"/r{index}": httpx.Response(302, headers={"location": f"/r{index + 1}"}) for index in range(6)}
    hops["/r6"] = httpx.Response(200, content=PAGE, headers={"content-type": "text/html"})
    _seen, site = _site(pages=hops)
    calls, client = _api()
    with pytest.raises(ScrawlError) as looped:
        client.local_fetch("https://members.example/r0", fetch_client=httpx.Client(transport=site))
    assert looped.value.code == "too_many_redirects" and calls == []
    client.local_fetch("https://members.example/r1", fetch_client=httpx.Client(transport=site))  # five redirects
    assert json.loads(calls[-1].content)["final_url"] == "https://members.example/r6"
    to_private = {"/go": httpx.Response(301, headers={"location": "/private/x"}),
                  "/private/x": httpx.Response(200, content=PAGE)}
    _seen, guarded = _site(pages=to_private)
    with pytest.raises(ScrawlError) as refused:
        client.local_fetch("https://members.example/go", fetch_client=httpx.Client(transport=guarded))
    assert refused.value.code == "robots_disallowed"


def test_a_body_over_the_limit_is_never_sent() -> None:
    big = {"/big": httpx.Response(200, content=b"x" * 2048, headers={"content-type": "text/html"})}
    _seen, site = _site(pages=big)
    calls, client = _api()
    with pytest.raises(ScrawlError) as refused:
        client.local_fetch("https://members.example/big", fetch_client=httpx.Client(transport=site), max_bytes=1024)
    assert refused.value.code == "payload_too_large" and calls == []


@pytest.mark.asyncio
async def test_the_async_client_does_the_same() -> None:
    seen, site = _site()
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"job_id": "j1", "status": "completed", "url": "u"})

    async with AsyncScrawl("sk-test", base_url="https://scrawl.test",
                           http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler))) as client:
        await client.local_fetch("https://members.example/lamp", fetch_client=httpx.AsyncClient(transport=site))
    assert [request.url.path for request in seen] == ["/robots.txt", "/lamp"] and len(sent) == 1
    assert base64.b64decode(json.loads(sent[0].content)["body_base64"]) == PAGE


#: RFC 9309 vectors, the same in the TypeScript SDK's test (``local-fetch.test.js``): robots.txt, path, allowed.
ROBOTS_VECTORS = [
    ("User-agent: *\nAllow: /\nDisallow: /private\n", "/private", False),       # the longest match, not the first
    ("User-agent: *\nAllow: /\nDisallow: /private\n", "/", True),
    ("User-agent: *\nDisallow: /*.pdf$\n", "/doc.pdf", False),                   # * and $
    ("User-agent: *\nDisallow: /*.pdf$\n", "/doc.pdf?x=1", True),
    ("User-agent: *\nDisallow: /*.pdf$\n", "/doc.pdfs", True),
    ("User-agent: *\nDisallow: /a\nAllow: /a/public\n", "/a/public", True),
    ("User-agent: *\nDisallow: /a\nAllow: /a/public\n", "/a/b", False),
    ("User-agent: *\nDisallow: /t\nAllow: /t\n", "/t", True),                    # Allow wins a tie
    ("User-agent: sdk\nDisallow: /\n\nUser-agent: *\nAllow: /\n", "/x", True),   # a token, not a substring
    ("User-agent:\nDisallow: /\n\nUser-agent: *\nDisallow: /p\n", "/x", True),   # an empty agent is nobody
    ("User-agent: ScrawlSDK\nDisallow: /x\n\nUser-agent: *\nDisallow: /\n", "/x", False),
    ("User-agent: ScrawlSDK\nDisallow: /x\n\nUser-agent: *\nDisallow: /\n", "/y", True),   # our group only
    ("User-agent: scrawlsdk\nUser-agent: other\nDisallow: /both\n", "/both", False),       # a group of agents
    ("User-agent: other\nDisallow: /\n", "/x", True),                            # no group for us or *
]


@pytest.mark.parametrize(("robots", "path", "allowed"), ROBOTS_VECTORS)
def test_robots_txt_is_matched_as_rfc_9309_says(robots: str, path: str, allowed: bool) -> None:
    from scrawl._local_fetch import parse_robots, robots_allow

    assert robots_allow(parse_robots(robots), "https://members.example" + path) is allowed


def test_a_redirect_to_another_host_is_not_followed_with_your_own_client() -> None:
    """Your client may carry credentials (auth, cookies, default headers) for the site you asked for: a hop to another
    host is refused, never sent through it. A downgrade from https to http is refused always."""
    pages = {"/go": httpx.Response(302, headers={"location": "https://elsewhere.example/x"}),
             "/down": httpx.Response(301, headers={"location": "http://members.example/lamp"})}
    seen, site = _site(pages=pages)
    calls, client = _api()
    with pytest.raises(ScrawlError) as away:
        client.local_fetch("https://members.example/go", fetch_client=httpx.Client(transport=site))
    assert away.value.code == "cross_origin_redirect" and "elsewhere.example" in str(away.value)
    assert all(request.url.host == "members.example" for request in seen) and calls == []
    with pytest.raises(ScrawlError) as down:
        client.local_fetch("https://members.example/down", fetch_client=httpx.Client(transport=site))
    assert down.value.code == "insecure_redirect" and calls == []


def test_an_upgrade_to_https_on_the_same_host_is_followed() -> None:
    pages = {"/up": httpx.Response(301, headers={"location": "https://members.example/lamp"}),
             "/lamp": httpx.Response(200, content=PAGE, headers={"content-type": "text/html"})}
    _seen, site = _site(pages=pages)
    calls, client = _api()
    client.local_fetch("http://members.example/up", fetch_client=httpx.Client(transport=site))
    assert json.loads(calls[-1].content)["final_url"] == "https://members.example/lamp"


def test_robots_compares_paths_after_rfc_9309_percent_encoding_normalisation() -> None:
    """SCCLD1 fixes-5 item 4 (TC-17): ``Disallow: /private/`` also covers ``/%70rivate/`` (an encoded unreserved
    octet is decoded before comparing); non-ASCII is percent-encoded and hex case does not matter; an encoded
    reserved octet (``%2F``) is not the character it encodes."""
    from scrawl._local_fetch import parse_robots, robots_allow

    rules = parse_robots("User-agent: *\nDisallow: /private/\nDisallow: /caf%C3%A9\nDisallow: /%7Euser\n"
                         "Disallow: /a/b\n")
    for blocked in ("/%70rivate/x", "/private/x", "/%70%72ivate/", "/café", "/caf%c3%a9", "/~user/page",
                    "/%7euser"):
        assert robots_allow(rules, "https://e.example" + blocked) is False, blocked
    for allowed in ("/a%2Fb", "/public", "/%2570rivate/"):              # %2F stays a different octet; %25 is '%'
        assert robots_allow(rules, "https://e.example" + allowed) is True, allowed


def test_robots_compares_the_path_the_client_will_send() -> None:
    """fixes-5 review: characters a client percent-encodes on the wire (a space, braces, quotes, angle brackets, a
    backslash, ^, `, |) are compared encoded, whichever side wrote them raw; dot segments are removed first, as the
    HTTP client removes them. The TypeScript SDK decides the same."""
    from scrawl._local_fetch import parse_robots, robots_allow

    rules = parse_robots("User-agent: *\nDisallow: /My%20Documents/\nDisallow: /%7Bt%7D\nDisallow: /raw space/\n"
                         "Disallow: /a|b\n")
    for blocked in ("/My Documents/f", "/My%20Documents/f", "/{t}", "/%7bt%7d", "/raw%20space/x", "/raw space/x",
                    "/a/../My%20Documents/f", "/x/./../My Documents/f", "/a%7Cb", "/a|b"):
        assert robots_allow(rules, "https://e.example" + blocked) is False, blocked
    for allowed in ("/My-Documents/f", "/t", "/a/b", "/My%2520Documents/"):
        assert robots_allow(rules, "https://e.example" + allowed) is True, allowed


def test_the_module_says_how_robots_paths_are_compared() -> None:
    """SCCLD1 fixes-6 item 4 (TC-23): fixes-5 normalises percent-encoding (RFC 9309) and removes dot segments, but
    the module's documentation still said percent-encoding was not normalised."""
    from scrawl import _local_fetch

    doc = " ".join((_local_fetch.__doc__ or "").split())
    assert "not normalised" not in doc, doc
    assert "percent-encoding normalised" in doc and "dot segments removed" in doc, doc


# -- the review of kits 0.1.5 (DeepSeek ds-xg73yq and passes): robots redirects, bounds, errors, uploads ------------

def _robots_redirect_site(location: str):  # type: ignore[no-untyped-def]
    """A site whose robots.txt redirects to LOCATION; the page itself is fine."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/robots.txt" and request.url.host == "members.example":
            return httpx.Response(301, headers={"location": location})
        if request.url.path in ("/robots.txt", "/moved-robots.txt"):
            return httpx.Response(200, text="User-agent: *\nDisallow: /private/\n")
        return httpx.Response(200, content=PAGE, headers={"content-type": "text/html"})

    return seen, httpx.MockTransport(handler)


@pytest.mark.parametrize(("location", "code"), [("http://members.example/robots.txt", "insecure_redirect"),
                                                ("https://other.example/robots.txt", "cross_origin_redirect")])
def test_robots_txt_redirects_get_the_same_checks_as_every_page_hop(location: str, code: str) -> None:
    seen, site = _robots_redirect_site(location)
    calls, client = _api()
    with pytest.raises(ScrawlError) as refused:
        client.local_fetch("https://members.example/lamp", fetch_client=httpx.Client(transport=site))
    assert refused.value.code == code and calls == []
    assert [str(request.url) for request in seen] == ["https://members.example/robots.txt"]   # the hop never made


def test_a_robots_txt_redirect_on_the_same_host_is_followed_and_its_rules_apply() -> None:
    seen, site = _robots_redirect_site("/moved-robots.txt")
    calls, client = _api()
    with pytest.raises(ScrawlError) as refused:
        client.local_fetch("https://members.example/private/x", fetch_client=httpx.Client(transport=site))
    assert refused.value.code == "robots_disallowed" and calls == []
    assert [request.url.path for request in seen] == ["/robots.txt", "/moved-robots.txt"]


def test_robots_txt_is_read_up_to_500_kib_only() -> None:
    padding = "# " + "x" * 1022 + "\n"
    robots = "User-agent: *\n" + padding * 600 + "Disallow: /lamp\n"         # the rule sits past 500 KiB
    _seen, site = _site(robots=robots)
    calls, client = _api()
    client.local_fetch("https://members.example/lamp", fetch_client=httpx.Client(transport=site))
    assert len(calls) == 1                                                  # past the limit: ignored (RFC 9309 2.5)


@pytest.mark.parametrize(("failure", "code"), [(httpx.ConnectError("refused"), "fetch_failed"),
                                               (httpx.ReadTimeout("slow"), "fetch_timeout")])
def test_a_network_failure_of_the_fetch_is_a_scrawl_error(failure: Exception, code: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise failure

    calls, client = _api()
    with pytest.raises(ScrawlError) as failed:
        client.local_fetch("https://members.example/lamp", fetch_client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert failed.value.code == code and calls == []


def test_robots_wildcards_match_in_bounded_time() -> None:
    import time

    from scrawl._local_fetch import RobotsRule, robots_allow

    rules = [RobotsRule(False, "/" + "*a" * 40 + "b")]
    started = time.monotonic()
    assert robots_allow(rules, "https://members.example/" + "a" * 5000) is True
    assert robots_allow(rules, "https://members.example/" + "a" * 50 + "b") is False
    assert time.monotonic() - started < 2.0


def test_an_empty_page_is_refused_before_anything_is_sent() -> None:
    _seen, site = _site(pages={"/lamp": httpx.Response(204)})
    calls, client = _api()
    with pytest.raises(ScrawlError) as refused:
        client.local_fetch("https://members.example/lamp", fetch_client=httpx.Client(transport=site))
    assert refused.value.code == "empty_body" and calls == []


def test_an_overlong_content_type_is_sent_as_its_media_type() -> None:
    long_type = "text/html; " + "; ".join(f"p{index}=v" for index in range(60))
    _seen, site = _site(pages={"/lamp": httpx.Response(200, content=PAGE, headers={"content-type": long_type})})
    calls, client = _api()
    client.local_fetch("https://members.example/lamp", fetch_client=httpx.Client(transport=site))
    assert json.loads(calls[0].content)["content_type"] == "text/html"
