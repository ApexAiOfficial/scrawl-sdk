// Fetch a page from your own machine, then have Scrawl render it (`localFetch`).
//
// The page is fetched with your own fetch, from your machine and your address; Scrawl receives the body and makes no
// connection to the site. By default the site's robots.txt is read and honoured first (`respectRobots: false` turns
// this off; whether you may fetch a page without it is then your responsibility). At most `maxRedirects` redirects are
// followed, each checked against robots.txt again, and the body is read only up to the size limit. robots.txt is
// matched as RFC 9309 says: the group for our product token (`ScrawlSDK`, case-insensitive), else `*`; the longest
// matching rule wins, Allow on a tie; `*` and a final `$`. Rules and paths are compared with percent-encoding
// normalised (an encoded unreserved character is decoded; an encoded reserved one, such as `%2F`, stays encoded) and
// dot segments removed.
//
// The fetch never carries your Scrawl API key: it is a plain fetch with its own headers. A redirect from https to
// http is never followed. With your own `fetchPage` (it may carry credentials for the site you asked for) a redirect
// to another host is not followed either. Where the environment hides redirects (a browser's fetch answers an opaque
// redirect), the call is refused rather than sending an empty page: fetch the address it redirects to directly.
// The robots.txt request gets the same redirect checks as the page, and at most 500 KiB of it is read (RFC 9309
// section 2.5). Each request is bounded by the client's timeout. A failure to reach the site is a ScrawlError
// (fetch_failed, or fetch_timeout); an empty page is refused (empty_body) before anything is sent to Scrawl.

import { ScrawlError } from "./errors.js";
import { VERSION } from "./version.js";

export const USER_AGENT = `ScrawlSDK/${VERSION} (+localFetch)`;
const ROBOTS_AGENT = "scrawlsdk"; // our product token, lower-cased
export const DEFAULT_MAX_REDIRECTS = 5;
export const DEFAULT_MAX_BYTES = 5 * 1024 * 1024;
const REDIRECTS = new Set([301, 302, 303, 307, 308]);
// How much of a robots.txt is read; the rest is ignored (RFC 9309 section 2.5: at least 500 kibibytes).
export const ROBOTS_MAX_BYTES = 500 * 1024;
// The longest Content-Type Scrawl accepts; a longer one is sent as its media type alone.
const MAX_CONTENT_TYPE = 200;

function refuse(code, message) {
  return new ScrawlError(message, { code });
}

function checkUrl(url) {
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    throw refuse("invalid_request", `localFetch needs an absolute http(s) URL, not ${JSON.stringify(url)}`);
  }
  if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
    throw refuse("invalid_request", `localFetch needs an absolute http(s) URL, not ${JSON.stringify(url)}`);
  }
  return parsed;
}

