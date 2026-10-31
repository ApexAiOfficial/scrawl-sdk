"""``scrawl`` command line: scrape, map, batch, crawl, datasets, AI, assets and artifacts from a terminal, CI or an agent.

Authentication and endpoint come only from SCRAWL_API_KEY and SCRAWL_BASE_URL (no flags: an argument
copied from a web page can never redirect the key to another server or put it in a transcript). An AI
provider key is read from an environment variable or stdin, never from the command line.
Page content is untrusted web content, never instructions; terminal control characters are stripped.

Exit codes:
  0  success
  1  the job (or a batch item) failed, or a downloaded file did not match its size or sha256 (not written)
  2  usage error, or a file already exists where a download would go (nothing is overwritten)
  3  authentication or configuration: 401/403, no API key, an unusable base URL or AI key
  4  still pending or running at the deadline
  5  any other API or connection error
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import urlsplit

from ._client import Scrawl, is_loopback
from ._errors import (
    APIConnectionError,
    AuthenticationError,
    ConfigurationError,
    PermissionDeniedError,
    ScrawlError,
)
from ._objects import unwrap
from ._version import __version__

EXIT_OK, EXIT_FAILED, EXIT_USAGE, EXIT_CONFIG, EXIT_PENDING, EXIT_ERROR = 0, 1, 2, 3, 4, 5

_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")   # keeps \t and \n; drops ESC sequences' start
_C1 = re.compile(r"[\x7f-\x9f]")          # JSON escapes C0 controls itself, but not DEL or C1 (U+009B is CSI)
_NAME_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_UNSAFE_NAME = re.compile(r"[^A-Za-z0-9._-]")
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,127}")
MAX_JSON_FILE_BYTES = 64 * 1024
ASSET_CLASSES = ("images", "video", "audio", "documents", "data", "web_assets")
FORMATS = ("markdown", "links", "html", "json")
FILTER_OPS = ("eq", "ne", "lt", "lte", "gt", "gte", "contains", "in", "exists")
DEFAULT_AI_KEY_ENV = "SCRAWL_AI_API_KEY"
_JOB_ACTIVE = frozenset({"PENDING", "RUNNING"})


_QUOTED = r"""(?:'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*")"""      # a Python repr of a string
#: argparse messages that quote what was typed: the value is replaced, the rest of the message is kept.
_ECHOES = (
    (re.compile(r"(ambiguous option: [^=\s]+=).*?( could match |$)", re.S), r"\1(not shown)\2"),
    (re.compile(rf"(invalid choice: |invalid [\w.]+ value: |ignored explicit argument ){_QUOTED}"),
     r"\1(not shown)"),
)


class _Parser(argparse.ArgumentParser):
    """An argument parser that never echoes what was typed (an argument might be a pasted secret)."""

    def error(self, message: str) -> NoReturn:
        if message.startswith("unrecognized arguments"):
            message = "unrecognized arguments (not shown: secrets never belong on the command line)"
        for pattern, replacement in _ECHOES:
            message = pattern.sub(replacement, message)
        super().error(message)


def _safe(text: str) -> str:
    return _CONTROL.sub("", text)


def _json(value: Any) -> str:
    """Indented JSON with every terminal control character escaped (still the same JSON)."""
    text = json.dumps(value, indent=2, ensure_ascii=False)       # escapes C0 controls, keeps other characters
    return _C1.sub(lambda match: f"\\u{ord(match.group()):04x}", text)  # only ever inside strings: valid JSON


def _emit(value: Any, *, as_json: bool, field: str | None = None) -> None:
    value = unwrap(value)                                         # a batch's ``items`` field shadows dict.items
    if as_json or field is None or not isinstance(value, dict) or value.get(field) is None:
        print(_json(value))
    elif isinstance(value[field], (dict, list)):
        print(_json(value[field]))
    else:
        print(_safe(str(value[field])))


def _json_file(path: str | None, flag: str) -> Any:
    if not path:
        return None
    file = Path(path)
    if file.suffix.lower() != ".json" or file.stat().st_size > MAX_JSON_FILE_BYTES:
        raise ValueError(f"{flag} must be a .json file of at most 64 KiB")
    return json.loads(file.read_text(encoding="utf-8"))


def _schema(path: str | None) -> dict | None:
    schema = _json_file(path, "--schema")
    if schema is not None and not isinstance(schema, dict):
        raise ValueError("--schema must hold a JSON object (a JSON Schema)")
    return schema


def _engine_options(args: argparse.Namespace) -> dict:
    """``--browser`` and ``--wait-for`` as SDK options; nothing when neither was given."""
    if args.wait_for is not None and not args.browser:
        raise ValueError("--wait-for needs --browser")          # main() turns it into exit code 2
    return {"engine": "browser", "wait_for_ms": args.wait_for} if args.browser else {}


def _job_exit(job: Any) -> int:
    status = str(job.get("status") or "").upper()
    if status == "COMPLETED":
        return EXIT_OK
    return EXIT_PENDING if status in _JOB_ACTIVE else EXIT_FAILED


def _batch_exit(result: Any) -> int:
    if result.status != "completed":
        return EXIT_PENDING
    items = result.get("items") or []
    return EXIT_OK if all(item.get("status") == "completed" for item in items) else EXIT_FAILED


def _batch_downgrades(result: Any) -> list[str]:
    """URLs of finished batch items another engine rendered (the batch asked for ``--browser``)."""
    return [str(item.get("url")) for item in result.get("items") or []
            if isinstance(item.get("result"), dict) and item["result"].get("status") in ("completed", "failed")
            and item["result"].get("engine") != "browser"]


def _batch_report(result: Any, *, browser: bool) -> int:
    """Print the batch; with ``--browser``, a finished item from another engine is ``render_not_supported`` (5)."""
    _emit(result, as_json=True)
    downgraded = _batch_downgrades(result) if browser else []
    if downgraded:
        print(_safe(f"error: [render_not_supported] the server did not render {len(downgraded)} item(s) in a browser "
                    f"(it may predate the browser engine): {', '.join(downgraded[:5])}"), file=sys.stderr)
        return EXIT_ERROR
    return _batch_exit(result)


# -- scrape, map, batch, extract, ask --------------------------------------------------------------

def _cmd_scrape(client: Scrawl, args: argparse.Namespace) -> int:
    formats = args.format or (["json"] if (args.schema or args.instruction) else ["markdown"])
    engine = _engine_options(args)
    result = client.scrape(args.url, formats=formats, schema=_schema(args.schema), instruction=args.instruction,
                           profile=args.profile, wait_seconds=min(args.wait, 60), **engine)
    if result.status == "pending" and args.wait > 60:
        result = client.wait_for_scrape(result.job_id, timeout=args.wait - 60, engine=engine.get("engine"))
    if result.status == "pending":
        follow = f"scrawl result {result.job_id}" + (" --browser" if args.browser else "")
        print(_safe(f"pending: job {result.job_id} ({follow})"), file=sys.stderr)
        return EXIT_PENDING
    if result.status == "failed":
        print(f"failed: {_safe(str(result.get('error')))}", file=sys.stderr)
        if not args.json:
            return EXIT_FAILED
    field = None if args.json else ("json" if formats == ["json"] else formats[0])
    _emit(result, as_json=args.json, field=field)
    return EXIT_OK if result.status == "completed" else EXIT_FAILED


def _cmd_result(client: Scrawl, args: argparse.Namespace) -> int:
    engine = "browser" if args.browser else None           # keeps the downgrade guard on the follow-up
    result = (client.wait_for_scrape(args.job_id, timeout=args.wait, engine=engine) if args.wait
              else client.scrape_result(args.job_id, engine=engine))
    _emit(result, as_json=True)
    return {"completed": EXIT_OK, "pending": EXIT_PENDING}.get(result.status, EXIT_FAILED)


def _cmd_map(client: Scrawl, args: argparse.Namespace) -> int:
    result = client.map(args.url, limit=args.limit, wait_seconds=min(args.wait, 60), **_engine_options(args))
    if args.json:
        _emit(result, as_json=True)
    else:
        print(_safe("\n".join(result.get("links") or [])))
    return {"completed": EXIT_OK, "pending": EXIT_PENDING}.get(result.status, EXIT_FAILED)


def _cmd_batch(client: Scrawl, args: argparse.Namespace) -> int:
    started = client.batch_scrape(args.urls, formats=args.format or ["markdown"], schema=_schema(args.schema),
                                  instruction=args.instruction, profile=args.profile, **_engine_options(args))
    result = client.wait_for_batch(started.batch_id, timeout=args.wait) if args.wait else started
    return _batch_report(result, browser=args.browser)


def _cmd_batch_status(client: Scrawl, args: argparse.Namespace) -> int:
    result = (client.wait_for_batch(args.batch_id, timeout=args.wait) if args.wait
              else client.batch_status(args.batch_id))
    return _batch_report(result, browser=args.browser)


def _cmd_extract(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.extract(args.job_id, args.artifact, schema=_schema(args.schema), instruction=args.instruction,
                         profile=args.profile), as_json=args.json, field="data")
    return EXIT_OK


def _cmd_ask(client: Scrawl, args: argparse.Namespace) -> int:
    result = client.ask(args.question, dataset_id=args.dataset, profile=args.profile)
    if args.json:
        _emit(result, as_json=True)
        return EXIT_OK
    print(_safe(str(result.get("answer") or "")))
    citations = result.get("citations") or []
    if citations:
        print("\nSources:")
    for citation in citations:
        title = citation.get("title") or citation.get("document_id") or ""
        print(_safe(f"  [{citation.get('tag')}] {title} {citation.get('url') or ''}".rstrip()))
    return EXIT_OK


# -- crawls and jobs -------------------------------------------------------------------------------

def _cmd_crawl(client: Scrawl, args: argparse.Namespace) -> int:
    launch = client.crawl(args.target, export_format=args.export_format, max_items=args.max_items,
                          max_seconds=args.max_seconds)
    if not args.wait:
        _emit(launch, as_json=True)
        return EXIT_OK
    job = client.wait_for_job(launch.job_id, timeout=args.wait)
    launch["job"] = job
    _emit(launch, as_json=True)
    return _job_exit(job)


def _cmd_job(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.get_job(args.job_id, wait_seconds=min(args.wait, 60)), as_json=True)
    return EXIT_OK


def _cmd_jobs(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.list_jobs(limit=args.limit, status=args.status, cursor=args.cursor), as_json=True)
    return EXIT_OK


def _cmd_cancel(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.cancel_job(args.job_id), as_json=True)
    return EXIT_OK


# -- downloads: whole files, never overwriting ---------------------------------------------------

def _write_new_file(target: Path, data: bytes) -> None:
    """Write DATA to TARGET whole or not at all, never replacing a file (an existing one is an OSError, exit 2).

    The bytes go to a temporary sibling first; only a complete, flushed file is linked to the final name, so a
    write cut short (disk full, kill) never leaves a partial file that would block the retry.
    """
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex[:8]}.part")
    try:
        with open(temporary, "xb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        try:
            os.link(temporary, target)                  # fails if TARGET exists: never overwrites
        except FileExistsError:
            raise
        except OSError:                                 # a filesystem without hard links: claim the name
            placeholder = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)   # exclusively, then
            os.close(placeholder)                                                          # replace only our own
            try:
                os.replace(temporary, target)
            except BaseException:
                target.unlink(missing_ok=True)
                raise
    finally:
        temporary.unlink(missing_ok=True)


