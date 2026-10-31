"""Repository consistency: documented CLI commands parse, versions agree, packaged license files match."""

from __future__ import annotations

import json
import re
import shlex

import pytest
from conftest import REPO

import scrawl
from scrawl.cli import build_parser

DOCS = [REPO / "README.md", REPO / "python" / "README.md", *sorted((REPO / "docs").glob("*.md"))]


def _documented_commands() -> list[tuple[str, str]]:
    """Every ``scrawl ...`` line inside a fenced bash block of the docs (comments and pipes stripped)."""
    found = []
    for doc in DOCS:
        in_bash = False
        for line in doc.read_text(encoding="utf-8").splitlines():
            if line.startswith("```"):
                in_bash = line.strip() in ("```bash", "```sh")
                continue
            if not in_bash:
                continue
            command = line.split(" #", 1)[0].strip()
            for part in re.split(r"\s*(?:&&|\|\||;)\s*", command):
                part = part.split(" < ", 1)[0].split(" > ", 1)[0].strip()
                if part.startswith("scrawl "):
                    found.append((doc.name, part))
    return found


COMMANDS = _documented_commands()


def test_the_docs_show_the_cli() -> None:
    assert len(COMMANDS) > 40


@pytest.mark.parametrize(("doc", "command"), COMMANDS, ids=[f"{d}:{c}" for d, c in COMMANDS])
def test_every_documented_command_parses(doc: str, command: str) -> None:
    argv = shlex.split(command)[1:]
    try:
        build_parser().parse_args(argv)
    except SystemExit as exc:                     # --version / --help exit 0; anything else is a usage error
        assert exc.code == 0, f"{doc}: {command}"


def test_python_versions_agree() -> None:
    pyproject = (REPO / "python" / "pyproject.toml").read_text(encoding="utf-8")
    declared = re.search(r'^version = "([^"]+)"', pyproject, re.M)
    assert declared and declared.group(1) == scrawl.__version__


def test_typescript_versions_agree() -> None:
    package = json.loads((REPO / "typescript" / "package.json").read_text(encoding="utf-8"))
    version_js = (REPO / "typescript" / "src" / "version.js").read_text(encoding="utf-8")
    assert f'"{package["version"]}"' in version_js
    assert package["name"] == "@apexaiofficial/scrawl" and package["license"] == "Apache-2.0"
    assert not package.get("private"), "the npm package must be publishable"


@pytest.mark.parametrize("name", ["LICENSE", "NOTICE"])
def test_packaged_license_files_match_the_repository(name: str) -> None:
    root = (REPO / name).read_bytes()
    assert (REPO / "python" / name).read_bytes() == root
    assert (REPO / "typescript" / name).read_bytes() == root


def test_the_notice_names_the_copyright_holder() -> None:
    assert "Copyright 2026 ApexAiOfficial" in (REPO / "NOTICE").read_text(encoding="utf-8")
    assert "Apache License" in (REPO / "LICENSE").read_text(encoding="utf-8")


def test_examples_and_tests_use_reserved_domains_only() -> None:
    """Hosts in examples and tests are .example / .test / loopback / TEST-NET, never a real or private name."""
    allowed = re.compile(r"^(?:[a-z0-9-]+\.)*(?:example|test|localhost)$|^127\.0\.0\.1$|^\[::1\]$|^192\.0\.2\.\d+$")
    files = [*(REPO / "python").glob("examples/*.py"), *(REPO / "python").glob("tests/**/*.py"),
             *(REPO / "typescript").glob("examples/*.mjs"), *(REPO / "typescript").glob("test/**/*.js"),
             *(REPO / "typescript").glob("test/**/*.mts"), REPO / "tools" / "fake_apexapi.py"]
    for file in files:
        for netloc in re.findall(r"https?://([^/\s\"'`)]+)", file.read_text(encoding="utf-8")):
            host = netloc if netloc.startswith("[") and netloc.endswith("]") else re.sub(r":[^:\]]*$", "", netloc)
            if host in ("example.com",) or "$" in host or "{" in netloc:   # RFC 2606; template placeholders
                continue
            assert allowed.match(host.lower()), f"{file.relative_to(REPO)}: {netloc}"


def test_no_build_output_or_virtualenv_is_tracked() -> None:
    ignored = (REPO / ".gitignore").read_text(encoding="utf-8")
    for pattern in (".venv/", "build/", "dist/", "*.egg-info/", "node_modules/", ".env"):
        assert pattern in ignored