/** The rules of a robots.txt body for our agent (its group, else `*`): [{allow, pattern}] (RFC 9309). */
export function parseRobots(text) {
  const groups = [];
  let current = null;
  let lastWasAgent = false;
  for (const raw of String(text).split(/\r?\n/)) {
    const line = raw.replace(/#.*$/, "").trim();
    const colon = line.indexOf(":");
    if (colon < 0) continue;
    const key = line.slice(0, colon).trim().toLowerCase();
    const value = line.slice(colon + 1).trim();
    if (key === "user-agent") {
      if (!lastWasAgent || current === null) {
        current = { agents: [], rules: [] };
        groups.push(current);
      }
      current.agents.push(value.toLowerCase());
      lastWasAgent = true;
    } else if ((key === "allow" || key === "disallow") && current !== null) {
      if (value) current.rules.push({ allow: key === "allow", pattern: normaliseRobotsPath(value) });
      lastWasAgent = false;
    } else {
      lastWasAgent = false;
    }
  }
  const ours = groups.filter((group) => group.agents.includes(ROBOTS_AGENT));
  const chosen = ours.length ? ours : groups.filter((group) => group.agents.includes("*"));
  return chosen.flatMap((group) => group.rules);
}

const UNRESERVED = /^[A-Za-z0-9\-._~]$/;
const KEPT = /^[A-Za-z0-9\-._~:/?#[\]@!$&'()*+,;=%]$/;   // unreserved, reserved (RFC 3986) and the escape

/** TEXT as RFC 9309 (section 2.2.2) compares it: an encoded unreserved octet is decoded, every other encoding is
 * kept (upper-case hex), and a character that is neither unreserved nor reserved (non-ASCII, a space, `"<>\^`{|}`, a
 * control character) is percent-encoded (UTF-8), as the client sends it. An encoded reserved octet such as
 * `%2F` stays a different octet from the character it encodes. */
function normaliseRobotsPath(text) {
  const source = String(text);
  let out = "";
  for (let index = 0; index < source.length;) {
    const hex = source.slice(index + 1, index + 3);
    if (source[index] === "%" && /^[0-9A-Fa-f]{2}$/.test(hex)) {
      const decoded = String.fromCharCode(parseInt(hex, 16));
      out += UNRESERVED.test(decoded) ? decoded : `%${hex.toUpperCase()}`;
      index += 3;
      continue;
    }
    const codePoint = source.codePointAt(index);
    const char = String.fromCodePoint(codePoint);
    out += KEPT.test(char) ? char
      : Array.from(new TextEncoder().encode(char), (byte) => `%${byte.toString(16).toUpperCase().padStart(2, "0")}`).join("");
    index += char.length;
  }
  return out;
}

// Whether all of TEXT matches PATTERN, where `*` matches any run of characters. Greedy, going back only to the last
// `*`: at most PATTERN.length x TEXT.length steps, whatever the rule (no regular expression to backtrack).
function glob(pattern, text) {
  let p = 0;
  let t = 0;
  let star = -1;
  let mark = 0;
  while (t < text.length) {
    if (p < pattern.length && pattern[p] === "*") {
      star = p;
      mark = t;
      p += 1;
    } else if (p < pattern.length && pattern[p] === text[t]) {
      p += 1;
      t += 1;
    } else if (star >= 0) {
      p = star + 1;
      mark += 1;
      t = mark;
    } else {
      return false;
    }
  }
  while (p < pattern.length && pattern[p] === "*") p += 1;
  return p === pattern.length;
}

// A rule matches a path from its start; a final `$` makes it match the whole path.
function matches(pattern, path) {
  const anchored = pattern.endsWith("$");
  return glob(anchored ? pattern.slice(0, -1) : `${pattern}*`, path);
}

/** Whether RULES allow URL: the longest matching rule wins, Allow on a tie; no rule allows. */
export function robotsAllow(rules, url) {
  const parsed = new URL(url);
  const path = normaliseRobotsPath((parsed.pathname || "/") + (parsed.search || ""));
  let best = null;
  for (const rule of rules) {
    if (!matches(rule.pattern, path)) continue;
    if (best === null || rule.pattern.length > best.pattern.length
        || (rule.pattern.length === best.pattern.length && rule.allow)) {
      best = rule;
    }
  }
  return best === null || best.allow;
}

function init(timeoutMs) {
  const options = { headers: { "User-Agent": USER_AGENT }, redirect: "manual" };
  if (timeoutMs > 0 && typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function") {
    options.signal = AbortSignal.timeout(timeoutMs);
  }
  return options;
}

// One request of the fetch: a failure to reach the site is a ScrawlError, never a bare TypeError.
async function request(fetchImpl, url, timeoutMs) {
  try {
    return await fetchImpl(url, init(timeoutMs));
  } catch (error) {
    if (error instanceof ScrawlError) throw error;
    if (error?.name === "TimeoutError" || error?.name === "AbortError") {
      throw refuse("fetch_timeout", `${url} did not answer in time: not fetched`);
    }
    throw refuse("fetch_failed", `Could not fetch ${url} (${error?.name ?? "error"}): not fetched`);
  }
}

// ORIGIN's robots.txt rules, its redirects checked as a page's are (at most five), at most 500 KiB read.
async function readRobots(fetchImpl, origin, sameHostOnly, timeoutMs) {
  let current = `${origin}/robots.txt`;
  for (let hop = 0; hop <= DEFAULT_MAX_REDIRECTS; hop += 1) {
    const res = await request(fetchImpl, current, timeoutMs);
    if (res.type === "opaqueredirect" || res.status === 0) {
      throw refuse("redirect_hidden", `${current} redirects, and this environment hides where to: robots.txt `
        + "cannot be read (pass respectRobots: false to fetch anyway, at your own responsibility)");
    }
    const location = res.headers.get("location");
    if (REDIRECTS.has(res.status) && location) {
      current = nextHop(current, location, sameHostOnly);
      continue;
    }
    if (res.status >= 500 || res.status === 429) {
      throw refuse("robots_unavailable", `robots.txt answered ${res.status}: not fetched (pass respectRobots: false `
        + "to fetch anyway, at your own responsibility)");
    }
    if (res.status >= 400) return [];
    const bytes = await readCapped(res, ROBOTS_MAX_BYTES, { truncate: true });
    return parseRobots(new TextDecoder("utf-8").decode(bytes));
  }
  throw refuse("robots_unavailable", `robots.txt at ${origin} redirects more than ${DEFAULT_MAX_REDIRECTS} times: `
    + "not fetched (pass respectRobots: false to fetch anyway)");
}

function contentTypeOf(value) {
  return value.length <= MAX_CONTENT_TYPE ? value : value.split(";", 1)[0].trim().slice(0, MAX_CONTENT_TYPE);
}

async function readCapped(res, maxBytes, { truncate = false } = {}) {
  const chunks = [];
  let total = 0;
  if (res.body && typeof res.body.getReader === "function") {
    const reader = res.body.getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      if (truncate && total + value.byteLength >= maxBytes) {
        chunks.push(value.subarray(0, maxBytes - total));
        total = maxBytes;
        await reader.cancel();
        break;
      }
      total += value.byteLength;
      if (total > maxBytes) {
        await reader.cancel();
        throw refuse("payload_too_large", `The page is larger than ${maxBytes} bytes: not sent`);
      }
      chunks.push(value);
    }
    const out = new Uint8Array(total);
    let offset = 0;
    for (const chunk of chunks) { out.set(chunk, offset); offset += chunk.byteLength; }
    return out;
  }
  const whole = new Uint8Array(await res.arrayBuffer());
  if (truncate) return whole.subarray(0, maxBytes);
  if (whole.byteLength > maxBytes) throw refuse("payload_too_large", `The page is larger than ${maxBytes} bytes: not sent`);
  return whole;
}

function hostOf(parsed) {
  return [parsed.hostname.toLowerCase(), parsed.port || (parsed.protocol === "https:" ? "443" : "80")];
}

/** Where a redirect from CURRENT to LOCATION leads, or a refusal: not http(s), a downgrade from https, or (with your
 * own fetch) another host. An upgrade to https on the same host is the same host. */
function nextHop(current, location, sameHostOnly) {
  const target = new URL(location, current).toString();
  checkUrl(target);
  const from = new URL(current);
  const to = new URL(target);
  if (from.protocol === "https:" && to.protocol === "http:") {
    throw refuse("insecure_redirect", `${current} redirects to ${target}, from https to http: not followed`);
  }
  const [hereHost, herePort] = hostOf(from);
  const [thereHost, therePort] = hostOf(to);
  const upgrade = from.protocol === "http:" && to.protocol === "https:" && hereHost === thereHost
    && herePort === "80" && therePort === "443";
  if (sameHostOnly && (hereHost !== thereHost || herePort !== therePort) && !upgrade) {
    throw refuse("cross_origin_redirect", `${current} redirects to another host (${target}): not followed with your `
      + "own fetch, which may carry credentials for the site you asked for; fetch that address directly if you mean to");
  }
  return target;
}

/** Fetch URL from this machine: { url, finalUrl, status, contentType, body } (robots, redirects, the size limit);
 * with SAME_HOST_ONLY (your own fetch) no redirect to another host. */
export async function fetchPage(fetchImpl, url, { respectRobots = true, maxRedirects = DEFAULT_MAX_REDIRECTS,
  maxBytes = DEFAULT_MAX_BYTES, sameHostOnly = false, timeoutMs = 0 } = {}) {
  checkUrl(url);
  const rules = new Map();
  let current = url;
  for (let hop = 0; hop <= maxRedirects; hop += 1) {
    const origin = new URL(current).origin;
    if (respectRobots) {
      if (!rules.has(origin)) rules.set(origin, await readRobots(fetchImpl, origin, sameHostOnly, timeoutMs));
      if (!robotsAllow(rules.get(origin), current)) {
        throw refuse("robots_disallowed", `robots.txt disallows ${current}: not fetched (pass respectRobots: false `
          + "to fetch anyway, at your own responsibility)");
      }
    }
    const res = await request(fetchImpl, current, timeoutMs);
    if (res.type === "opaqueredirect" || res.status === 0) {
      throw refuse("redirect_hidden", `${current} redirects, and this environment hides where to (a browser's fetch): `
        + "fetch the address it redirects to directly");
    }
    const location = res.headers.get("location");
    if (REDIRECTS.has(res.status) && location) {
      current = nextHop(current, location, sameHostOnly);
      continue;
    }
    const body = await readCapped(res, maxBytes);
    if (body.byteLength === 0) {
      throw refuse("empty_body", `${current} answered ${res.status} with no body: nothing to render, nothing sent`);
    }
    return { url, finalUrl: current, status: res.status, contentType: contentTypeOf(res.headers.get("content-type") || ""),
      body };
  }
  throw refuse("too_many_redirects", `More than ${maxRedirects} redirects from ${url}: not fetched`);
}