def _clean_name(name: Any, fallback: str) -> str:
    """A page- or server-supplied name reduced to ``[A-Za-z0-9._-]``, no directory, no leading dot."""
    base = _NAME_CONTROL.sub("", str(name or "")).replace("\\", "/").rsplit("/", 1)[-1]
    return _UNSAFE_NAME.sub("_", base)[:120].lstrip(".") or fallback


def _inside(root: Path, target: Path) -> Path:
    resolved = target.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise ValueError(f"refusing to write outside {root}: {resolved}")
    return resolved


def _asset_path(root: Path, item: Any) -> Path:
    """``DIR/<class>/<asset_id[:12]>-<basename>``: page-supplied names never pick a directory or a device."""
    folder = item.get("asset_class") if item.get("asset_class") in ASSET_CLASSES else "other"
    base = _clean_name(item.get("filename"), "asset")
    prefix = _UNSAFE_NAME.sub("", str(item.get("asset_id") or "")[:12]).lstrip(".-") or "asset"
    return _inside(root, root / folder / f"{prefix}-{base}")


def _artifact_path(root: Path, name: str, *, markdown: bool) -> Path:
    """``DIR/<name>`` (``DIR/<stem>.md`` for a Markdown conversion), the name reduced to safe characters."""
    base = _clean_name(name, "artifact")
    if markdown:
        base = (Path(base).stem or "artifact") + ".md"
    return _inside(root, root / base)


