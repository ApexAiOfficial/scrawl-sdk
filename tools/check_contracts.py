#!/usr/bin/env python3
"""Does an ApexAPI contract still serve what the Scrawl SDKs send?

One checker, three users:

* The SDK test suites (Python imports this module; TypeScript runs it as a program) check that every
  ApexAPI operation is covered or deliberately excluded in ``coverage.json``, and that every request an
  SDK records (path, query parameters, JSON body fields, enum values, required fields, the
  ``Idempotency-Key`` header) matches the contract and the coverage declaration.
* The backend's CI runs ``compat`` against a new OpenAPI document before it ships: an operation, field,
  enum value or ``Idempotency-Key`` that a released SDK sends and that disappears fails the build, as does
  a new required field the SDK does not send. New operations are only reported.
* ``manifest`` verifies ``contracts/MANIFEST.json`` (per-file SHA-256 and the contract digest).
* ``coverage`` also reads the backend's error catalogue (``contracts/apexapi_errors.json``) strictly: every code
  in it must be in ``coverage.json`` ``error_codes`` with the same HTTP status and ``retryable`` flag.

Standard library only, Python 3.10+. Exit codes: 0 ok, 1 problems found, 2 usage error.

    python tools/check_contracts.py coverage [--contracts DIR]
    python tools/check_contracts.py compat --openapi path/to/new/apexapi_openapi.json
    python tools/check_contracts.py requests recorded.json
    python tools/check_contracts.py manifest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
OPENAPI = CONTRACTS / "apexapi_openapi.json"
COVERAGE = ROOT / "coverage.json"
MANIFEST_NAME = "MANIFEST.json"
DIGEST_ALGORITHM = "sha256sum-listing-v1"
ERROR_CATALOGUE = "apexapi_errors.json"
CATALOGUE_SCHEMA_VERSION = 1
CATALOGUE_KEYS = ("schema_version", "fields", "surfaces", "errors")
CATALOGUE_ENTRY_KEYS = ("code", "http_status", "retryable", "description", "surfaces")
_CODE = re.compile(r"[a-z][a-z0-9_]{0,63}")
HTTP_METHODS = ("get", "put", "post", "delete", "patch", "head", "options")
SDK_KEYS = ("python", "typescript", "cli")


# -- loading ---------------------------------------------------------------------------------------

def load_json(path: str | Path) -> Any:
    """Parse a JSON file (UTF-8)."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def operations(openapi: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Every operation of an OpenAPI document, keyed ``"METHOD /path"``."""
    found: dict[str, dict[str, Any]] = {}
    for path, item in (openapi.get("paths") or {}).items():
        for method, op in item.items():
            if method in HTTP_METHODS and isinstance(op, dict):
                found[f"{method.upper()} {path}"] = op
    return found


def split_route(route: str) -> tuple[str, str]:
    method, _, path = route.partition(" ")
    return method.upper(), path


def resolve(openapi: Mapping[str, Any], schema: Any) -> Any:
    """Follow ``$ref`` and pick the meaningful variant of a nullable ``anyOf``."""
    seen = 0
    while isinstance(schema, dict):
        seen += 1
        if seen > 64:
            raise ValueError("schema $ref chain is too deep")
        if "$ref" in schema:
            node: Any = openapi
            for key in schema["$ref"].lstrip("#/").split("/"):
                node = node[key]
            schema = node
            continue
        variants = schema.get("anyOf") or schema.get("oneOf")
        if variants:
            useful = [v for v in variants if not (isinstance(v, dict) and v.get("type") == "null")]
            if len(useful) == 1:
                schema = useful[0]
                continue
        return schema
    return schema


def enum_of(openapi: Mapping[str, Any], schema: Any) -> list[Any] | None:
    """The values an (optionally nullable, optionally array) schema allows, or None when it is no enum."""
    resolved = resolve(openapi, schema)
    if not isinstance(resolved, dict):
        return None
    if "enum" in resolved:
        return list(resolved["enum"])
    if "const" in resolved:
        return [resolved["const"]]
    if resolved.get("type") == "array" and "items" in resolved:
        return enum_of(openapi, resolved["items"])
    return None


