import assert from "node:assert/strict";
import { test } from "node:test";

import { parseRobots, robotsAllow } from "../src/local_fetch.js";
import { makeClient } from "./helpers.js";

const PAGE = "<html><head><title>Members</title></head><body><p>12.50</p></body></html>";

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
  const result = await client.localFetch("https://members.example/lamp", { fetchPage, formats: ["markdown"] });
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
  await assert.rejects(client.localFetch("https://members.example/private/x", { fetchPage }),
    (error) => error.code === "robots_disallowed");
  assert.equal(fetch.calls.length, 0);
  await client.localFetch("https://members.example/private/x", { fetchPage, respectRobots: false });
  assert.equal(fetch.calls.length, 1);
  const down = async (url) => new URL(url).pathname === "/robots.txt" ? new Response("", { status: 503 }) : new Response(PAGE);
  await assert.rejects(client.localFetch("https://members.example/lamp", { fetchPage: down }),
    (error) => error.code === "robots_unavailable");
  await client.localFetch("https://members.example/lamp", { fetchPage: site(null).fetchPage });
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
  await assert.rejects(client.localFetch("https://members.example/r0", { fetchPage }),
    (error) => error.code === "too_many_redirects");
  await client.localFetch("https://members.example/r1", { fetchPage });
  assert.equal(fetch.calls.at(-1).body.final_url, "https://members.example/r6");
  const big = site(undefined, { "/big": () => new Response("x".repeat(2048)) });
  await assert.rejects(client.localFetch("https://members.example/big", { fetchPage: big.fetchPage, maxBytes: 1024 }),
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
  await assert.rejects(client.localFetch("https://members.example/go", { fetchPage: watched }),
    (error) => error.code === "cross_origin_redirect" && error.message.includes("elsewhere.example"));
  await assert.rejects(client.localFetch("https://members.example/down", { fetchPage: watched }),
    (error) => error.code === "insecure_redirect");
  assert.ok(hosts.every((host) => host === "members.example") && seen.length > 0);
  assert.equal(fetch.calls.length, 0);
});

test("a redirect this environment hides (a browser's opaque redirect) is refused, not sent as the page", async () => {
  const opaque = async (url) => (new URL(url).pathname === "/robots.txt" ? new Response("", { status: 404 })
    : { status: 0, type: "opaqueredirect", headers: new Headers(), body: null, arrayBuffer: async () => new ArrayBuffer(0) });
  const { client, fetch } = makeClient([{ body: { job_id: "j1", status: "completed", url: "u" } }]);
  await assert.rejects(client.localFetch("https://members.example/moved", { fetchPage: opaque }),
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