def _download_assets(client: Scrawl, result: Any, out: str) -> int:
    root, written, rejected = Path(out), 0, 0
    assets = result.get("assets") or []
    if assets and not result.get("files_available"):
        state = (result.get("billing") or {}).get("state")
        print(f"error: the job's files are not available (billing: {_safe(str(state))})", file=sys.stderr)
        return EXIT_FAILED
    for item in assets:
        target = _asset_path(root, item)
        data = client.download_asset(result.job_id, item.asset_id)
        expected = str(item.get("sha256") or "").lower()
        if not expected or hashlib.sha256(data).hexdigest() != expected:
            print(f"error: sha256 mismatch for asset {_safe(str(item.asset_id))}: not written", file=sys.stderr)
            rejected += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_new_file(target, data)
        written += 1
    print(f"wrote {written} file(s) under {_safe(str(root))}", file=sys.stderr)
    return EXIT_FAILED if rejected else EXIT_OK


def _cmd_artifacts_list(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.list_artifacts(args.job_id), as_json=True)
    return EXIT_OK


def _cmd_artifacts_download(client: Scrawl, args: argparse.Namespace) -> int:
    """Each file is checked against the job's artifact list (size, and sha256 when the server lists one)."""
    listing = client.list_artifacts(args.job_id)
    entries = {str(entry.get("name")): entry for entry in listing.get("artifacts") or []}
    names = args.names or list(entries)
    markdown = args.format == "markdown"
    root, files, rejected = Path(args.out), [], 0
    for name in names:
        entry = entries.get(name)
        if entry is None:
            print(f"error: {_safe(name)} is not in job {_safe(args.job_id)}'s artifact list: not written", file=sys.stderr)
            rejected += 1
            continue
        target = _artifact_path(root, name, markdown=markdown)
        data = client.download_artifact(args.job_id, name, format="markdown" if markdown else None)
        digest = hashlib.sha256(data).hexdigest()
        checks = []
        if not markdown:                                 # a conversion has no listed size or hash to match
            size, expected = entry.get("size_bytes"), str(entry.get("sha256") or "").lower()
            if size is not None:
                checks.append("size")
                if int(size) != len(data):
                    print(f"error: {_safe(name)} is {len(data)} bytes, the list says {size}: not written", file=sys.stderr)
                    rejected += 1
                    continue
            if expected:
                checks.append("sha256")
                if digest != expected:
                    print(f"error: sha256 mismatch for {_safe(name)}: not written", file=sys.stderr)
                    rejected += 1
                    continue
        target.parent.mkdir(parents=True, exist_ok=True)
        _write_new_file(target, data)
        files.append({"name": name, "path": str(target), "bytes": len(data), "sha256": digest, "verified": checks})
    _emit({"job_id": args.job_id, "out": str(root), "files": files}, as_json=True)
    print(f"wrote {len(files)} file(s) under {_safe(str(root))}", file=sys.stderr)
    return EXIT_FAILED if rejected else EXIT_OK


