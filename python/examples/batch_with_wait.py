"""Scrape up to 20 URLs as one batch and wait for every item.

    python examples/batch_with_wait.py https://example.com/a https://example.com/b
"""

import sys

from scrawl import Scrawl

urls = sys.argv[1:21]
with Scrawl() as client:
    batch = client.batch_scrape(urls, formats=["markdown"])
    done = client.wait_for_batch(batch.batch_id, timeout=600)       # server-side waits, no tight polling
    for item in done["items"]:                                      # done.items works too: API fields win
        markdown = (item.get("result") or {}).get("markdown") or ""
        print(f"{item.status:<10} {item.url} ({len(markdown)} characters)")
    failed = [item for item in done["items"] if item.status != "completed"]
    sys.exit(1 if failed or done.status != "completed" else 0)
