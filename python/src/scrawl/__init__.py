"""Scrawl Python SDK: URL in, Markdown or structured JSON out — plus map, batch, crawl and datasets.

    from scrawl import Scrawl

    with Scrawl() as client:                      # SCRAWL_API_KEY / SCRAWL_BASE_URL from the environment
        page = client.scrape("https://example.com")
        print(page.markdown)
"""

from ._client import DEFAULT_BASE_URL, AsyncScrawl, Scrawl
from ._contract import CONTRACT_DIGEST
from ._errors import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ConfigurationError,
    ConflictError,
    ErrorCode,
    NotFoundError,
    PaymentRequiredError,
    PermissionDeniedError,
    RateLimitError,
    ScrawlError,
    ServerError,
    ValidationError,
)
from ._objects import ScrawlObject
from ._version import __version__

#: The contract digest (``contracts/MANIFEST.json``) this SDK version was built against.
__contract__ = CONTRACT_DIGEST

__all__ = [
    "CONTRACT_DIGEST",
    "DEFAULT_BASE_URL",
    "APIConnectionError",
    "APITimeoutError",
    "AsyncScrawl",
    "AuthenticationError",
    "BadRequestError",
    "ConfigurationError",
    "ConflictError",
    "ErrorCode",
    "NotFoundError",
    "PaymentRequiredError",
    "PermissionDeniedError",
    "RateLimitError",
    "Scrawl",
    "ScrawlError",
    "ScrawlObject",
    "ServerError",
    "ValidationError",
    "__contract__",
    "__version__",
]
