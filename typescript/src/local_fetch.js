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

import { ScrawlError } from "./errors.js";
import { VERSION } from "./version.js";

export const USER_AGENT = `ScrawlSDK/${VERSION} (+localFetch)`;
const ROBOTS_AGENT = "scrawlsdk"; // our product token, lower-cased
export const DEFAULT_MAX_REDIRECTS = 5;
export const DEFAULT_MAX_BYTES = 5 * 1024 * 1024;
const REDIRECTS = new Set([301, 302, 303, 307, 308]);

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

function matches(pattern, path) {
  const anchored = pattern.endsWith("$");
  const body = anchored ? pattern.slice(0, -1) : pattern;
  const regex = body.split("*").map((part) => part.replace(/[.+?^${}()|[\]\\]/g, "\\$&")).join(".*");
  return new RegExp(`^${regex}${anchored ? "$" : ""}`).test(path);
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

async function readRobots(fetchImpl, origin) {
  const res = await fetchImpl(`${origin}/robots.txt`, { headers: { "User-Agent": USER_AGENT }, redirect: "follow" });
  if (res.status >= 500 || res.status === 429) {
    throw refuse("robots_unavailable", `robots.txt answered ${res.status}: not fetched (pass respectRobots: false `
      + "to fetch anyway, at your own responsibility)");
  }
  if (res.status >= 400) return [];
  return parseRobots(await res.text());
}

async function readCapped(res, maxBytes) {
  const chunks = [];
  let total = 0;
  if (res.body && typeof res.body.getReader === "function") {
    const reader = res.body.getReader();
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
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
  maxBytes = DEFAULT_MAX_BYTES, sameHostOnly = false } = {}) {
  checkUrl(url);
  const rules = new Map();
  let current = url;
  for (let hop = 0; hop <= maxRedirects; hop += 1) {
    const origin = new URL(current).origin;
    if (respectRobots) {
      if (!rules.has(origin)) rules.set(origin, await readRobots(fetchImpl, origin));
      if (!robotsAllow(rules.get(origin), current)) {
        throw refuse("robots_disallowed", `robots.txt disallows ${current}: not fetched (pass respectRobots: false `
          + "to fetch anyway, at your own responsibility)");
      }
    }
    const res = await fetchImpl(current, { headers: { "User-Agent": USER_AGENT }, redirect: "manual" });
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
    return { url, finalUrl: current, status: res.status, contentType: res.headers.get("content-type") || "", body };
  }
  throw refuse("too_many_redirects", `More than ${maxRedirects} redirects from ${url}: not fetched`);
}