def body_schema(openapi: Mapping[str, Any], op: Mapping[str, Any]) -> dict[str, Any] | None:
    """The resolved JSON request-body schema of an operation, or None when it takes no JSON body."""
    content = ((op.get("requestBody") or {}).get("content") or {}).get("application/json")
    if not content:
        return None
    resolved = resolve(openapi, content.get("schema"))
    return resolved if isinstance(resolved, dict) else None


def body_required(op: Mapping[str, Any]) -> bool:
    return bool((op.get("requestBody") or {}).get("required"))


def params_in(op: Mapping[str, Any], where: str) -> dict[str, dict[str, Any]]:
    return {p["name"]: p for p in op.get("parameters") or [] if p.get("in") == where}


def accepts_idempotency_key(op: Mapping[str, Any]) -> bool:
    return any(name.lower() == "idempotency-key" for name in params_in(op, "header"))


def path_pattern(template: str) -> re.Pattern[str]:
    """A regex for a path template: each ``{param}`` is one non-empty segment."""
    parts = re.split(r"(\{[^}]+\})", template)
    return re.compile("^" + "".join("[^/]+" if p.startswith("{") else re.escape(p) for p in parts) + "$")


# -- what an SDK declares and sends ----------------------------------------------------------------

def _field_schema(openapi: Mapping[str, Any], op: Mapping[str, Any], where: str, name: str) -> Any:
    if where == "query":
        param = params_in(op, "query").get(name)
        return param.get("schema") if param else None
    schema = body_schema(openapi, op) or {}
    return (schema.get("properties") or {}).get(name)


def check_declared(openapi: Mapping[str, Any], route: str, sends: Mapping[str, Any]) -> list[str]:
    """Problems with a coverage ``sends`` declaration for ROUTE against the contract."""
    ops = operations(openapi)
    op = ops.get(route)
    if op is None:
        return [f"{route}: the contract has no such operation"]
    problems: list[str] = []
    query = list(sends.get("query") or [])
    known_query = params_in(op, "query")
    for name in query:
        if name not in known_query:
            problems.append(f"{route}: query parameter {name!r} is not in the contract")
    for name, param in known_query.items():
        if param.get("required") and name not in query:
            problems.append(f"{route}: the contract requires query parameter {name!r}, which the SDK never sends")

    body = sends.get("body")
    schema = body_schema(openapi, op)
    if body is None:
        if body_required(op):
            problems.append(f"{route}: the contract requires a JSON body, which the SDK never sends")
    elif schema is None:
        problems.append(f"{route}: the SDK sends a JSON body, but the contract takes none")
    else:
        properties = schema.get("properties") or {}
        for name in body:
            if name not in properties and not schema.get("additionalProperties"):
                problems.append(f"{route}: body field {name!r} is not in the contract")
        for name in schema.get("required") or []:
            if name not in body:
                problems.append(f"{route}: the contract requires body field {name!r}, which the SDK never sends")

    if sends.get("idempotency_key") and not accepts_idempotency_key(op):
        problems.append(f"{route}: the SDK sends Idempotency-Key, which the contract no longer accepts")

    for name, values in (sends.get("enums") or {}).items():
        where = "query" if name in query else "body"
        if where == "body" and name not in (body or []):
            problems.append(f"{route}: enum {name!r} is declared but the SDK never sends that field")
            continue
        allowed = enum_of(openapi, _field_schema(openapi, op, where, name))
        if allowed is None:
            continue                                   # no longer an enum: any value is accepted
        for value in values:
            if value not in allowed:
                problems.append(f"{route}: {where} {name!r} value {value!r} is not one of {allowed}")
    return problems


def _query_values(value: Any) -> list[Any]:
    values = value if isinstance(value, list) else [value]
    out: list[Any] = []
    for item in values:
        out.extend(item.split(",") if isinstance(item, str) and "," in item else [item])
    return out