# -- assets ------------------------------------------------------------------------------------------

def _asset_options(args: argparse.Namespace) -> dict[str, Any]:
    return {"classes": args.classes, "max_items": args.max_items, "max_bytes": args.max_bytes,
            "max_credits": args.max_credits}


def _asset_exit(result: Any) -> int:
    return {"completed": EXIT_OK, "pending": EXIT_PENDING, "running": EXIT_PENDING}.get(result.status, EXIT_FAILED)


def _whole(client: Scrawl, result: Any, view: str) -> Any:
    """Follow ``next_cursor`` so the printed result (and ``--out``) covers the whole job, not one page."""
    if result.get("next_cursor") and isinstance(result.get(view), list):
        result[view].extend(client.paginate(client.get_assets, result.job_id, view=view, limit=200,
                                            cursor=result.next_cursor))
        result["next_cursor"] = None
    return result


def _cmd_assets(client: Scrawl, args: argparse.Namespace) -> int:
    job = client.extract_assets(args.url, **_asset_options(args))
    result = _whole(client, client.wait_for_assets(job.job_id, timeout=args.wait), "assets")
    _emit(result, as_json=True)
    code = _asset_exit(result)
    return _download_assets(client, result, args.out) if code == EXIT_OK and args.out else code


def _cmd_assets_quote(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.quote_assets(args.url, **_asset_options(args)), as_json=True)
    return EXIT_OK


def _cmd_assets_result(client: Scrawl, args: argparse.Namespace) -> int:
    if args.out and args.view != "assets":
        raise ValueError("--out downloads stored assets: it cannot be combined with --view skipped")
    result = client.wait_for_assets(args.job_id, timeout=args.wait) if args.wait else None
    if result is None or args.view != "assets":
        result = client.get_assets(args.job_id, view=args.view)
    result = _whole(client, result, args.view)
    _emit(result, as_json=True)
    code = _asset_exit(result)
    return _download_assets(client, result, args.out) if code == EXIT_OK and args.out else code


# -- datasets ----------------------------------------------------------------------------------------

def _cmd_datasets_list(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.list_datasets(limit=args.limit, cursor=args.cursor), as_json=True)
    return EXIT_OK


def _cmd_datasets_get(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.get_dataset(args.dataset_id), as_json=True)
    return EXIT_OK


def _cmd_datasets_versions(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.list_versions(args.dataset_id, limit=args.limit, cursor=args.cursor, status=args.status), as_json=True)
    return EXIT_OK


def _cmd_datasets_activate(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.activate_version(args.dataset_id, args.version_id), as_json=True)
    return EXIT_OK


def _cmd_datasets_diff(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.diff_versions(args.dataset_id, args.from_version, args.to_version, limit=args.limit,
                               cursor=args.cursor), as_json=True)
    return EXIT_OK


def _cmd_datasets_fields(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.dataset_fields(args.dataset_id, version=args.version), as_json=True)
    return EXIT_OK


def _filter_value(text: str) -> Any:
    try:
        return json.loads(text)                         # 20 -> 20, true -> True, ["a","b"] -> list
    except ValueError:
        return text                                     # anything else is a string


def _filters(args: argparse.Namespace) -> list[dict[str, Any]]:
    filters = _json_file(args.filters_file, "--filters-file") or []
    if not isinstance(filters, list) or not all(isinstance(item, dict) for item in filters):
        raise ValueError("--filters-file must hold a JSON list of {field, op, value} objects")
    for field, op, value in args.where or []:
        if op not in FILTER_OPS:
            raise ValueError(f"--where: op must be one of {', '.join(FILTER_OPS)}")
        filters.append({"field": field, "op": op, "value": _filter_value(value)})
    return filters


