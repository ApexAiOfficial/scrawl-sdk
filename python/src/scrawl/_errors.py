"""Typed errors carrying the API's stable error ``code`` (never the API key)."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from types import MappingProxyType
from typing import Any


class ErrorCode(str, Enum):
    """Every code in the backend's error catalogue, plus the SDK's own ``render_not_supported``.

    Most are ApexAPI errors, raised as a ``ScrawlError``; some only appear as the ``error_code`` of a failed
    result (``fetch_failed``, ``settlement_failed``...) or only on the MCP server (``key_revoked``...).
    ``ScrawlError.code`` is a plain string, so it compares equal to these members
    (``error.code == ErrorCode.NOT_FOUND``) and stays readable when the API adds a code this SDK
    version does not list yet. The table with each code's status, retryability and meaning is ``docs/errors.md``.
    """

    BAD_REQUEST = "bad_request"
    DISPATCH_REFUSED = "dispatch_refused"
    EGRESS_REQUIRED = "egress_required"
    ERROR = "error"
    INVALID_TOKEN = "invalid_token"
    UNAUTHORIZED = "unauthorized"
    INSUFFICIENT_CREDITS = "insufficient_credits"
    ACCOUNT_NOT_ACTIVE = "account_not_active"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    CONFLICT = "conflict"
    PAYLOAD_TOO_LARGE = "payload_too_large"
    UNSUPPORTED_MEDIA_TYPE = "unsupported_media_type"
    BUDGET_EXCEEDED = "budget_exceeded"
    INVALID_ARTIFACT_NAME = "invalid_artifact_name"
    INVALID_REQUEST = "invalid_request"
    UNSAFE_ARTIFACT_PATH = "unsafe_artifact_path"
    RATE_LIMITED = "rate_limited"
    TOO_MANY_ACTIVE_JOBS = "too_many_active_jobs"
    INTERNAL_ERROR = "internal_error"
    SUBMISSION_FAILED = "submission_failed"
    AI_AUTH = "ai_auth"
    AI_BAD_REQUEST = "ai_bad_request"
    AI_CONTEXT_OVERFLOW = "ai_context_overflow"
    AI_ENDPOINT_FORBIDDEN = "ai_endpoint_forbidden"
    AI_MALFORMED_OUTPUT = "ai_malformed_output"
    AI_PROVIDER_ERROR = "ai_provider_error"
    AI_QUOTA = "ai_quota"
    AI_RATE_LIMITED = "ai_rate_limited"
    AI_REFUSED = "ai_refused"
    AI_TIMEOUT = "ai_timeout"
    AI_UNAVAILABLE = "ai_unavailable"
    BROWSER_UNAVAILABLE = "browser_unavailable"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    UNAVAILABLE = "unavailable"
    EGRESS_UNAVAILABLE = "egress_unavailable"
    FETCH_FAILED = "fetch_failed"
    INTERNAL = "internal"
    INTERRUPTED = "interrupted"
    JOB_TIMEOUT = "job_timeout"
    KEY_REVOKED = "key_revoked"
    LISTEN_EXPIRED = "listen_expired"
    PREFLIGHT_DENIED = "preflight_denied"
    RENDER_INTERRUPTED = "render_interrupted"
    SETTLEMENT_FAILED = "settlement_failed"
    TOO_MANY_STREAMS = "too_many_streams"
    RENDER_NOT_SUPPORTED = "render_not_supported"

    def __str__(self) -> str:
        return self.value


#: The catalogue's ``retryable`` flag of every ``ErrorCode``: whether the same request can succeed if sent again
#: later unchanged. The SDKs never retry automatically on a code marked ``False`` (``submission_failed`` and
#: ``settlement_failed`` above all: a resend may charge twice), and retry a ``True`` one only where the HTTP status
#: allows it (``_client``). Kept equal to ``contracts/apexapi_errors.json`` and the TypeScript SDK by the tests.
RETRYABLE: Mapping[str, bool] = MappingProxyType({
    "bad_request": False,
    "dispatch_refused": False,
    "egress_required": False,
    "error": False,
    "invalid_token": False,
    "unauthorized": False,
    "insufficient_credits": False,
    "account_not_active": False,
    "forbidden": False,
    "not_found": False,
    "method_not_allowed": False,
    "conflict": True,
    "payload_too_large": False,
    "unsupported_media_type": False,
    "budget_exceeded": False,
    "invalid_artifact_name": False,
    "invalid_request": False,
    "unsafe_artifact_path": False,
    "rate_limited": True,
    "too_many_active_jobs": True,
    "internal_error": True,
    "submission_failed": False,
    "ai_auth": False,
    "ai_bad_request": False,
    "ai_context_overflow": False,
    "ai_endpoint_forbidden": False,
    "ai_malformed_output": False,
    "ai_provider_error": False,
    "ai_quota": False,
    "ai_rate_limited": True,
    "ai_refused": False,
    "ai_timeout": True,
    "ai_unavailable": True,
    "browser_unavailable": False,
    "temporarily_unavailable": True,
    "unavailable": True,
    "egress_unavailable": True,
    "fetch_failed": True,
    "internal": True,
    "interrupted": True,
    "job_timeout": True,
    "key_revoked": False,
    "listen_expired": True,
    "preflight_denied": False,
    "render_interrupted": True,
    "settlement_failed": False,
    "too_many_streams": True,
    "render_not_supported": False,
})


def never_retry(code: object) -> bool:
    """True when the error catalogue marks CODE not retryable: the SDKs then never resend the request.

    A code this SDK version does not know (a newer server's) is not refused here; the HTTP status decides.
    """
    return isinstance(code, str) and RETRYABLE.get(str(code)) is False


def code_of(body: Any) -> str | None:
    """The error code of an API error body, in either shape: ``{"error": {"code"...}}`` or ``{"detail", "code"}``."""
    if not isinstance(body, dict):
        return None
    envelope = body.get("error")
    code = envelope.get("code") if isinstance(envelope, dict) else body.get("code")
    return code if isinstance(code, str) else None


class ScrawlError(Exception):
    """Any failed Scrawl call. ``code`` is the API's stable machine code (e.g. ``"not_found"``)."""

    def __init__(self, message: str, *, status: int | None = None, code: str | None = None,
                 request_id: str | None = None, details: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = str(code) if code is not None else None
        self.request_id = request_id
        self.details = details

    def __str__(self) -> str:
        parts = [self.message]
        if self.code:
            parts.insert(0, f"[{self.code}]")
        if self.request_id:
            parts.append(f"(request {self.request_id})")
        return " ".join(parts)


class ConfigurationError(ScrawlError):
    """The client cannot be used as configured (no API key, an unusable base URL); nothing was sent."""


class BadRequestError(ScrawlError):
    """400: refused before any work started (``egress_required``, ``dispatch_refused``, ``bad_request``)."""


class AuthenticationError(ScrawlError):
    """401: missing, invalid or revoked API key."""


class PaymentRequiredError(ScrawlError):
    """402: ``insufficient_credits``; the hosted account cannot cover this job."""


class PermissionDeniedError(ScrawlError):
    """403: the key lacks the scope, or the server has the feature turned off."""


class NotFoundError(ScrawlError):
    """404: unknown or not yours (Scrawl never reveals other owners' resources)."""


class ConflictError(ScrawlError):
    """409: e.g. an Idempotency-Key whose first request is still running."""


class ValidationError(ScrawlError):
    """422: the request is invalid (or an Idempotency-Key was reused for a different request)."""


class RateLimitError(ScrawlError):
    """429: rate limited or ``too_many_active_jobs``; ``retry_after`` is in seconds when the API says."""

    def __init__(self, message: str, *, retry_after: float | None = None, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.retry_after = retry_after


class ServerError(ScrawlError):
    """5xx from Scrawl (including ``ai_*`` failures of your own AI provider, which are 502)."""


class APIConnectionError(ScrawlError):
    """The request never got a response (network, DNS, TLS)."""


class APITimeoutError(APIConnectionError):
    """The request timed out."""


_BY_STATUS: dict[int, type[ScrawlError]] = {
    400: BadRequestError, 401: AuthenticationError, 402: PaymentRequiredError, 403: PermissionDeniedError,
    404: NotFoundError, 409: ConflictError, 422: ValidationError, 429: RateLimitError,
}


def error_for(status: int, body: Any, *, request_id: str | None, retry_after: float | None) -> ScrawlError:
    """Map an HTTP error response to the matching ``ScrawlError`` subclass.

    Reads both shapes the API uses: ``{"error": {"code", "message", "request_id", "details"?}}`` and
    ``{"detail": ..., "code": ...}``. The ``X-Request-ID`` header wins; the envelope's ``request_id`` is
    the fallback (e.g. behind a proxy that drops headers).
    """
    code, message, details = None, None, None
    if isinstance(body, dict):
        envelope = body.get("error") if isinstance(body.get("error"), dict) else None
        if envelope:
            code, message, details = envelope.get("code"), envelope.get("message"), envelope.get("details")
            request_id = request_id or envelope.get("request_id") or None
        else:
            code = body.get("code")
            detail = body.get("detail")
            message = detail if isinstance(detail, str) else None
            details = detail if not isinstance(detail, str) else None
    message = message or f"HTTP {status}"
    cls = _BY_STATUS.get(status) or (ServerError if status >= 500 else ScrawlError)
    kwargs: dict[str, Any] = {"status": status, "code": code if isinstance(code, str) else None,
                              "request_id": request_id, "details": details}
    if cls is RateLimitError:
        return RateLimitError(message, retry_after=retry_after, **kwargs)
    return cls(message, **kwargs)
