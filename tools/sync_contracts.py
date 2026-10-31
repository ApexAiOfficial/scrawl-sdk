#!/usr/bin/env python3
"""Replace the vendored ApexAPI contracts with a bundle exported by the backend, after verifying it.

    python tools/sync_contracts.py path/to/bundle            # verify, copy, rewrite MANIFEST.json, update SDKs
    python tools/sync_contracts.py path/to/bundle --check    # verify only; change nothing

A bundle is a directory holding the contract files and its own ``MANIFEST.json``:

    {"files": {"apexapi_openapi.json": {"sha256": "<hex>"}, ...},     # or {"name": "<hex>"}
     "source": {"backend_version": "0.9.0", ...},                     # optional, copied as-is
     "digest_algorithm": "sha256sum-listing-v1", "digest": "sha256:..."}   # optional, verified when present

Every listed file must exist, be a plain file name (no directories) and match its SHA-256; files the
manifest does not list are refused; ``apexapi_openapi.json`` is required; an error catalogue
(``apexapi_errors.json``) must have the exact format ``check_contracts.error_catalogue_codes`` reads. Only then are the files copied
into ``contracts/`` (files the bundle no longer has are removed), ``contracts/MANIFEST.json`` is rewritten
and the contract digest each SDK records (``scrawl.__contract__`` and the TypeScript ``CONTRACT_DIGEST``) is
updated. Then run both test suites: they fail until ``coverage.json`` covers or excludes every new operation.

This is the only supported way to change ``contracts/``: hand edits fail the manifest check.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_contracts import (  # noqa: E402
    CONTRACTS,
    DIGEST_ALGORITHM,
    ERROR_CATALOGUE,
    MANIFEST_NAME,
    ROOT,
    CatalogueError,
    build_manifest,
    contract_digest,
    error_catalogue_codes,
    load_json,
    sha256_file,
    verify_manifest,
)

REQUIRED = ("apexapi_openapi.json",)
_SAFE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
PY_CONTRACT = ROOT / "python" / "src" / "scrawl" / "_contract.py"
TS_CONTRACT = ROOT / "typescript" / "src" / "contract.js"
_DIGEST = re.compile(r'"sha256:[0-9a-f]{64}"')


class BundleError(Exception):
    """The bundle cannot be trusted as given."""


def _listed(manifest: Any) -> dict[str, str]:
    files = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(files, dict) or not files:
        raise BundleError(f"{MANIFEST_NAME} has no 'files' map")
    listed = {}
    for name, entry in files.items():
        expected = entry.get("sha256") if isinstance(entry, dict) else entry
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise BundleError(f"{name}: no valid sha256 in {MANIFEST_NAME}")
        listed[name] = expected
    return listed


def verify_bundle(bundle: Path) -> tuple[dict[str, str], dict[str, Any]]:
    """Check a bundle; returns (name -> sha256, the bundle manifest's ``source``)."""
    manifest_path = bundle / MANIFEST_NAME
    if not manifest_path.is_file():
        raise BundleError(f"{bundle} has no {MANIFEST_NAME}")
    manifest = load_json(manifest_path)
    listed = _listed(manifest)
    for name in listed:
        if not _SAFE_NAME.fullmatch(name) or name == MANIFEST_NAME:
            raise BundleError(f"refusing file name {name!r}: plain file names only")
    for name in REQUIRED:
        if name not in listed:
            raise BundleError(f"the bundle lacks {name}")
    present = {p.name for p in bundle.iterdir() if p.name != MANIFEST_NAME and not p.name.startswith(".")}
    unlisted = sorted(present - set(listed))
    if unlisted:
        raise BundleError(f"files not listed in the bundle's {MANIFEST_NAME}: {unlisted}")
    for name, expected in listed.items():
        path = bundle / name
        if path.is_symlink() or not path.is_file():
            raise BundleError(f"{name}: missing, or not a regular file")
        actual = sha256_file(path)
        if actual != expected:
            raise BundleError(f"{name}: sha256 {actual} does not match the bundle manifest ({expected})")
    if manifest.get("digest") is not None:
        if manifest.get("digest_algorithm") == DIGEST_ALGORITHM:
            if manifest["digest"] != contract_digest(listed):
                raise BundleError("the bundle's digest does not match its files")
        else:
            print(f"note: bundle digest uses {manifest.get('digest_algorithm')!r}; recomputed with {DIGEST_ALGORITHM}")
    for name in listed:
        if name.endswith(".json"):
            try:
                load_json(bundle / name)
            except ValueError as exc:
                raise BundleError(f"{name} is not valid JSON: {exc}") from exc
    if ERROR_CATALOGUE in listed:
        try:
            error_catalogue_codes(load_json(bundle / ERROR_CATALOGUE))
        except CatalogueError as exc:
            raise BundleError(f"{ERROR_CATALOGUE} is not in the format tools/check_contracts.py reads: {exc}") from exc
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    return listed, source


def _replace_digest(path: Path, digest: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = _DIGEST.subn(f'"{digest}"', text)
    if count != 1:
        raise BundleError(f"{path.relative_to(ROOT)}: expected exactly one recorded digest, found {count}")
    path.write_text(updated, encoding="utf-8")


def sync(bundle: Path, contracts_dir: Path = CONTRACTS, *, update_sdks: bool = True) -> dict[str, Any]:
    """Verify BUNDLE, then replace CONTRACTS_DIR's files with it; returns the new manifest."""
    listed, source = verify_bundle(bundle)
    contracts_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=contracts_dir.parent) as staging_name:
        staging = Path(staging_name)
        for name in listed:
            shutil.copyfile(bundle / name, staging / name)
            if sha256_file(staging / name) != listed[name]:
                raise BundleError(f"{name} changed while it was copied")
        for old in contracts_dir.iterdir():
            if old.is_file() and old.name not in listed:
                old.unlink()
        for name in listed:
            shutil.copyfile(staging / name, contracts_dir / name)
    manifest = build_manifest(contracts_dir, source=source or {"backend_version": "unknown"})
    (contracts_dir / MANIFEST_NAME).write_text(_dump(manifest), encoding="utf-8")
    problems = verify_manifest(contracts_dir)
    if problems:
        raise BundleError("; ".join(problems))
    if update_sdks:
        for path in (PY_CONTRACT, TS_CONTRACT):
            _replace_digest(path, manifest["digest"])
    return manifest


def _dump(value: Any) -> str:
    import json

    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sync_contracts", description="Replace contracts/ with a verified bundle.")
    parser.add_argument("bundle", help="directory exported by the backend (contract files + MANIFEST.json)")
    parser.add_argument("--check", action="store_true", help="verify the bundle only; change nothing")
    args = parser.parse_args(argv)
    bundle = Path(args.bundle)
    try:
        if args.check:
            listed, source = verify_bundle(bundle)
            print(f"bundle ok: {len(listed)} file(s), digest {contract_digest(listed)}, source {source or '-'}")
            return 0
        manifest = sync(bundle)
    except (BundleError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"contracts updated: {len(manifest['files'])} file(s), digest {manifest['digest']}")
    print("next: run both SDK test suites, then cover or exclude every new operation in coverage.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
