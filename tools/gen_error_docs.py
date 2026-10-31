#!/usr/bin/env python3
"""Generate the error-code table in ``docs/errors.md`` (between its BEGIN/END markers).

    python tools/gen_error_docs.py           # rewrite the table
    python tools/gen_error_docs.py --check   # exit 1 if the table is out of date (the tests run this)

One row per code of the backend's error catalogue (``contracts/apexapi_errors.json``) and per code of
``coverage.json`` ``error_codes`` (the codes both SDKs expose as ``ErrorCode``, including SDK-only ones). The
HTTP status, the retryable flag, where the code appears and its description come from the catalogue; an
SDK-only code uses its ``coverage.json`` entry. ``check_contracts.py coverage`` keeps the two in step.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_contracts import (  # noqa: E402
    CONTRACTS,
    COVERAGE,
    ERROR_CATALOGUE,
    ROOT,
    CatalogueError,
    error_catalogue_codes,
    load_json,
)

DOC = ROOT / "docs" / "errors.md"
BEGIN = "<!-- BEGIN GENERATED: error codes (tools/gen_error_docs.py) -->"
END = "<!-- END GENERATED: error codes -->"
CLASSES = {400: "BadRequestError", 401: "AuthenticationError", 402: "PaymentRequiredError",
           403: "PermissionDeniedError", 404: "NotFoundError", 409: "ConflictError", 422: "ValidationError",
           429: "RateLimitError"}
#: How the table names each catalogue surface (see the legend in docs/errors.md).
SURFACES = {"apexapi": "API", "result": "result", "mcp": "MCP"}


def _class_for(status: int | None) -> str:
    if status is None:
        return "ScrawlError"
    return CLASSES.get(status) or ("ServerError" if status >= 500 else "ScrawlError")


def _cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def render(coverage: dict[str, Any], catalogue: dict[str, dict[str, Any]] | None = None) -> str:
    """The generated table (markers included). CATALOGUE is ``error_catalogue_codes`` of the vendored file."""
    catalogue = catalogue or {}
    known = coverage.get("error_codes") or {}
    rows = []
    for code in sorted(set(known) | set(catalogue), key=lambda c: (_status(c, known, catalogue) or 999, c)):
        entry = catalogue.get(code)
        ours = known.get(code) or {}
        if entry is not None:
            status, retryable, meaning = entry["http_status"], entry["retryable"], entry["description"]
            where = ", ".join(SURFACES.get(surface, surface) for surface in entry["surfaces"])
            raised = "apexapi" in entry["surfaces"]               # the SDKs raise only ApexAPI errors
        else:
            status, retryable, meaning = ours.get("status"), ours.get("retryable"), ours.get("summary", "")
            where, raised = ("SDK", True) if ours.get("source") == "sdk" else ("?", False)
        cls = f"`{_class_for(status)}`" if raised else "-"
        constant = f"`ErrorCode.{code.upper()}`" if code in known else "-"
        flag = {True: "yes", False: "no"}.get(retryable, "?")
        rows.append(f"| `{code}` | {status if status is not None else 'none'} | {flag} | {where} | {cls} | "
                    f"{constant} | {_cell(meaning)} |")
    source = ("the vendored error catalogue (`contracts/apexapi_errors.json`) and `coverage.json`" if catalogue
              else "`coverage.json` (the vendored contracts carry no error catalogue)")
    return "\n".join([
        BEGIN,
        f"Generated from {source}; do not edit by hand.",
        "",
        "| Code | HTTP | Retryable | Where | Class (both SDKs) | Constant | Meaning |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        *rows,
        END,
    ])


def _status(code: str, known: dict[str, Any], catalogue: dict[str, dict[str, Any]]) -> int | None:
    if code in catalogue:
        return catalogue[code]["http_status"]
    return (known.get(code) or {}).get("status")


def updated(text: str, table: str) -> str:
    start, end = text.find(BEGIN), text.find(END)
    if start < 0 or end < start:
        raise ValueError(f"{DOC.name} lacks the generated-table markers")
    return text[:start] + table + text[end + len(END):]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gen_error_docs", description="Generate the error table in docs/errors.md.")
    parser.add_argument("--check", action="store_true", help="fail if docs/errors.md is out of date")
    args = parser.parse_args(argv)
    path = CONTRACTS / ERROR_CATALOGUE
    try:
        catalogue = error_catalogue_codes(load_json(path)) if path.exists() else None
    except (CatalogueError, ValueError) as exc:
        print(f"error: {ERROR_CATALOGUE}: {exc}", file=sys.stderr)
        return 2
    current = DOC.read_text(encoding="utf-8")
    fresh = updated(current, render(load_json(COVERAGE), catalogue))
    if args.check:
        if fresh != current:
            print("docs/errors.md is out of date: run python tools/gen_error_docs.py", file=sys.stderr)
            return 1
        print("docs/errors.md is up to date")
        return 0
    DOC.write_text(fresh, encoding="utf-8")
    print("docs/errors.md updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