def check_request(openapi: Mapping[str, Any], route: str, request: Mapping[str, Any],
                  sends: Mapping[str, Any] | None = None, *, exact: bool = False) -> list[str]:
    """Problems with one recorded request for ROUTE.

    REQUEST is ``{"method", "path", "query": {name: value | [values]}, "body": dict | None,
    "headers": {name: value}}``. With SENDS (the coverage declaration), the request may only use what
    it declares; with EXACT it must use all of it (a call with every option set).
    """
    ops = operations(openapi)
    op = ops.get(route)
    if op is None:
        return [f"{route}: the contract has no such operation"]
    method, template = split_route(route)
    problems: list[str] = []
    if str(request.get("method", "")).upper() != method:
        problems.append(f"{route}: sent {request.get('method')!r}, the contract says {method}")
    if not path_pattern(template).match(str(request.get("path", ""))):
        problems.append(f"{route}: path {request.get('path')!r} does not match {template}")

    query = dict(request.get("query") or {})
    known_query = params_in(op, "query")
    for name, value in query.items():
        param = known_query.get(name)
        if param is None:
            problems.append(f"{route}: query parameter {name!r} is not in the contract")
            continue
        allowed = enum_of(openapi, param.get("schema"))
        if allowed is not None:
            for item in _query_values(value):
                if item not in allowed:
                    problems.append(f"{route}: query {name!r} value {item!r} is not one of {allowed}")
    for name, param in known_query.items():
        if param.get("required") and name not in query:
            problems.append(f"{route}: required query parameter {name!r} is missing")

    body = request.get("body")
    schema = body_schema(openapi, op)
    if body is None:
        if body_required(op):
            problems.append(f"{route}: the contract requires a JSON body")
    elif schema is None:
        problems.append(f"{route}: a JSON body was sent, but the contract takes none")
    elif not isinstance(body, dict):
        problems.append(f"{route}: the JSON body is not an object")
    else:
        properties = schema.get("properties") or {}
        for name, value in body.items():
            if name not in properties:
                if not schema.get("additionalProperties"):
                    problems.append(f"{route}: body field {name!r} is not in the contract")
                continue
            allowed = enum_of(openapi, properties[name])
            if allowed is not None and value is not None:
                for item in value if isinstance(value, list) else [value]:
                    if item not in allowed:
                        problems.append(f"{route}: body {name!r} value {item!r} is not one of {allowed}")
        for name in schema.get("required") or []:
            if name not in body:
                problems.append(f"{route}: required body field {name!r} is missing")

    headers = {str(k).lower(): v for k, v in (request.get("headers") or {}).items()}
    keyed = bool(headers.get("idempotency-key"))
    if keyed and not accepts_idempotency_key(op):
        problems.append(f"{route}: Idempotency-Key was sent, but the contract does not accept it")

    if sends is not None:
        problems.extend(_against_declaration(route, query, body, keyed, bool(headers.get("authorization")),
                                             sends, exact=exact))
    return problems


def _against_declaration(route: str, query: Mapping[str, Any], body: Any, keyed: bool, authed: bool,
                         sends: Mapping[str, Any], *, exact: bool) -> list[str]:
    problems: list[str] = []
    declared_query = set(sends.get("query") or [])
    declared_body = None if sends.get("body") is None else set(sends["body"])
    sent_body = set(body) if isinstance(body, dict) else None
    if not set(query) <= declared_query:
        problems.append(f"{route}: sent query {sorted(set(query) - declared_query)} not declared in coverage.json")
    if sent_body is not None and (declared_body is None or not sent_body <= declared_body):
        extra = sorted(sent_body - (declared_body or set()))
        problems.append(f"{route}: sent body fields {extra} not declared in coverage.json")
    if keyed != bool(sends.get("idempotency_key")):
        problems.append(f"{route}: Idempotency-Key sent={keyed}, coverage.json says {bool(sends.get('idempotency_key'))}")
    if authed != bool(sends.get("auth", True)):
        problems.append(f"{route}: Authorization sent={authed}, coverage.json says {bool(sends.get('auth', True))}")
    for name, values in (sends.get("enums") or {}).items():
        sent = query.get(name) if name in query else (body or {}).get(name) if isinstance(body, dict) else None
        if sent is None:
            continue
        items = _query_values(sent) if name in query else (sent if isinstance(sent, list) else [sent])
        for item in items:
            if item not in values:
                problems.append(f"{route}: {name}={item!r} is not among the values coverage.json declares {values}")
    if exact:
        if set(query) != declared_query:
            problems.append(f"{route}: a call with every option set sent query {sorted(query)}, "
                            f"coverage.json declares {sorted(declared_query)}")
        if sent_body != declared_body:
            problems.append(f"{route}: a call with every option set sent body {sorted(sent_body or [])}, "
                            f"coverage.json declares {sorted(declared_body or [])}")
    return problems