def _cmd_datasets_query(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.query_dataset(args.dataset_id, _filters(args), version_id=args.version, limit=args.limit,
                               cursor=args.cursor), as_json=True)
    return EXIT_OK


def _cmd_datasets_extract(client: Scrawl, args: argparse.Namespace) -> int:
    launch = client.extract_dataset(args.dataset_id, schema=_schema(args.schema), instruction=args.instruction,
                                    profile=args.profile, version_id=args.version, max_records=args.max_records)
    if not args.wait:
        _emit(launch, as_json=True)
        return EXIT_OK
    job = client.wait_for_job(launch.job_id, timeout=args.wait)
    launch["job"] = job
    _emit(launch, as_json=True)
    return _job_exit(job)


def _cmd_datasets_quarantine(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.quarantine_record(args.dataset_id, args.record_id, reason=args.reason), as_json=True)
    return EXIT_OK


def _cmd_datasets_release(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.release_record(args.dataset_id, args.record_id), as_json=True)
    return EXIT_OK


def _cmd_search(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.search(args.query, limit=args.limit), as_json=True)
    return EXIT_OK


def _cmd_document(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.get_document(args.document_id), as_json=True)
    return EXIT_OK


# -- AI providers (your own keys) ----------------------------------------------------------------

def _env_name(text: str) -> str:
    if not _ENV_NAME.fullmatch(text):
        raise argparse.ArgumentTypeError("an environment variable name, e.g. SCRAWL_AI_API_KEY")
    return text


def _ai_key(args: argparse.Namespace) -> str:
    """The provider key from stdin (``--key-stdin``) or an environment variable; never from argv."""
    if args.key_stdin:
        key = sys.stdin.readline().strip()
        if not key:
            raise ConfigurationError("No AI provider key on stdin")
        return key
    name = args.key_env or DEFAULT_AI_KEY_ENV
    key = os.environ.get(name, "").strip()
    if not key:
        raise ConfigurationError(f"No AI provider key: set {name} (or pipe the key with --key-stdin)")
    return key


def _cmd_ai_list(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.list_ai_providers(), as_json=True)
    return EXIT_OK


def _cmd_ai_set(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.set_ai_provider(args.profile, provider=args.provider, api_key=_ai_key(args), model=args.model,
                                 base_url=args.base_url), as_json=True)
    return EXIT_OK


def _cmd_ai_default(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.set_default_ai_provider(args.profile), as_json=True)
    return EXIT_OK


def _cmd_ai_test(client: Scrawl, args: argparse.Namespace) -> int:
    result = client.test_ai_provider(args.profile)
    _emit(result, as_json=True)
    return EXIT_OK if result.get("ok") else EXIT_FAILED


def _cmd_ai_remove(client: Scrawl, args: argparse.Namespace) -> int:
    client.delete_ai_provider(args.profile)
    _emit({"profile": args.profile, "removed": True}, as_json=True)
    return EXIT_OK


def _cmd_ai_usage(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.ai_usage(days=args.days), as_json=True)
    return EXIT_OK


def _cmd_balance(client: Scrawl, args: argparse.Namespace) -> int:
    _emit(client.credit_balance(), as_json=True)
    return EXIT_OK


# -- doctor: is this machine set up to use Scrawl? -------------------------------------------------

def _doctor_report(checks: list[dict[str, str]], base_url: str | None, as_json: bool, code: int) -> int:
    if as_json:
        print(_json({"ok": code == EXIT_OK, "base_url": base_url, "checks": checks}))
    else:
        for check in checks:
            print(_safe(f"{check['status']:<5} {check['check']:<10} {check['detail']}"))
        print("ready" if code == EXIT_OK else "not ready", file=sys.stderr)
    return code


def _cmd_doctor(client: Scrawl | None, args: argparse.Namespace) -> int:
    """Check the base URL, TLS, reachability and the API key; never prints the key."""
    checks: list[dict[str, str]] = []

    def add(check: str, status: str, detail: str) -> None:
        checks.append({"check": check, "status": status, "detail": detail})

    owned = client is None
    try:
        client = client or Scrawl()
    except ConfigurationError as exc:
        add("base_url", "fail", str(exc))
        return _doctor_report(checks, os.environ.get("SCRAWL_BASE_URL"), args.json, EXIT_CONFIG)
    try:
        return _doctor_checks(client, add, checks, args)
    finally:
        if owned:
            client.close()


