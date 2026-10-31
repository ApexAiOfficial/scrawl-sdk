"""Typed errors, the stable error code, and retries that never start the work twice.

    python examples/errors_and_retries.py https://example.com
"""

import sys
import uuid

from scrawl import (
    APIConnectionError,
    AuthenticationError,
    ErrorCode,
    NotFoundError,
    RateLimitError,
    Scrawl,
    ScrawlError,
    ServerError,
)

url = sys.argv[1]
# GETs and submits that start work retry 429, 502/503/504 and network errors with backoff (Retry-After
# honoured). Submits carry an Idempotency-Key, so a retry never starts a second job.
with Scrawl(max_retries=3, timeout=90) as client:
    key = uuid.uuid4().hex                                         # your own key: safe to resend after a crash
    first = client.scrape(url, idempotency_key=key)
    again = client.scrape(url, idempotency_key=key)               # replayed by the server, not run again
    print("the same job both times:", first.job_id == again.job_id)

    try:
        client.get_job(f"missing-{uuid.uuid4().hex}")
    except NotFoundError as error:                                 # unknown, or not yours: never distinguished
        print(f"not found: code={error.code} request={error.request_id}")

    try:
        client.scrape(url, formats=["json"], instruction="The page title")
    except RateLimitError as error:
        print(f"rate limited ({error.code}); retry after {error.retry_after} s")
    except AuthenticationError:
        sys.exit("the API key was refused: check SCRAWL_API_KEY")
    except ServerError as error:
        if not str(error.code or "").startswith("ai_"):
            raise
        print(f"your AI provider failed: {error.code}")            # fix the profile, then retry
    except APIConnectionError as error:
        sys.exit(f"no response from the server: {error}")
    except ScrawlError as error:                                   # every other refusal, with its stable code
        if error.code == ErrorCode.FORBIDDEN:
            print("this key lacks the ai:use scope (or BYO AI is off on this server)")
        else:
            print(f"refused: {error}")
