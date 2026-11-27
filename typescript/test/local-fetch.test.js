import assert from "node:assert/strict";
import { test } from "node:test";

import { parseRobots, robotsAllow } from "../src/local_fetch.js";
import { makeClient } from "./helpers.js";

const PAGE = "<html><head><title>Members</title></head><body><p>12.50</p></body></html>";
// Host names resolve without DNS in these tests: to a public documentation address (RFC 5737).
const PUBLIC = async () => ["192.0.2.10"];

/** A site's fetch: robots.txt (null: 404) and pages (path -> Response factory); the paths it was asked for. */
function site(robots = "User-agent: *\nDisallow: /private/\n", pages = {}) {
  const seen = [];
  const fetchPage = async (url, init = {}) => {
    const parsed = new URL(url);
    seen.push({ path: parsed.pathname, headers: init.headers ?? {} });
    if (parsed.pathname === "/robots.txt") return robots === null ? new Response("", { status: 404 }) : new Response(robots);
    const page = pages[parsed.pathname] ?? (() => new Response(PAGE, { headers: { "content-type": "text/html" } }));
    return page();
  };
  return { seen, fetchPage };
}

test("localFetch fetches with its own fetch, honours robots and submits the body without the key", async () => {
  const { seen, fetchPage } = site();
  const { client, fetch } = makeClient([{ body: { job_id: "j1", status: "completed", url: "u", origin: "client_fetched",
    url_verified: false } }]);
  const result = await client.localFetch("https://members.example/lamp", { resolve: PUBLIC, fetchPage, formats: ["markdown"] });
  assert.equal(result.origin, "client_fetched");
  assert.deepEqual(seen.map((call) => call.path), ["/robots.txt", "/lamp"]);
  assert.ok(seen.every((call) => !("Authorization" in call.headers) && call.headers["User-Agent"].startsWith("ScrawlSDK/")));
  const [submit] = fetch.calls;
  assert.equal(submit.url.pathname, "/v1/scrape/local");
  assert.equal(Buffer.from(submit.body.body_base64, "base64").toString(), PAGE);
  assert.equal(submit.body.content_type, "text/html");
  assert.equal(submit.body.final_url, undefined);
});

test("robots.txt disallows by default; the opt-out is explicit; 5xx refuses; 404 allows", async () => {
  const { fetchPage } = site();
  const { client, fetch } = makeClient([{ body: { job_id: "j1", status: "completed", url: "u" } }]);
  await assert.rejects(client.localFetch("https://members.example/private/x", { resolve: PUBLIC, fetchPage }),
    (error) => error.code === "robots_disallowed");
  assert.equal(fetch.calls.length, 0);
  await client.localFetch("https://members.example/private/x", { resolve: PUBLIC, fetchPage, respectRobots: false });
  assert.equal(fetch.calls.length, 1);
  const down = async (url) => new URL(url).pathname === "/robots.txt" ? new Response("", { status: 503 }) : new Response(PAGE);
  await assert.rejects(client.localFetch("https://members.example/lamp", { resolve: PUBLIC, fetchPage: down }),
    (error) => error.code === "robots_unavailable");
  await client.localFetch("https://members.example/lamp", { resolve: PUBLIC, fetchPage: site(null).fetchPage });
  assert.equal(fetch.calls.length, 2);
});

test("at most five redirects, each hop checked; the size limit before upload", async () => {
  const hops = {};
  for (let index = 0; index < 6; index += 1) {
    hops[`/r${index}`] = () => new Response(null, { status: 302, headers: { location: `/r${index + 1}` } });
  }
  hops["/r6"] = () => new Response(PAGE, { headers: { "content-type": "text/html" } });
  const { fetchPage } = site(undefined, hops);
  const { client, fetch } = makeClient([{ body: { job_id: "j1", status: "completed", url: "u" } }]);
  await assert.rejects(client.localFetch("https://members.example/r0", { resolve: PUBLIC, fetchPage }),
    (error) => error.code === "too_many_redirects");
  await client.localFetch("https://members.example/r1", { resolve: PUBLIC, fetchPage });
  assert.equal(fetch.calls.at(-1).body.final_url, "https://members.example/r6");
  const big = site(undefined, { "/big": () => new Response("x".repeat(2048)) });
  await assert.rejects(client.localFetch("https://members.example/big", { resolve: PUBLIC, fetchPage: big.fetchPage, maxBytes: 1024 }),
    (error) => error.code === "payload_too_large");
  assert.equal(fetch.calls.length, 1);
});