def _doctor_checks(client: Scrawl, add: Any, checks: list[dict[str, str]], args: argparse.Namespace) -> int:
    base = client.base_url
    parts = urlsplit(base)
    source = "SCRAWL_BASE_URL" if os.environ.get("SCRAWL_BASE_URL") else \
        "default: a server on this machine; set SCRAWL_BASE_URL for a remote one"
    add("base_url", "ok", f"{base} ({source})")
    if parts.scheme == "https":
        tls = ("ok", "https: the server certificate is verified")
    elif is_loopback(parts.hostname or ""):
        tls = ("ok", "plain HTTP to this machine (no TLS needed)")
    else:
        tls = ("warn", "plain HTTP to a remote host: the API key crosses the network unencrypted")
    started = time.monotonic()
    try:
        health = client.health()
    except APIConnectionError as exc:
        text = str(exc)
        if parts.scheme == "https" and any(word in text for word in ("SSL", "TLS", "certificate", "CERTIFICATE")):
            add("tls", "fail", f"TLS failed: {text}")
            return _doctor_report(checks, base, args.json, EXIT_CONFIG)
        add("tls", *tls)
        add("reachable", "fail", text)
        return _doctor_report(checks, base, args.json, EXIT_ERROR)
    except ScrawlError as exc:
        add("tls", *tls)
        add("reachable", "fail", f"GET /v1/health: {exc}")
        return _doctor_report(checks, base, args.json, EXIT_ERROR)
    add("tls", *tls)
    elapsed = int((time.monotonic() - started) * 1000)
    status = health.get("status") if isinstance(health, dict) else None
    add("reachable", "ok" if status == "ok" else "warn", f"GET /v1/health answered {status!r} in {elapsed} ms")
    if not client._t.api_key:
        add("auth", "fail", "no API key: set SCRAWL_API_KEY")
        return _doctor_report(checks, base, args.json, EXIT_CONFIG)
    try:
        client.list_jobs(limit=1)
    except ConfigurationError as exc:
        add("auth", "fail", str(exc))
        return _doctor_report(checks, base, args.json, EXIT_CONFIG)
    except AuthenticationError as exc:
        add("auth", "fail", f"the API key was refused: {exc}")
        return _doctor_report(checks, base, args.json, EXIT_CONFIG)
    except PermissionDeniedError:
        add("auth", "warn", "the API key is valid but lacks the jobs:read scope")
    except ScrawlError as exc:
        add("auth", "fail", f"GET /v1/jobs: {exc}")
        return _doctor_report(checks, base, args.json, EXIT_ERROR)
    else:
        add("auth", "ok", "the API key is accepted (GET /v1/jobs)")
    return _doctor_report(checks, base, args.json, EXIT_OK)