def check_response(openapi: Mapping[str, Any], route: str, status: int, body: Any) -> list[str]:
    """Problems with a (fake) response body: the contract's required top-level fields must be present."""
    op = operations(openapi).get(route)
    if op is None:
        return [f"{route}: the contract has no such operation"]
    response = (op.get("responses") or {}).get(str(status))
    if response is None:
        return [] if status >= 400 else [f"{route}: the contract documents no {status} response"]
    content = (response.get("content") or {}).get("application/json")
    schema = resolve(openapi, content.get("schema")) if content else None
    if not isinstance(schema, dict) or not isinstance(body, dict):
        return []
    return [f"{route}: {status} response lacks required field {name!r}"
            for name in schema.get("required") or [] if name not in body]


# -- coverage.json ------------------------------------------------------------------------------------

def _entry_problems(route: str, entry: Any) -> list[str]:
    if not isinstance(entry, dict):
        return [f"{route}: coverage entry must be an object"]
    if "excluded" in entry:
        reason = entry["excluded"]
        if not isinstance(reason, str) or len(reason.strip()) < 10:
            return [f"{route}: an exclusion needs a reason"]
        return []
    problems = []
    for key in SDK_KEYS:
        value = entry.get(key)
        if not isinstance(value, str) or not value.strip():
            problems.append(f"{route}: coverage needs a {key} method/command (or the whole route excluded)")
    if not isinstance(entry.get("sends"), dict):
        problems.append(f"{route}: coverage needs a 'sends' declaration")
    return problems


def check_coverage(openapi: Mapping[str, Any], coverage: Mapping[str, Any],
                   contracts_dir: Path = CONTRACTS) -> list[str]:
    """Strict SDK-side check: every operation is covered or excluded, every declaration holds, and every
    code of the error catalogue in CONTRACTS_DIR (when there is one) is known with its status and flag."""
    ops = operations(openapi)
    declared = coverage.get("operations") or {}
    problems: list[str] = []
    for route in sorted(set(ops) - set(declared)):
        problems.append(f"{route}: new operation; add an SDK method and CLI command, or exclude it with a reason")
    for route in sorted(set(declared) - set(ops)):
        problems.append(f"{route}: coverage.json lists an operation the contract no longer has")
    for route, entry in sorted(declared.items()):
        problems.extend(_entry_problems(route, entry))
        if route in ops and isinstance(entry, dict) and "excluded" not in entry and isinstance(entry.get("sends"), dict):
            problems.extend(check_declared(openapi, route, entry["sends"]))
    problems.extend(check_error_catalogue(coverage, contracts_dir))
    return problems


