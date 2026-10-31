"""Scrape a page, then save its job's artifacts: checked against the artifact list, never overwriting.

    python examples/download_artifacts.py https://example.com ./artifacts
"""

import hashlib
import re
import sys
from pathlib import Path

from scrawl import Scrawl

url, out = sys.argv[1], Path(sys.argv[2])
out.mkdir(parents=True, exist_ok=True)
with Scrawl() as client:
    page = client.scrape(url)
    if page.status == "pending":
        page = client.wait_for_scrape(page.job_id)
    for artifact in client.list_artifacts(page.job_id).artifacts:
        data = client.download_artifact(page.job_id, artifact.name)
        if len(data) != artifact.size_bytes:
            sys.exit(f"{artifact.name}: {len(data)} bytes, the list says {artifact.size_bytes}")
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", artifact.name).lstrip(".") or "artifact"   # never trust a name
        with open(out / safe_name, "xb") as file:                 # "x": fail rather than overwrite
            file.write(data)
        print(f"{safe_name}  {len(data)} bytes  sha256 {hashlib.sha256(data).hexdigest()}")
