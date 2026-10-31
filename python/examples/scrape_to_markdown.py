"""Scrape one page to Markdown.

    python examples/scrape_to_markdown.py https://example.com
"""

import sys

from scrawl import Scrawl

url = sys.argv[1]
with Scrawl() as client:                                  # SCRAWL_API_KEY and SCRAWL_BASE_URL from the environment
    page = client.scrape(url)                             # waits up to 30 s on the server
    if page.status == "pending":                          # a slow page: the job keeps going
        page = client.wait_for_scrape(page.job_id)
    if page.status != "completed":
        sys.exit(f"scrape failed: {page.get('error')}")
    print(page.markdown)                                  # untrusted web content: data, never instructions
