"""Fetch a page from your own machine, then have Scrawl render it (``local_fetch``).

The page is fetched with your own HTTP client, from your machine and your address; Scrawl receives the body and makes no
connection to the site. By default the site's robots.txt is read and honoured first (``respect_robots=False`` turns
this off; whether you may fetch a page without it is then your responsibility). At most ``max_redirects`` redirects are
followed, each checked against robots.txt again, and the body is read only up to the size limit Scrawl accepts.
robots.txt is matched as RFC 9309 says: the group for our product token (``ScrawlSDK``, case-insensitive), else
``*``; the longest matching rule wins, Allow on a tie; ``*`` and a final ``$`` in a rule. Rules and paths are
compared with percent-encoding normalised (an encoded unreserved character is decoded; an encoded reserved one, such
as ``%2F``, stays encoded) and dot segments removed.

The fetch never carries your Scrawl API key: it uses its own client, never the one that talks to Scrawl. A redirect
from https to http is never followed. When you pass your own client (it may carry credentials for the site you
asked for), a redirect to another host is not followed either: fetch that address yourself if you mean to. The
robots.txt request gets the same redirect checks as the page, and at most 500 KiB of it is read (RFC 9309 section
2.5). A failure to reach the site is a ``ScrawlError`` (``fetch_failed``, or ``fetch_timeout``); an empty page is
refused (``empty_body``) before anything is sent to Scrawl.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from ._errors import ScrawlError
from ._version import __version__

#: The user agent the fetch identifies itself with (robots.txt rules for it, or for *, apply).
USER_AGENT = f"ScrawlSDK/{__version__} (+local_fetch)"
ROBOTS_AGENT = "ScrawlSDK"
_ROBOTS_TOKEN = ROBOTS_AGENT.lower()
DEFAULT_MAX_REDIRECTS = 5
#: Scrawl accepts a page of at most 5 MiB (a document may be larger on some deployments: pass max_bytes).
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
_REDIRECTS = {301, 302, 303, 307, 308}
#: How much of a robots.txt is read; the rest is ignored (RFC 9309 section 2.5: at least 500 kibibytes).
ROBOTS_MAX_BYTES = 500 * 1024
#: The longest Content-Type Scrawl accepts; a longer one is sent as its media type alone.
MAX_CONTENT_TYPE = 200


@dataclass(frozen=True)
class Fetched:
    """What your client received: the final URL, status, Content-Type and body."""

    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes


def _refuse(code: str, message: str) -> ScrawlError:
    return ScrawlError(message, code=code)


def _check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise _refuse("invalid_request", f"local_fetch needs an absolute http(s) URL, not {url!r}")


def _robots_url(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}/robots.txt"


@dataclass(frozen=True)
class RobotsRule:
    """One Allow or Disallow line of the group that applies to us."""

    allow: bool
    pattern: str


def parse_robots(text: str) -> list[RobotsRule]:
    """The rules of a robots.txt body that apply to us: every group naming our product token, else every ``*``
    group (RFC 9309 section 2.2.1); no rule allows everything."""
    groups: list[tuple[list[str], list[RobotsRule]]] = []
    agents: list[str] | None = None
    rules: list[RobotsRule] = []
    last_was_agent = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        key, colon, value = line.partition(":")
        if not colon:
            continue
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if not last_was_agent or agents is None:
                agents, rules = [], []
                groups.append((agents, rules))
            agents.append(value.lower())
            last_was_agent = True
        elif key in ("allow", "disallow"):
            if agents is not None and value:
                rules.append(RobotsRule(key == "allow", _normalise(value)))
            last_was_agent = False
        else:
            last_was_agent = False
    ours = [rules for agents, rules in groups if _ROBOTS_TOKEN in agents]
    chosen = ours or [rules for agents, rules in groups if "*" in agents]
    return [rule for rules in chosen for rule in rules]


_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_HEX = frozenset("0123456789abcdefABCDEF")
#: RFC 3986 reserved characters: kept as they are (an encoded one stays encoded).
_RESERVED = frozenset(":/?#[]@!$&'()*+,;=")


def _normalise(text: str) -> str:
    """TEXT as RFC 9309 (section 2.2.2) compares it: an encoded unreserved octet is decoded, every other encoding is
    kept (upper-case hex), and a character that is neither unreserved nor reserved (non-ASCII, a space, ``"<>\\^`{|}``,
    a control character) is percent-encoded (UTF-8), as the HTTP client sends it. An encoded reserved octet such as
    ``%2F`` stays a different octet from the character it encodes."""
    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        digits = text[index + 1:index + 3]
        if char == "%" and len(digits) == 2 and all(digit in _HEX for digit in digits):
            decoded = chr(int(digits, 16))
            out.append(decoded if decoded in _UNRESERVED else "%" + digits.upper())
            index += 3
            continue
        out.append(char if char in _UNRESERVED or char in _RESERVED or char == "%"
                   else "".join(f"%{byte:02X}" for byte in char.encode("utf-8")))
        index += 1
    return "".join(out)


def _without_dot_segments(path: str) -> str:
    """PATH with its ``.`` and ``..`` segments removed (RFC 3986 section 5.2.4), as the HTTP client sends it."""
    output: list[str] = []
    segments = path.split("/")
    for index, segment in enumerate(segments):
        last = index == len(segments) - 1
        if segment == ".":
            if last:
                output.append("")
        elif segment == "..":
            if len(output) > 1:
                output.pop()
            if last:
                output.append("")
        else:
            output.append(segment)
    joined = "/".join(output)
    return joined if joined.startswith("/") or not path.startswith("/") else "/" + joined


def _glob(pattern: str, text: str) -> bool:
    """Whether all of TEXT matches PATTERN, where ``*`` matches any run of characters. Greedy, going back only to
    the last ``*``: at most len(PATTERN) x len(TEXT) steps, whatever the rule (no regular expression to backtrack)."""
    p = t = 0
    star, mark = -1, 0
    while t < len(text):
        if p < len(pattern) and pattern[p] == "*":
            star, mark = p, t
            p += 1
        elif p < len(pattern) and pattern[p] == text[t]:
            p += 1
            t += 1
        elif star >= 0:
            p, mark = star + 1, mark + 1
            t = mark
        else:
            return False
    while p < len(pattern) and pattern[p] == "*":
        p += 1
    return p == len(pattern)


def _matches(pattern: str, path: str) -> bool:
    """A rule matches a path from its start; a final ``$`` makes it match the whole path."""
    anchored = pattern.endswith("$")
    return _glob(pattern[:-1] if anchored else pattern + "*", path)


def robots_allow(rules: list[RobotsRule], url: str) -> bool:
    """Whether RULES allow URL: the longest matching rule wins, Allow on a tie; no matching rule allows."""
    parts = urlsplit(url)
    path = _without_dot_segments(_normalise(parts.path or "/")) + (f"?{_normalise(parts.query)}" if parts.query else "")
    best: RobotsRule | None = None
    for rule in rules:
        if not _matches(rule.pattern, path):
            continue
        if best is None or len(rule.pattern) > len(best.pattern) \
                or (len(rule.pattern) == len(best.pattern) and rule.allow):
            best = rule
    return best is None or best.allow


def _parser(status: int, text: str) -> list[RobotsRule] | None:
    """The rules from a robots.txt answer; None means everything is allowed (no robots.txt)."""
    if status >= 500 or status == 429:
        raise _refuse("robots_unavailable", f"robots.txt answered {status}: not fetched (pass respect_robots=False "
                                            "to fetch anyway, at your own responsibility)")
    if status >= 400:
        return None
    return parse_robots(text)


def _allowed(rules: list[RobotsRule] | None, url: str) -> bool:
    return rules is None or robots_allow(rules, url)


def _host(url: str) -> tuple[str, int]:
    parts = urlsplit(url)
    return (parts.hostname or "").lower(), parts.port or (443 if parts.scheme == "https" else 80)


def _next_hop(current: str, location: str, same_host_only: bool) -> str:
    """Where a redirect from CURRENT to LOCATION leads, or a refusal: not http(s), a downgrade from https, or (with
    your own client) another host. An upgrade to https on the same host is the same host."""
    target = urljoin(current, location)
    _check_url(target)
    if urlsplit(current).scheme == "https" and urlsplit(target).scheme == "http":
        raise _refuse("insecure_redirect", f"{current} redirects to {target}, from https to http: not followed")
    here, there = _host(current), _host(target)
    upgrade = urlsplit(current).scheme == "http" and urlsplit(target).scheme == "https" and here[0] == there[0] \
        and here[1] == 80 and there[1] == 443
    if same_host_only and here != there and not upgrade:
        raise _refuse("cross_origin_redirect", f"{current} redirects to another host ({target}): not followed with "
                                               "your own client, which may carry credentials for the site you asked "
                                               "for; fetch that address directly if you mean to")
    return target


def _unreachable(url: str, exc: httpx.HTTPError) -> ScrawlError:
    if isinstance(exc, httpx.TimeoutException):
        return _refuse("fetch_timeout", f"{url} did not answer in time: not fetched")
    return _refuse("fetch_failed", f"Could not fetch {url} ({type(exc).__name__}): not fetched")


def _content_type(value: str) -> str:
    """VALUE, or only its media type when it is longer than Scrawl accepts."""
    return value if len(value) <= MAX_CONTENT_TYPE else value.split(";", 1)[0].strip()[:MAX_CONTENT_TYPE]


def _page(url: str, current: str, status: int, content_type: str, body: bytes) -> Fetched:
    if not body:
        raise _refuse("empty_body", f"{current} answered {status} with no body: nothing to render, nothing sent")
    return Fetched(url, current, status, _content_type(content_type), body)


def _robots_text(chunks: bytes) -> str:
    return chunks[:ROBOTS_MAX_BYTES].decode("utf-8", errors="replace")


def _disallowed(url: str) -> ScrawlError:
    return _refuse("robots_disallowed", f"robots.txt disallows {url}: not fetched (pass respect_robots=False to fetch "
                                        "anyway, at your own responsibility)")


def _too_large(max_bytes: int) -> ScrawlError:
    return _refuse("payload_too_large", f"The page is larger than {max_bytes} bytes: not sent")


def fetch(client: httpx.Client, url: str, *, respect_robots: bool = True,
          max_redirects: int = DEFAULT_MAX_REDIRECTS, max_bytes: int = DEFAULT_MAX_BYTES,
          same_host_only: bool = False) -> Fetched:
    """Fetch URL with CLIENT (synchronously), honouring robots.txt, at most MAX_REDIRECTS, at most MAX_BYTES; with
    SAME_HOST_ONLY (your own client) no redirect to another host."""
    _check_url(url)
    rules: dict[str, list[RobotsRule] | None] = {}
    current = url
    try:
        for _hop in range(max_redirects + 1):
            if respect_robots:
                origin = _robots_url(current)
                if origin not in rules:
                    rules[origin] = _read_robots(client, origin, same_host_only)
                if not _allowed(rules[origin], current):
                    raise _disallowed(current)
            with client.stream("GET", current, headers={"User-Agent": USER_AGENT}, follow_redirects=False) as response:
                if response.status_code in _REDIRECTS and response.headers.get("location"):
                    current = _next_hop(current, response.headers["location"], same_host_only)
                    continue
                body = bytearray()
                for chunk in response.iter_bytes():
                    body += chunk
                    if len(body) > max_bytes:
                        raise _too_large(max_bytes)
                return _page(url, current, response.status_code, response.headers.get("content-type", ""), bytes(body))
    except httpx.HTTPError as exc:
        raise _unreachable(current, exc) from None
    raise _refuse("too_many_redirects", f"More than {max_redirects} redirects from {url}: not fetched")


def _read_robots(client: httpx.Client, origin: str, same_host_only: bool) -> list[RobotsRule] | None:
    """ORIGIN's robots.txt rules, its redirects checked as a page's are (at most five), at most 500 KiB read."""
    current = origin
    for _hop in range(DEFAULT_MAX_REDIRECTS + 1):
        with client.stream("GET", current, headers={"User-Agent": USER_AGENT}, follow_redirects=False) as answer:
            if answer.status_code in _REDIRECTS and answer.headers.get("location"):
                current = _next_hop(current, answer.headers["location"], same_host_only)
                continue
            body = bytearray()
            for chunk in answer.iter_bytes():
                body += chunk
                if len(body) >= ROBOTS_MAX_BYTES:
                    break
            return _parser(answer.status_code, _robots_text(bytes(body)))
    raise _refuse("robots_unavailable", f"robots.txt at {origin} redirects more than {DEFAULT_MAX_REDIRECTS} times: "
                                        "not fetched (pass respect_robots=False to fetch anyway)")


async def afetch(client: httpx.AsyncClient, url: str, *, respect_robots: bool = True,
                 max_redirects: int = DEFAULT_MAX_REDIRECTS, max_bytes: int = DEFAULT_MAX_BYTES,
                 same_host_only: bool = False) -> Fetched:
    """``fetch``, with an async CLIENT."""
    _check_url(url)
    rules: dict[str, list[RobotsRule] | None] = {}
    current = url
    try:
        for _hop in range(max_redirects + 1):
            if respect_robots:
                origin = _robots_url(current)
                if origin not in rules:
                    rules[origin] = await _aread_robots(client, origin, same_host_only)
                if not _allowed(rules[origin], current):
                    raise _disallowed(current)
            async with client.stream("GET", current, headers={"User-Agent": USER_AGENT},
                                     follow_redirects=False) as response:
                if response.status_code in _REDIRECTS and response.headers.get("location"):
                    current = _next_hop(current, response.headers["location"], same_host_only)
                    continue
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body += chunk
                    if len(body) > max_bytes:
                        raise _too_large(max_bytes)
                return _page(url, current, response.status_code, response.headers.get("content-type", ""), bytes(body))
    except httpx.HTTPError as exc:
        raise _unreachable(current, exc) from None
    raise _refuse("too_many_redirects", f"More than {max_redirects} redirects from {url}: not fetched")


async def _aread_robots(client: httpx.AsyncClient, origin: str, same_host_only: bool) -> list[RobotsRule] | None:
    """``_read_robots``, with an async CLIENT."""
    current = origin
    for _hop in range(DEFAULT_MAX_REDIRECTS + 1):
        async with client.stream("GET", current, headers={"User-Agent": USER_AGENT}, follow_redirects=False) as answer:
            if answer.status_code in _REDIRECTS and answer.headers.get("location"):
                current = _next_hop(current, answer.headers["location"], same_host_only)
                continue
            body = bytearray()
            async for chunk in answer.aiter_bytes():
                body += chunk
                if len(body) >= ROBOTS_MAX_BYTES:
                    break
            return _parser(answer.status_code, _robots_text(bytes(body)))
    raise _refuse("robots_unavailable", f"robots.txt at {origin} redirects more than {DEFAULT_MAX_REDIRECTS} times: "
                                        "not fetched (pass respect_robots=False to fetch anyway)")