# -- the parser ----------------------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """The ``scrawl`` argument parser."""
    parser = _Parser(prog="scrawl", description="Scrawl: URL to Markdown or JSON, map, batch, crawl, datasets, "
                     "AI extraction, assets and artifacts.",
                     epilog="Exit codes: 0 ok, 1 failed, 2 usage, 3 auth/config, 4 pending, 5 other error.")
    parser.add_argument("--version", action="version", version=f"scrawl {__version__}")
    parser.add_argument("--json", action="store_true", help="print the full JSON response")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def engine_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--browser", action="store_true",
                       help="render the page in a sandboxed browser first (only where the server enables it)")
        p.add_argument("--wait-for", dest="wait_for", type=int, metavar="MS",
                       help="with --browser: wait this many more milliseconds after the page settles (0-10000)")

    def ai_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("--schema", help="JSON Schema file for the json format (.json, at most 64 KiB)")
        p.add_argument("--instruction", help="what to extract (json format)")
        p.add_argument("--profile", help="your AI profile (default if omitted)")

    p = sub.add_parser("scrape", help="scrape one URL")
    p.add_argument("url")
    p.add_argument("--format", action="append", choices=FORMATS)
    p.add_argument("--wait", type=int, default=60, help="seconds to wait for the result (default 60)")
    engine_options(p)
    ai_options(p)
    p.set_defaults(handler=_cmd_scrape)

    p = sub.add_parser("result", help="a scrape job's result")
    p.add_argument("job_id")
    p.add_argument("--wait", type=int, default=0)
    p.add_argument("--browser", action="store_true",
                   help="the scrape asked for --browser: fail (render_not_supported) if another engine answered")
    p.set_defaults(handler=_cmd_result)

    p = sub.add_parser("map", help="list a site's URLs")
    p.add_argument("url")
    p.add_argument("--limit", type=int, default=100)
    p.add_argument("--wait", type=int, default=60, help="seconds the server waits (max 60)")
    engine_options(p)
    p.set_defaults(handler=_cmd_map)

    p = sub.add_parser("batch", help="scrape up to 20 URLs")
    p.add_argument("urls", nargs="+")
    p.add_argument("--format", action="append", choices=FORMATS)
    p.add_argument("--wait", type=int, default=300, help="seconds to wait for every item (0: return at once)")
    engine_options(p)
    ai_options(p)
    p.set_defaults(handler=_cmd_batch)

    p = sub.add_parser("batch-status", help="a batch's items and results")
    p.add_argument("batch_id")
    p.add_argument("--wait", type=int, default=0, help="seconds to wait for every item to settle")
    p.add_argument("--browser", action="store_true",
                   help="the batch asked for --browser: fail (render_not_supported) if another engine answered")
    p.set_defaults(handler=_cmd_batch_status)

    p = sub.add_parser("extract", help="extract JSON from a finished job with your AI provider")
    p.add_argument("job_id")
    p.add_argument("--artifact", default="response.html")
    ai_options(p)
    p.set_defaults(handler=_cmd_extract)

    p = sub.add_parser("ask", help="answer a question from your datasets, with citations")
    p.add_argument("question")
    p.add_argument("--dataset", help="only this dataset")
    p.add_argument("--profile", help="your AI profile (default if omitted)")
    p.set_defaults(handler=_cmd_ask)

    p = sub.add_parser("crawl", help="start a bounded crawl that publishes a new dataset version")
    p.add_argument("target", help="a crawl target name the server allows")
    p.add_argument("--export-format", choices=("jsonlines", "json", "csv"))
    p.add_argument("--max-items", type=int)
    p.add_argument("--max-seconds", type=int)
    p.add_argument("--wait", type=int, default=0, help="seconds to wait for the crawl job to finish (0: return at once)")
    p.set_defaults(handler=_cmd_crawl)

    p = sub.add_parser("job", help="a job's state")
    p.add_argument("job_id")
    p.add_argument("--wait", type=int, default=0)
    p.set_defaults(handler=_cmd_job)

    p = sub.add_parser("cancel", help="cancel a job")
    p.add_argument("job_id")
    p.set_defaults(handler=_cmd_cancel)

    p = sub.add_parser("jobs", help="your jobs")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--status")
    p.add_argument("--cursor")
    p.set_defaults(handler=_cmd_jobs)

    artifacts = sub.add_parser("artifacts", help="a job's files").add_subparsers(dest="artifacts_command",
                                                                              required=True, metavar="ACTION")
    p = artifacts.add_parser("list", help="a job's artifacts")
    p.add_argument("job_id")
    p.set_defaults(handler=_cmd_artifacts_list)
    p = artifacts.add_parser("download", help="download artifacts, checked against the list, never overwriting")
    p.add_argument("job_id")
    p.add_argument("names", nargs="*", metavar="NAME", help="artifact names (default: every listed artifact)")
    p.add_argument("--out", required=True, help="directory to write into")
    p.add_argument("--format", choices=("raw", "markdown"), default="raw",
                   help="markdown converts an HTML artifact (written as NAME.md; nothing to verify against)")
    p.set_defaults(handler=_cmd_artifacts_download)

    datasets_parser = sub.add_parser("datasets", help="your datasets (no action: list them)")
    datasets_parser.add_argument("--limit", type=int, default=20)
    datasets_parser.add_argument("--cursor")
    datasets_parser.set_defaults(handler=_cmd_datasets_list)
    datasets = datasets_parser.add_subparsers(dest="datasets_command", metavar="ACTION")
    p = datasets.add_parser("list", help="your datasets")
    p.add_argument("--limit", type=int, default=argparse.SUPPRESS)
    p.add_argument("--cursor", default=argparse.SUPPRESS)
    p.set_defaults(handler=_cmd_datasets_list)
    p = datasets.add_parser("get", help="a dataset and its versions")
    p.add_argument("dataset_id")
    p.set_defaults(handler=_cmd_datasets_get)
    p = datasets.add_parser("versions", help="a dataset's versions, newest first")
    p.add_argument("dataset_id")
    p.add_argument("--limit", type=int)
    p.add_argument("--cursor")
    p.add_argument("--status")
    p.set_defaults(handler=_cmd_datasets_versions)
    p = datasets.add_parser("activate", help="make a completed version the active one")
    p.add_argument("dataset_id")
    p.add_argument("version_id")
    p.set_defaults(handler=_cmd_datasets_activate)
    p = datasets.add_parser("diff", help="records added, removed or changed between two versions")
    p.add_argument("dataset_id")
    p.add_argument("from_version")
    p.add_argument("to_version")
    p.add_argument("--limit", type=int)
    p.add_argument("--cursor")
    p.set_defaults(handler=_cmd_datasets_diff)
    p = datasets.add_parser("fields", help="field paths, types and examples of a version")
    p.add_argument("dataset_id")
    p.add_argument("--version")
    p.set_defaults(handler=_cmd_datasets_fields)
    p = datasets.add_parser("query", help="typed filters over a version's records")
    p.add_argument("dataset_id")
    p.add_argument("--where", nargs=3, action="append", metavar=("FIELD", "OP", "VALUE"),
                   help=f"a filter (repeatable); OP is one of {', '.join(FILTER_OPS)}; VALUE is JSON or text")
    p.add_argument("--filters-file", help="a .json file with a list of {field, op, value} filters")
    p.add_argument("--version")
    p.add_argument("--limit", type=int)
    p.add_argument("--cursor")
    p.set_defaults(handler=_cmd_datasets_query)
    p = datasets.add_parser("extract", help="extract a structured version with your AI provider (a job)")
    p.add_argument("dataset_id")
    ai_options(p)
    p.add_argument("--version")
    p.add_argument("--max-records", type=int)
    p.add_argument("--wait", type=int, default=0, help="seconds to wait for the job to finish (0: return at once)")
    p.set_defaults(handler=_cmd_datasets_extract)
    p = datasets.add_parser("quarantine", help="hide a record from retrieval (reversible)")
    p.add_argument("dataset_id")
    p.add_argument("record_id")
    p.add_argument("--reason")
    p.set_defaults(handler=_cmd_datasets_quarantine)
    p = datasets.add_parser("release", help="undo a quarantine")
    p.add_argument("dataset_id")
    p.add_argument("record_id")
    p.set_defaults(handler=_cmd_datasets_release)

    p = sub.add_parser("search", help="search your active dataset versions")
    p.add_argument("query")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(handler=_cmd_search)

    p = sub.add_parser("document", help="one indexed record with provenance")
    p.add_argument("document_id")
    p.set_defaults(handler=_cmd_document)

    ai = sub.add_parser("ai", help="your own AI providers").add_subparsers(dest="ai_command", required=True,
                                                                          metavar="AREA")
    providers = ai.add_parser("providers", help="AI provider profiles and usage").add_subparsers(
        dest="providers_command", required=True, metavar="ACTION")
    p = providers.add_parser("list", help="your profiles (never the keys)")
    p.set_defaults(handler=_cmd_ai_list)
    p = providers.add_parser("set", help="create or replace a profile; the key comes from an env var or stdin")
    p.add_argument("profile")
    p.add_argument("--provider", required=True)
    p.add_argument("--model")
    p.add_argument("--base-url")
    key = p.add_mutually_exclusive_group()
    key.add_argument("--key-env", type=_env_name, metavar="NAME",
                     help=f"read the provider key from this environment variable (default {DEFAULT_AI_KEY_ENV})")
    key.add_argument("--key-stdin", action="store_true", help="read the provider key from the first line of stdin")
    p.set_defaults(handler=_cmd_ai_set)
    for name, handler, text in (("default", _cmd_ai_default, "make a profile your default"),
                                ("test", _cmd_ai_test, "check a profile can reach its provider (exit 1 if not)"),
                                ("remove", _cmd_ai_remove, "delete a profile and its stored key")):
        p = providers.add_parser(name, help=text)
        p.add_argument("profile")
        p.set_defaults(handler=handler)
    p = providers.add_parser("usage", help="your AI calls and tokens by provider, model and feature")
    p.add_argument("--days", type=int, default=30)
    p.set_defaults(handler=_cmd_ai_usage)

    def asset_options(p: argparse.ArgumentParser) -> None:
        p.add_argument("url")
        p.add_argument("--class", dest="classes", action="append", choices=ASSET_CLASSES,
                       help="an asset class (repeatable; default all six)")
        p.add_argument("--max-items", type=int, help="at most this many files (server default 100)")
        p.add_argument("--max-bytes", type=int, help="at most this many bytes (server default 50 MiB)")
        p.add_argument("--max-credits", type=int, help="refuse when the estimate is above this (budget_exceeded)")

    p = sub.add_parser("assets", help="extract a page's images, video, audio, documents, data and web assets")
    asset_options(p)
    p.add_argument("--wait", type=int, default=300, help="seconds to wait for the job (default 300)")
    p.add_argument("--out", help="write every stored asset, sha256-verified, under this directory")
    p.set_defaults(handler=_cmd_assets)

    p = sub.add_parser("assets-quote", help="what an asset extraction would hold (starts nothing)")
    asset_options(p)
    p.set_defaults(handler=_cmd_assets_quote)

    p = sub.add_parser("assets-result", help="an asset job's result")
    p.add_argument("job_id")
    p.add_argument("--wait", type=int, default=0)
    p.add_argument("--view", choices=["assets", "skipped"], default="assets")
    p.add_argument("--out", help="write every stored asset, sha256-verified, under this directory")
    p.set_defaults(handler=_cmd_assets_result)

    p = sub.add_parser("balance", help="your credit balance")
    p.set_defaults(handler=_cmd_balance)

    p = sub.add_parser("doctor", help="check the setup: base URL, TLS, reachability, API key")
    p.set_defaults(handler=_cmd_doctor)
    return parser


def main(argv: list[str] | None = None, *, client: Scrawl | None = None) -> int:
    """Run the CLI; returns the exit code."""
    args = build_parser().parse_args(argv)
    try:
        if args.handler is _cmd_doctor:
            return _cmd_doctor(client, args)
        owned = client is None
        client = client or Scrawl()
        try:
            return args.handler(client, args)
        finally:
            if owned:
                client.close()
    except (AuthenticationError, PermissionDeniedError, ConfigurationError) as exc:
        print(_safe(f"error: {exc}"), file=sys.stderr)          # server messages are not trusted either
        return EXIT_CONFIG
    except ScrawlError as exc:
        print(_safe(f"error: {exc}"), file=sys.stderr)
        return EXIT_ERROR
    except (OSError, ValueError) as exc:
        print(_safe(f"error: {exc}"), file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
