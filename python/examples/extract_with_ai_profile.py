"""Structured JSON from a page with your own AI provider (bring-your-own AI).

    SCRAWL_AI_PROVIDER=openai SCRAWL_AI_API_KEY=... python examples/extract_with_ai_profile.py https://example.com/item

With SCRAWL_AI_PROVIDER and SCRAWL_AI_API_KEY set, the example (re)configures a profile named "example" first;
the provider key is stored encrypted on the server and never returned. Without them it uses your default profile.
"""

import json
import os
import sys

from scrawl import Scrawl

SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "price": {"type": "number"}, "sku": {"type": "string"}},
}

url = sys.argv[1]
with Scrawl() as client:
    profile = None
    if os.environ.get("SCRAWL_AI_PROVIDER") and os.environ.get("SCRAWL_AI_API_KEY"):
        info = client.set_ai_provider("example", provider=os.environ["SCRAWL_AI_PROVIDER"],
                                      api_key=os.environ["SCRAWL_AI_API_KEY"],
                                      model=os.environ.get("SCRAWL_AI_MODEL") or None)
        print(f"profile {info.profile}: {info.provider}/{info.model} key {info.key_fingerprint}", file=sys.stderr)
        profile = info.profile
    product = client.scrape(url, formats=["json"], schema=SCHEMA, profile=profile,
                            instruction="The product name, price and SKU, if this is a product page")
    if product.status == "pending":
        product = client.wait_for_scrape(product.job_id)
    if product.status != "completed":
        sys.exit(f"extraction failed: {product.get('error_code')}: {product.get('error')}")
    print(json.dumps(product.json.to_dict() if product.json else None, indent=2))
    print("provider, model and tokens used:", product.get("ai"), file=sys.stderr)
