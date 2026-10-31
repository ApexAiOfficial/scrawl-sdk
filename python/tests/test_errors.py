"""Error mapping: one class per status (400 included), the stable code, the request id from header or body."""

from __future__ import annotations

import json
import shutil
import subprocess

import check_contracts
import httpx
import pytest
from conftest import COVERAGE, REPO, Recorder, make_client

from scrawl import _errors
from scrawl import (
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

CASES = [(400, BadRequestError), (401, AuthenticationError), (402, PaymentRequiredError),
         (403, PermissionDeniedError), (404, NotFoundError), (409, ConflictError), (422, ValidationError),
         (429, RateLimitError), (500, ServerError), (502, ServerError), (503, ServerError), (418, ScrawlError)]


@pytest.mark.parametrize(("status", "cls"), CASES)
def test_each_status_maps_to_its_class_with_code_message_and_request_id(status: int, cls: type) -> None:
    rec = Recorder(httpx.Response(status, json={"error": {"code": f"c{status}", "message": f"m{status}"}},
                                  headers={"X-Request-ID": "req-1"}))
    with pytest.raises(ScrawlError) as caught:
        make_client(rec, max_retries=0).get_dataset("d1")
    error = caught.value
    assert type(error) is cls
    assert (error.status, error.code, error.message, error.request_id) == (status, f"c{status}", f"m{status}", "req-1")
    assert str(error) == f"[c{status}] m{status} (request req-1)"


def test_a_400_is_a_bad_request_error_with_the_refusal_code() -> None:
    egress = httpx.Response(400, json={"error": {"code": "egress_required", "message": "add a proxy first",
                                                 "request_id": "rq-400"}})
    with pytest.raises(BadRequestError) as caught:
        make_client(Recorder(egress), max_retries=0).extract_assets("https://e.example/page")
    assert caught.value.code == ErrorCode.EGRESS_REQUIRED and caught.value.request_id == "rq-400"
    legacy = httpx.Response(400, json={"detail": "Bad request", "code": "bad_request"})
    with pytest.raises(BadRequestError) as caught:
        make_client(Recorder(legacy), max_retries=0).get_job("j1")
    assert caught.value.code == "bad_request" and caught.value.message == "Bad request"


def test_the_request_id_comes_from_the_header_else_from_the_error_body() -> None:
    body_only = httpx.Response(404, json={"error": {"code": "not_found", "message": "no", "request_id": "from-body"}})
    with pytest.raises(NotFoundError) as caught:
        make_client(Recorder(body_only)).get_job("x")
    assert caught.value.request_id == "from-body"
    both = httpx.Response(404, json={"error": {"code": "not_found", "message": "no", "request_id": "from-body"}},
                          headers={"X-Request-ID": "from-header"})
    with pytest.raises(NotFoundError) as caught:
        make_client(Recorder(both)).get_job("x")
    assert caught.value.request_id == "from-header"


def test_legacy_and_non_json_error_bodies_still_map_cleanly() -> None:
    invalid = httpx.Response(422, json={"detail": [{"loc": ["body", "url"], "msg": "bad"}], "code": "invalid_request"})
    with pytest.raises(ValidationError) as caught:
        make_client(Recorder(invalid)).get_dataset("d1")
    assert caught.value.details == [{"loc": ["body", "url"], "msg": "bad"}] and caught.value.message == "HTTP 422"
    assert caught.value.code == ErrorCode.INVALID_REQUEST
    gateway = httpx.Response(502, text="<html>bad gateway</html>")
    with pytest.raises(ServerError) as caught:
        make_client(Recorder(gateway), max_retries=0).get_dataset("d1")
    assert caught.value.message == "<html>bad gateway</html>" and caught.value.code is None


def test_the_code_is_a_stable_plain_string_even_when_this_sdk_does_not_know_it() -> None:
    rec = Recorder(httpx.Response(409, json={"error": {"code": "a_code_added_later", "message": "x"}}))
    with pytest.raises(ConflictError) as caught:
        make_client(rec).activate_version("d1", "v1")
    assert type(caught.value.code) is str and caught.value.code == "a_code_added_later"
    rec = Recorder(httpx.Response(404, json={"error": {"code": "not_found", "message": "x"}}))
    with pytest.raises(NotFoundError) as caught:
        make_client(rec).get_job("j1")
    assert type(caught.value.code) is str and caught.value.code == ErrorCode.NOT_FOUND


def test_error_code_lists_exactly_the_codes_in_coverage_json() -> None:
    declared = COVERAGE["error_codes"]
    assert {member.value for member in ErrorCode} == set(declared)
    for member in ErrorCode:
        assert member.name == member.value.upper() and str(member) == member.value == f"{member}"


CATALOGUE = check_contracts.error_catalogue_codes(
    check_contracts.load_json(check_contracts.CONTRACTS / check_contracts.ERROR_CATALOGUE))
SDK_ONLY = {code for code, entry in COVERAGE["error_codes"].items() if entry.get("source") == "sdk"}


def test_error_code_is_every_catalogue_code_plus_the_sdk_only_ones() -> None:
    assert SDK_ONLY == {"render_not_supported"}
    assert {member.value for member in ErrorCode} == set(CATALOGUE) | SDK_ONLY


def test_the_retry_table_is_the_catalogues_retryable_flag() -> None:
    expected = {code: entry["retryable"] for code, entry in CATALOGUE.items()} | {code: False for code in SDK_ONLY}
    assert dict(_errors.RETRYABLE) == expected
    for code in ("submission_failed", "settlement_failed", "internal_error", "internal", "unavailable"):
        assert _errors.RETRYABLE[code] is False, code
    with pytest.raises(TypeError):
        _errors.RETRYABLE["submission_failed"] = True                    # type: ignore[index]
    assert _errors.never_retry("submission_failed") and _errors.never_retry(ErrorCode.SETTLEMENT_FAILED)
    assert not _errors.never_retry("rate_limited") and not _errors.never_retry("a_code_added_later")
    assert not _errors.never_retry(None)


def test_python_and_typescript_know_the_same_codes_with_the_same_flags() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed; the TypeScript suite makes the same comparison")
    module = (REPO / "typescript" / "src" / "errors.js").as_uri()
    script = (f"const m = await import({json.dumps(module)});"
              "process.stdout.write(JSON.stringify({codes: m.ErrorCode, retryable: m.RETRYABLE}));")
    out = subprocess.run([node, "--input-type=module", "-e", script], capture_output=True, text=True, check=True)
    typescript = json.loads(out.stdout)
    assert typescript["codes"] == {member.name: member.value for member in ErrorCode}
    assert typescript["retryable"] == dict(_errors.RETRYABLE)


def test_error_classes_form_one_hierarchy() -> None:
    for cls in (ConfigurationError, BadRequestError, AuthenticationError, PaymentRequiredError,
                PermissionDeniedError, NotFoundError, ConflictError, ValidationError, RateLimitError,
                ServerError, APIConnectionError):
        assert issubclass(cls, ScrawlError)
    assert issubclass(APITimeoutError, APIConnectionError)


def test_rate_limit_errors_carry_retry_after() -> None:
    limited = httpx.Response(429, json={"error": {"code": "too_many_active_jobs", "message": "slow down"}},
                             headers={"Retry-After": "7"})
    with pytest.raises(RateLimitError) as caught:
        make_client(Recorder(limited), max_retries=0).get_job("j1")
    assert caught.value.retry_after == 7.0 and caught.value.code == ErrorCode.TOO_MANY_ACTIVE_JOBS