test("the robots matcher: our group before *, longest match, Allow on a tie, wildcards and $", () => {
  const rules = parseRobots("User-agent: *\nDisallow: /\n\nUser-agent: ScrawlSDK\nDisallow: /private/\nAllow: /private/ok$\nDisallow: /*.pdf$\n");
  assert.equal(robotsAllow(rules, "https://e.example/lamp"), true);
  assert.equal(robotsAllow(rules, "https://e.example/private/x"), false);
  assert.equal(robotsAllow(rules, "https://e.example/private/ok"), true);
  assert.equal(robotsAllow(rules, "https://e.example/files/a.pdf"), false);
  assert.equal(robotsAllow(parseRobots("User-agent: *\nDisallow: /\n"), "https://e.example/x"), false);
});

// RFC 9309 vectors, the same in the Python SDK's test (test_local_fetch.py): robots.txt, path, allowed.
const ROBOTS_VECTORS = [
  ["User-agent: *\nAllow: /\nDisallow: /private\n", "/private", false],
  ["User-agent: *\nAllow: /\nDisallow: /private\n", "/", true],
  ["User-agent: *\nDisallow: /*.pdf$\n", "/doc.pdf", false],
  ["User-agent: *\nDisallow: /*.pdf$\n", "/doc.pdf?x=1", true],
  ["User-agent: *\nDisallow: /*.pdf$\n", "/doc.pdfs", true],
  ["User-agent: *\nDisallow: /a\nAllow: /a/public\n", "/a/public", true],
  ["User-agent: *\nDisallow: /a\nAllow: /a/public\n", "/a/b", false],
  ["User-agent: *\nDisallow: /t\nAllow: /t\n", "/t", true],
  ["User-agent: sdk\nDisallow: /\n\nUser-agent: *\nAllow: /\n", "/x", true],
  ["User-agent:\nDisallow: /\n\nUser-agent: *\nDisallow: /p\n", "/x", true],
  ["User-agent: ScrawlSDK\nDisallow: /x\n\nUser-agent: *\nDisallow: /\n", "/x", false],
  ["User-agent: ScrawlSDK\nDisallow: /x\n\nUser-agent: *\nDisallow: /\n", "/y", true],
  ["User-agent: scrawlsdk\nUser-agent: other\nDisallow: /both\n", "/both", false],
  ["User-agent: other\nDisallow: /\n", "/x", true],
];

test("robots.txt is matched as RFC 9309 says (the Python SDK's vectors)", () => {
  for (const [robots, path, allowed] of ROBOTS_VECTORS) {
    assert.equal(robotsAllow(parseRobots(robots), `https://members.example${path}`), allowed, `${JSON.stringify(robots)} ${path}`);
  }
});

test("a redirect to another host is not followed with your own fetch; https to http never", async () => {
  const { seen, fetchPage } = site(undefined, {
    "/go": () => new Response(null, { status: 302, headers: { location: "https://elsewhere.example/x" } }),
    "/down": () => new Response(null, { status: 301, headers: { location: "http://members.example/lamp" } }),
  });
  const hosts = [];
  const watched = async (url, init) => { hosts.push(new URL(url).host); return fetchPage(url, init); };
  const { client, fetch } = makeClient([{ body: { job_id: "j1", status: "completed", url: "u" } }]);
  await assert.rejects(client.localFetch("https://members.example/go", { resolve: PUBLIC, fetchPage: watched }),
    (error) => error.code === "cross_origin_redirect" && error.message.includes("elsewhere.example"));
  await assert.rejects(client.localFetch("https://members.example/down", { resolve: PUBLIC, fetchPage: watched }),
    (error) => error.code === "insecure_redirect");
  assert.ok(hosts.every((host) => host === "members.example") && seen.length > 0);
  assert.equal(fetch.calls.length, 0);
});