def check_compat(openapi: Mapping[str, Any], coverage: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    """Backend-side check: would this contract break what the SDK at ``coverage`` sends? (problems, notes)."""
    ops = operations(openapi)
    declared = coverage.get("operations") or {}
    problems: list[str] = []
    notes: list[str] = []
    for route, entry in sorted(declared.items()):
        if not isinstance(entry, dict):
            continue
        if "excluded" in entry:
            if route not in ops:
                notes.append(f"{route}: excluded operation removed (no SDK impact)")
            continue
        if route not in ops:
            problems.append(f"{route}: removed, but the SDK calls it ({entry.get('python')} / {entry.get('typescript')})")
            continue
        problems.extend(check_declared(openapi, route, entry.get("sends") or {}))
    for route in sorted(set(ops) - set(declared)):
        notes.append(f"{route}: new operation; the SDK does not cover it yet")
    return problems, notes


class CatalogueError(ValueError):
    """The error catalogue is not in the one format this tool reads."""


def _names(keys: Iterable[str]) -> str:
    keys = sorted(keys)
    return ("key " if len(keys) == 1 else "keys ") + ", ".join(repr(key) for key in keys)


def _exact_keys(where: str, value: Mapping[str, Any], expected: Iterable[str]) -> None:
    expected = set(expected)
    problems = []
    if expected - set(value):
        problems.append(f"missing {_names(expected - set(value))}")
    if set(value) - expected:
        problems.append(f"unexpected {_names(set(value) - expected)}")
    if problems:
        raise CatalogueError(f"{where}: {'; '.join(problems)}")


def _glossary(where: str, value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or not value or not all(
            isinstance(k, str) and k and isinstance(v, str) and v.strip() for k, v in value.items()):
        raise CatalogueError(f"{where} must be a non-empty map of names to descriptions")
    return value


def error_catalogue_codes(catalogue: Any) -> dict[str, dict[str, Any]]:
    """The codes of the backend's error catalogue, keyed by code, in catalogue order; strict about its shape.

    The catalogue is ``{"schema_version": 1, "fields": {name: text}, "surfaces": {name: text}, "errors":
    [{"code", "http_status": int | null, "retryable": bool, "description", "surfaces": [name, ...]}]}``.
    Anything else (a missing or extra key, a wrong type, a duplicate code, a surface the glossary does not
    define, an ``apexapi`` error without an HTTP status, another schema version) raises ``CatalogueError``:
    a format this tool does not know is refused, never guessed at.
    """
    if not isinstance(catalogue, dict):
        raise CatalogueError("the catalogue must be a JSON object")
    _exact_keys("the catalogue", catalogue, CATALOGUE_KEYS)
    version = catalogue["schema_version"]
    if type(version) is not int or version != CATALOGUE_SCHEMA_VERSION:
        raise CatalogueError(f"schema_version {version!r} is not {CATALOGUE_SCHEMA_VERSION}, the one this tool reads")
    fields = _glossary("'fields'", catalogue["fields"])
    unknown_fields = set(fields) - set(CATALOGUE_ENTRY_KEYS)
    if unknown_fields:
        raise CatalogueError(f"'fields' documents {_names(unknown_fields)} that no error entry has")
    surfaces = _glossary("'surfaces'", catalogue["surfaces"])
    errors = catalogue["errors"]
    if not isinstance(errors, list) or not errors:
        raise CatalogueError("'errors' must be a non-empty list")
    codes: dict[str, dict[str, Any]] = {}
    for index, entry in enumerate(errors):
        where = f"errors[{index}]"
        if not isinstance(entry, dict):
            raise CatalogueError(f"{where} must be an object")
        code = entry.get("code")
        if not isinstance(code, str) or not _CODE.fullmatch(code):
            raise CatalogueError(f"{where}: 'code' must be a snake_case string, not {code!r}")
        where = f"{where} ({code})"
        _exact_keys(where, entry, CATALOGUE_ENTRY_KEYS)
        if code in codes:
            raise CatalogueError(f"{where}: duplicate code {code!r}")
        status = entry["http_status"]
        if status is not None and (type(status) is not int or not 100 <= status <= 599):
            raise CatalogueError(f"{where}: http_status must be an HTTP status or null, not {status!r}")
        if type(entry["retryable"]) is not bool:
            raise CatalogueError(f"{where}: retryable must be true or false, not {entry['retryable']!r}")
        if not isinstance(entry["description"], str) or not entry["description"].strip():
            raise CatalogueError(f"{where}: description must be non-empty text")
        listed = entry["surfaces"]
        if not isinstance(listed, list) or not listed or not all(isinstance(s, str) for s in listed) \
                or len(set(listed)) != len(listed):
            raise CatalogueError(f"{where}: surfaces must be a non-empty list of distinct names")
        for surface in listed:
            if surface not in surfaces:
                raise CatalogueError(f"{where}: unknown surface {surface!r} (not in the 'surfaces' glossary)")
        if "apexapi" in listed and status is None:
            raise CatalogueError(f"{where}: an apexapi error needs an http_status")
        codes[code] = entry
    return codes


def check_error_catalogue(coverage: Mapping[str, Any], contracts_dir: Path = CONTRACTS) -> list[str]:
    """When the backend's error catalogue is vendored, ``coverage.json`` ``error_codes`` must mirror it.

    Every catalogue code is listed with the catalogue's HTTP status and ``retryable`` flag; a listed code the
    catalogue lacks must be an SDK-only code (``"source": "sdk"``). A catalogue of any other shape is a problem.
    """
    path = contracts_dir / ERROR_CATALOGUE
    if not path.exists():
        return []
    try:
        catalogue = error_catalogue_codes(load_json(path))
    except ValueError as exc:                                   # CatalogueError, or not JSON at all
        return [f"{ERROR_CATALOGUE}: {exc}"]
    known = coverage.get("error_codes")
    if not isinstance(known, dict):
        return ["coverage.json needs an error_codes map"]
    problems = [f"error code {code!r} is in the catalogue but not in coverage.json error_codes"
                for code in catalogue if code not in known]
    for code, ours in known.items():
        if not isinstance(ours, dict):
            problems.append(f"error code {code!r}: the coverage.json entry must be an object")
            continue
        entry = catalogue.get(code)
        sdk_only = ours.get("source") == "sdk"
        if entry is None:
            if not sdk_only:
                problems.append(f"error code {code!r} is in coverage.json but not in the catalogue "
                                '(an SDK-only code says "source": "sdk")')
            elif type(ours.get("retryable")) is not bool:
                problems.append(f"error code {code!r}: coverage.json needs retryable true or false")
            continue
        if sdk_only:
            problems.append(f'error code {code!r} is in the catalogue, so coverage.json must not mark it "source": "sdk"')
            continue
        if ours.get("status") != entry["http_status"]:
            problems.append(f"error code {code!r}: the catalogue says http_status {_json(entry['http_status'])}, "
                            f"coverage.json says status {_json(ours.get('status'))}")
        if type(ours.get("retryable")) is not bool:
            problems.append(f"error code {code!r}: coverage.json needs retryable {_json(entry['retryable'])} or "
                            f"{_json(not entry['retryable'])}")
        elif ours["retryable"] is not entry["retryable"]:
            problems.append(f"error code {code!r}: the catalogue says retryable {_json(entry['retryable'])}, "
                            f"coverage.json says {_json(ours['retryable'])}")
    return problems


def _json(value: Any) -> str:
    return json.dumps(value)


# -- MANIFEST.json ---------------------------------------------------------------------------------------

def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def contract_digest(file_hashes: Mapping[str, str]) -> str:
    """The contract digest: SHA-256 of the ``sha256sum`` listing of the files, sorted by name.

    Reproducible with shell tools (byte order, hence ``LC_ALL=C``):
    ``cd contracts && LC_ALL=C sh -c 'sha256sum $(ls | grep -v MANIFEST.json | sort) | sha256sum'``.
    """
    listing = "".join(f"{file_hashes[name]}  {name}\n" for name in sorted(file_hashes))
    return "sha256:" + hashlib.sha256(listing.encode("utf-8")).hexdigest()


def build_manifest(contracts_dir: Path, *, source: Mapping[str, Any]) -> dict[str, Any]:
    """A MANIFEST for every file in CONTRACTS_DIR (except the manifest itself)."""
    files = {}
    for path in sorted(contracts_dir.iterdir()):
        if path.name == MANIFEST_NAME or path.name.startswith(".") or not path.is_file():
            continue
        files[path.name] = {"sha256": sha256_file(path), "bytes": path.stat().st_size}
    return {
        "format": 1,
        "source": dict(source),
        "digest_algorithm": DIGEST_ALGORITHM,
        "digest": contract_digest({name: entry["sha256"] for name, entry in files.items()}),
        "files": files,
    }


def verify_manifest(contracts_dir: Path = CONTRACTS) -> list[str]:
    """Problems with ``MANIFEST.json``: missing, extra or changed files, or a wrong digest."""
    path = contracts_dir / MANIFEST_NAME
    if not path.exists():
        return [f"{path.name} is missing"]
    manifest = load_json(path)
    problems = []
    listed = manifest.get("files") or {}
    present = {p.name for p in contracts_dir.iterdir()
               if p.is_file() and p.name != MANIFEST_NAME and not p.name.startswith(".")}
    for name in sorted(present - set(listed)):
        problems.append(f"{name} is not listed in {MANIFEST_NAME}")
    for name, entry in sorted(listed.items()):
        file = contracts_dir / name
        if not file.is_file():
            problems.append(f"{name} is listed in {MANIFEST_NAME} but missing")
        elif sha256_file(file) != entry.get("sha256"):
            problems.append(f"{name}: sha256 does not match {MANIFEST_NAME} (edit contracts only through tools/sync_contracts.py)")
    if manifest.get("digest_algorithm") != DIGEST_ALGORITHM:
        problems.append(f"{MANIFEST_NAME}: unknown digest_algorithm {manifest.get('digest_algorithm')!r}")
    expected = contract_digest({name: entry.get("sha256", "") for name, entry in listed.items()})
    if manifest.get("digest") != expected:
        problems.append(f"{MANIFEST_NAME}: digest {manifest.get('digest')} != {expected}")
    return problems


def manifest_digest(contracts_dir: Path = CONTRACTS) -> str:
    """The digest recorded in ``MANIFEST.json``."""
    return str(load_json(contracts_dir / MANIFEST_NAME)["digest"])


# -- command line ----------------------------------------------------------------------------------------

def _report(problems: list[str], notes: list[str] | None = None, *, ok: str) -> int:
    for note in notes or []:
        print(f"note: {note}")
    for problem in problems:
        print(f"problem: {problem}", file=sys.stderr)
    if problems:
        print(f"{len(problems)} problem(s)", file=sys.stderr)
        return 1
    print(ok)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_contracts", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name, text in (("coverage", "every operation covered or excluded; declarations match the contract"),
                       ("compat", "would OPENAPI break what this SDK version sends? (backend CI)")):
        p = sub.add_parser(name, help=text)
        p.add_argument("--openapi", default=str(OPENAPI))
        p.add_argument("--coverage", default=str(COVERAGE))
        if name == "coverage":
            p.add_argument("--contracts", default=str(CONTRACTS), help=f"the directory holding {ERROR_CATALOGUE}")
    p = sub.add_parser("requests", help="check recorded requests: [{route, request, exact?}]")
    p.add_argument("file")
    p.add_argument("--openapi", default=str(OPENAPI))
    p.add_argument("--coverage", default=str(COVERAGE))
    p = sub.add_parser("manifest", help="verify contracts/MANIFEST.json")
    p.add_argument("--contracts", default=str(CONTRACTS))
    args = parser.parse_args(argv)

    try:
        if args.command == "manifest":
            return _report(verify_manifest(Path(args.contracts)), ok=f"manifest ok: {manifest_digest(Path(args.contracts))}")
        openapi = load_json(args.openapi)
        coverage = load_json(args.coverage)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.command == "coverage":
        return _report(check_coverage(openapi, coverage, Path(args.contracts)),
                       ok=f"coverage ok: {len(operations(openapi))} operations")
    if args.command == "compat":
        problems, notes = check_compat(openapi, coverage)
        return _report(problems, notes, ok="compatible: every operation and field this SDK sends is still served")
    try:
        recorded = load_json(args.file)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    declared = coverage.get("operations") or {}
    problems = []
    for item in recorded:
        route = item["route"]
        sends = (declared.get(route) or {}).get("sends")
        if sends is None:
            problems.append(f"{route}: not a covered operation in coverage.json")
            continue
        problems.extend(check_request(openapi, route, item["request"], sends, exact=bool(item.get("exact"))))
    return _report(problems, ok=f"requests ok: {len(recorded)} checked")


if __name__ == "__main__":
    sys.exit(main())
