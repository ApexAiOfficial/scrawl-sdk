"""List a site's URLs: the start page's links plus its sitemap, same host only.

    python examples/map_site.py https://example.com 200
"""

import sys

from scrawl import Scrawl

url = sys.argv[1]
limit = int(sys.argv[2]) if len(sys.argv) > 2 else 100
with Scrawl() as client:
    site = client.map(url, limit=limit)
    for link in site.get("links") or []:
        print(link)
    print(f"{len(site.get('links') or [])} URL(s); sources: {site.get('sources')}", file=sys.stderr)