test("a redirect this environment hides (a browser's opaque redirect) is refused, not sent as the page", async () => {
  const opaque = async (url) => (new URL(url).pathname === "/robots.txt" ? new Response("", { status: 404 })
    : { status: 0, type: "opaqueredirect", headers: new Headers(), body: null, arrayBuffer: async () => new ArrayBuffer(0) });
  const { client, fetch } = makeClient([{ body: { job_id: "j1", status: "completed", url: "u" } }]);
  await assert.rejects(client.localFetch("https://members.example/moved", { resolve: PUBLIC, fetchPage: opaque }),
    (error) => error.code === "redirect_hidden");
  assert.equal(fetch.calls.length, 0);
});

test("robots compares paths after RFC 9309 percent-encoding normalisation (fixes-5 item 4)", () => {
  const rules = parseRobots("User-agent: *\nDisallow: /private/\nDisallow: /caf%C3%A9\nDisallow: /%7Euser\nDisallow: /a/b\n");
  for (const blocked of ["/%70rivate/x", "/private/x", "/%70%72ivate/", "/café", "/caf%c3%a9", "/~user/page", "/%7euser"]) {
    assert.equal(robotsAllow(rules, `https://e.example${blocked}`), false, blocked);
  }
  for (const allowed of ["/a%2Fb", "/public", "/%2570rivate/"]) {
    assert.equal(robotsAllow(rules, `https://e.example${allowed}`), true, allowed);
  }
});

test("robots compares the path the client will send (fixes-5 review)", () => {
  const rules = parseRobots("User-agent: *\nDisallow: /My%20Documents/\nDisallow: /%7Bt%7D\nDisallow: /raw space/\nDisallow: /a|b\n");
  for (const blocked of ["/My Documents/f", "/My%20Documents/f", "/{t}", "/%7bt%7d", "/raw%20space/x", "/raw space/x",
                         "/a/../My%20Documents/f", "/x/./../My Documents/f", "/a%7Cb", "/a|b"]) {
    assert.equal(robotsAllow(rules, `https://e.example${blocked}`), false, blocked);
  }
  for (const allowed of ["/My-Documents/f", "/t", "/a/b", "/My%2520Documents/"]) {
    assert.equal(robotsAllow(rules, `https://e.example${allowed}`), true, allowed);
  }
});

test("the module says how robots paths are compared (fixes-6 item 4)", async () => {
  const { readFile } = await import("node:fs/promises");
  const source = await readFile(new URL("../src/local_fetch.js", import.meta.url), "utf8");
  const header = source.split("\nimport ")[0].replace(/\/\/ ?/g, "").replace(/\s+/g, " ");
  assert.ok(!header.includes("not normalised"), header);
  assert.ok(header.includes("percent-encoding normalised") && header.includes("dot segments removed"), header);
});

// -- the review of kits 0.1.5: robots redirects, bounds, errors, timeouts, uploads ------------------------------------

function robotsRedirectSite(location) {
  const seen = [];
  const fetchPage = async (url) => {
    const parsed = new URL(url);
    seen.push(parsed.toString());
    if (parsed.pathname === "/robots.txt" && parsed.hostname === "members.example") {
      return new Response(null, { status: 301, headers: { location } });
    }
    if (parsed.pathname.endsWith("robots.txt")) return new Response("User-agent: *\nDisallow: /private/\n");
    return new Response(PAGE, { headers: { "content-type": "text/html" } });
  };
  return { seen, fetchPage };
}

