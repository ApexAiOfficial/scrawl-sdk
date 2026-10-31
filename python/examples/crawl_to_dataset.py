"""Crawl a target into a new dataset version, then inspect and query it.

    python examples/crawl_to_dataset.py my-crawl-target
"""

import json
import sys

from scrawl import Scrawl

target = sys.argv[1]
with Scrawl() as client:
    launch = client.crawl(target, max_items=500)                  # a named crawl target the server allows
    job = client.wait_for_job(launch.job_id, timeout=1800)
    if job.status != "COMPLETED":
        sys.exit(f"crawl {job.status}")
    dataset_id = launch.dataset_id
    fields = client.dataset_fields(dataset_id, version=launch.dataset_version_id).fields
    print("fields:", ", ".join(f"{f.path} ({'/'.join(f.types)})" for f in fields))
    numeric = next((f.path for f in fields if "number" in f.types or "integer" in f.types), None)
    filters = [{"field": numeric, "op": "lt", "value": 20}] if numeric else []
    for record in client.paginate(client.query_dataset, dataset_id, filters, version_id=launch.dataset_version_id):
        print(json.dumps(record.to_dict()))
