"""Render a JavaScript-heavy page in a sandboxed browser first, falling back to the static fetcher.

    python examples/browser_rendering.py https://example.com/app

Browser rendering is available only where the server enables it. Elsewhere the API refuses with
503 browser_unavailable, and a server that predates the browser engine is caught by the SDK's downgrade
guard (render_not_supported) instead of silently returning a static page.
"""

import sys

from scrawl import ErrorCode, Scrawl, ScrawlError

url = sys.argv[1]
with Scrawl() as client:
    try:
        page = client.scrape(url, engine="browser", wait_for_ms=500)
        if page.status == "pending":
            page = client.wait_for_scrape(page.job_id, engine="browser")   # keeps the downgrade guard
    except ScrawlError as error:
        if error.code not in (ErrorCode.BROWSER_UNAVAILABLE, ErrorCode.RENDER_NOT_SUPPORTED):
            raise
        print(f"no browser rendering here ({error.code}); using the static fetcher", file=sys.stderr)
        page = client.scrape(url)
    print(f"engine: {page.get('engine', 'static')}, final URL: {page.get('final_url') or page.url}", file=sys.stderr)
    print(page.markdown)