test("robots.txt redirects get the same checks as every page hop", async () => {
  for (const [location, code] of [["http://members.example/robots.txt", "insecure_redirect"],
    ["https://other.example/robots.txt", "cross_origin_redirect"]]) {
    const { seen, fetchPage } = robotsRedirectSite(location);
    const { client, fetch } = makeClient([]);
    await assert.rejects(client.localFetch("https://members.example/lamp", { resolve: PUBLIC, fetchPage }),
      (error) => error.code === code);
    assert.deepEqual(seen, ["https://members.example/robots.txt"]);
    assert.equal(fetch.calls.length, 0);
  }
});

test("a same-host robots.txt redirect is followed and its rules apply", async () => {
  const { seen, fetchPage } = robotsRedirectSite("/moved-robots.txt");
  const { client, fetch } = makeClient([]);
  await assert.rejects(client.localFetch("https://members.example/private/x", { resolve: PUBLIC, fetchPage }),
    (error) => error.code === "robots_disallowed");
  assert.deepEqual(seen, ["https://members.example/robots.txt", "https://members.example/moved-robots.txt"]);
  assert.equal(fetch.calls.length, 0);
});

test("robots.txt is read up to 500 KiB only", async () => {
  const robots = "User-agent: *\n" + `# ${"x".repeat(1022)}\n`.repeat(600) + "Disallow: /lamp\n";
  const { fetchPage } = site(robots);
  const { client, fetch } = makeClient([{ body: { job_id: "j1", status: "completed" } }]);
  await client.localFetch("https://members.example/lamp", { resolve: PUBLIC, fetchPage });
  assert.equal(fetch.calls.length, 1);
});

test("a network failure or a timeout of the fetch is a ScrawlError", async () => {
  for (const [failure, code] of [[new TypeError("fetch failed"), "fetch_failed"],
    [Object.assign(new Error("timed out"), { name: "TimeoutError" }), "fetch_timeout"]]) {
    const { client, fetch } = makeClient([]);
    await assert.rejects(client.localFetch("https://members.example/lamp", { resolve: PUBLIC, fetchPage: async () => { throw failure; } }),
      (error) => error.code === code);
    assert.equal(fetch.calls.length, 0);
  }
});

test("the fetch is bounded by the client's timeout", async () => {
  const signals = [];
  const fetchPage = async (url, init = {}) => {
    signals.push(init.signal);
    return new URL(url).pathname === "/robots.txt" ? new Response("", { status: 404 })
      : new Response(PAGE, { headers: { "content-type": "text/html" } });
  };
  const { client } = makeClient([{ body: { job_id: "j1", status: "completed" } }]);
  await client.localFetch("https://members.example/lamp", { resolve: PUBLIC, fetchPage });
  assert.equal(signals.length, 2);
  assert.ok(signals.every((signal) => signal instanceof AbortSignal));
});

test("robots wildcards match in bounded time", () => {
  const rules = [{ allow: false, pattern: "/" + "*a".repeat(40) + "b" }];
  const started = Date.now();
  assert.equal(robotsAllow(rules, "https://members.example/" + "a".repeat(5000)), true);
  assert.equal(robotsAllow(rules, "https://members.example/" + "a".repeat(50) + "b"), false);
  assert.ok(Date.now() - started < 2000);
});

test("an empty page is refused before anything is sent, and an overlong type is sent as its media type", async () => {
  const empty = site(undefined, { "/lamp": () => new Response(null, { status: 204 }) });
  const first = makeClient([]);
  await assert.rejects(first.client.localFetch("https://members.example/lamp", { resolve: PUBLIC, fetchPage: empty.fetchPage }),
    (error) => error.code === "empty_body");
  assert.equal(first.fetch.calls.length, 0);
  const longType = "text/html; " + Array.from({ length: 60 }, (_, index) => `p${index}=v`).join("; ");
  const long = site(undefined, { "/lamp": () => new Response(PAGE, { headers: { "content-type": longType } }) });
  const second = makeClient([{ body: { job_id: "j1", status: "completed" } }]);
  await second.client.localFetch("https://members.example/lamp", { resolve: PUBLIC, fetchPage: long.fetchPage });
  assert.equal(second.fetch.calls[0].body.content_type, "text/html");
});

// -- link-local and cloud-metadata destinations are refused by default (L0, 2026-11-27) -----------------------------

const never = async (url) => { throw new Error(`no request may be made: ${url}`); };

test("link-local and metadata destinations are refused before connecting", async () => {
  for (const url of ["http://169.254.169.254/latest/meta-data/", "http://[fe80::1]/x", "http://[fd00:ec2::254]/x",
    "http://[::ffff:169.254.169.254]/x", "http://metadata.google.internal/computeMetadata/v1/", "http://metadata/x",
    "http://METADATA.Google.Internal./x"]) {
    const { client, fetch } = makeClient([]);
    await assert.rejects(client.localFetch(url, { resolve: PUBLIC, fetchPage: never }),
      (error) => error.code === "link_local_refused" && /allowLinkLocal/.test(error.message), url);
    assert.equal(fetch.calls.length, 0);
  }
});

test("a name that resolves to a link-local address is refused", async () => {
  for (const addresses of [["169.254.169.254"], ["192.0.2.10", "169.254.10.1"], ["fe80::1%2"], ["fd00:ec2::254"]]) {
    const { client, fetch } = makeClient([]);
    await assert.rejects(client.localFetch("https://innocent.example/lamp", { resolve: async () => addresses,
      fetchPage: never }), (error) => error.code === "link_local_refused");
    assert.equal(fetch.calls.length, 0);
  }
});

test("every redirect hop is checked again before it is fetched", async () => {
  const answers = [["192.0.2.10"], ["169.254.169.254"]];         // the name points elsewhere by the time of the hop
  const seen = [];
  const fetchPage = async (url) => {
    seen.push(new URL(url).pathname);
    return new Response(null, { status: 302, headers: { location: "/next" } });
  };
  const { client, fetch } = makeClient([]);
  await assert.rejects(client.localFetch("https://members.example/lamp", { respectRobots: false, fetchPage,
    resolve: async () => answers.shift() }), (error) => error.code === "link_local_refused");
  assert.deepEqual(seen, ["/lamp"]);
  assert.equal(fetch.calls.length, 0);
});

test("a robots.txt redirect to a metadata address is refused", async () => {
  const { seen, fetchPage } = robotsRedirectSite("http://169.254.169.254/robots.txt");
  const { client, fetch } = makeClient([]);
  await assert.rejects(client.localFetch("http://members.example/lamp", { resolve: PUBLIC, fetchPage }),
    (error) => error.code === "link_local_refused");
  assert.deepEqual(seen, ["http://members.example/robots.txt"]);
  assert.equal(fetch.calls.length, 0);
});

test("private and loopback destinations stay allowed, and allowLinkLocal is an explicit opt-in", async () => {
  for (const addresses of [["10.0.0.5"], ["192.168.1.20"], ["127.0.0.1"], ["::1"], ["fd12:3456::1"]]) {
    const { fetchPage } = site();
    const { client, fetch } = makeClient([{ body: { job_id: "j1", status: "completed" } }]);
    await client.localFetch("https://members.example/lamp", { resolve: async () => addresses, fetchPage });
    assert.equal(fetch.calls.length, 1, addresses.join());
  }
  const { fetchPage } = site();
  const { client, fetch } = makeClient([{ body: { job_id: "j1", status: "completed" } }]);
  await client.localFetch("https://members.example/lamp", { resolve: async () => ["169.254.169.254"], fetchPage,
    allowLinkLocal: true });
  assert.equal(fetch.calls.length, 1);
});

test("a name that does not resolve is a fetch failure", async () => {
  const { client, fetch } = makeClient([]);
  await assert.rejects(client.localFetch("https://nowhere.example/lamp", { fetchPage: never,
    resolve: async () => { throw Object.assign(new Error("getaddrinfo ENOTFOUND"), { code: "ENOTFOUND" }); } }),
  (error) => error.code === "fetch_failed");
  assert.equal(fetch.calls.length, 0);
});
