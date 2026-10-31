"""Contract gate, driven by the shared coverage.json and tools/check_contracts.py.

Every ApexAPI operation is covered (a sync and an async method, a CLI command) or excluded with a reason;
each covered method, called with every option set, sends exactly the path, query parameters, body fields,
enum values and Idempotency-Key that coverage.json declares, and all of them exist in the contract.
"""

from __future__ import annotations

import argparse
import ast
import inspect
from pathlib import Path
from urllib.parse import quote

import check_contracts
import pytest
from conftest import COVERAGE, OPENAPI, REPO, Recorder, as_recorded, make_async_client, make_client

import scrawl
from scrawl import AsyncScrawl, Scrawl
from scrawl.cli import build_parser

SCHEMA = {"type": "object", "properties": {"name": {"type": "string"}}}

# "METHOD path" -> (positional arguments, keyword arguments with every option set).
CALLS: dict[str, tuple[tuple, dict]] = {
    "POST /v1/scrape": (("https://e.example",), dict(formats=["markdown", "json"], schema=SCHEMA, instruction="name",
                                                     profile="p", wait_seconds=5, engine="browser", wait_for_ms=500,
                                                     idempotency_key="key-1")),
    "GET /v1/scrape/{job_id}/content": (("job1",), dict(wait_seconds=5, formats=["markdown", "links"])),
    "POST /v1/map": (("https://e.example",), dict(limit=50, wait_seconds=5, engine="browser", wait_for_ms=500,
                                                  idempotency_key="key-2")),
    "POST /v1/scrape/batch": ((["https://a.example"],), dict(formats=["json"], schema=SCHEMA, instruction="i",
                                                             profile="p", engine="browser", wait_for_ms=500,
                                                             idempotency_key="key-3")),
    "GET /v1/scrape/batch/{batch_id}": (("b1",), dict(wait_seconds=5)),
    "POST /v1/extract": (("job1", "response.html"), dict(schema=SCHEMA, instruction="i", profile="p")),
    "POST /v1/ask": (("why?",), dict(dataset_id="d1", profile="p")),
    "GET /v1/ai/providers": ((), {}),
    "PUT /v1/ai/providers/{profile}": (("p",), dict(provider="example", api_key="sk-ai-test", model="m",
                                                    base_url="https://ai.example")),
    "DELETE /v1/ai/providers/{profile}": (("p",), {}),
    "POST /v1/ai/providers/{profile}/default": (("p",), {}),
    "POST /v1/ai/providers/{profile}/test": (("p",), {}),
    "GET /v1/ai/usage": ((), dict(days=7)),
    "POST /v1/crawls": (("target",), dict(export_format="jsonlines", max_items=10, max_seconds=60,
                                          idempotency_key="key-4")),
    "GET /v1/jobs/{job_id}": (("job1",), dict(wait_seconds=5)),
    "GET /v1/jobs": ((), dict(limit=5, status="RUNNING", cursor="c")),
    "POST /v1/jobs/{job_id}/cancel": (("job1",), {}),
    "GET /v1/artifacts/{job_id}": (("job1",), {}),
    "GET /v1/artifacts/{job_id}/{filename}": (("job1", "response.html"), dict(format="markdown")),
    "GET /v1/datasets": ((), dict(limit=5, cursor="c")),
    "GET /v1/datasets/{dataset_id}": (("d1",), {}),
    "GET /v1/datasets/{dataset_id}/versions": (("d1",), dict(limit=5, cursor="c", status="completed")),
    "POST /v1/datasets/{dataset_id}/active-version": (("d1", "v1"), {}),
    "GET /v1/datasets/{dataset_id}/diff": (("d1", "v1", "v2"), dict(limit=5, cursor="c")),
    "GET /v1/datasets/{dataset_id}/fields": (("d1",), dict(version="v1")),
    "POST /v1/datasets/{dataset_id}/query": (("d1", [{"field": "price", "op": "lt", "value": 20}]),
                                             dict(version_id="v1", limit=5, cursor="c")),
    "POST /v1/datasets/{dataset_id}/extract": (("d1",), dict(schema=SCHEMA, instruction="i", profile="p",
                                                             version_id="v1", max_records=10, idempotency_key="key-5")),
    "PUT /v1/datasets/{dataset_id}/records/{record_id}/quarantine": (("d1", "r1"), dict(reason="spam")),
    "DELETE /v1/datasets/{dataset_id}/records/{record_id}/quarantine": (("d1", "r1"), {}),
    "POST /v1/search": (("lantern",), dict(limit=5)),
    "GET /v1/documents/{document_id}": (("doc1",), {}),
    "GET /v1/credits/balance": ((), {}),
    "GET /v1/health": ((), {}),
    "POST /v1/assets": (("https://e.example/page",), dict(classes=["images", "video"], max_items=10,
                                                          max_bytes=1_000_000, max_credits=50, idempotency_key="key-6")),
    "POST /v1/assets/quote": (("https://e.example/page",), dict(classes=["documents"], max_items=10,
                                                                max_bytes=1_000_000, max_credits=50)),
    "GET /v1/assets/{job_id}": (("job1",), dict(view="skipped", limit=50, cursor="c", wait_seconds=5)),
    "GET /v1/assets/{job_id}/files/{asset_id}": (("job1", "0123456789abcdef01234567"), {}),
}
COVERED = {route: entry for route, entry in COVERAGE["operations"].items() if "excluded" not in entry}


def test_every_operation_is_covered_or_excluded_and_every_declaration_holds() -> None:
    assert check_contracts.check_coverage(OPENAPI, COVERAGE) == []


def test_the_python_calls_table_covers_exactly_the_covered_operations() -> None:
    assert set(CALLS) == set(COVERED)


@pytest.mark.parametrize("route", sorted(COVERED))
def test_each_method_sends_exactly_what_coverage_declares(route: str) -> None:
    entry = COVERED[route]
    name = entry["python"]
    assert callable(getattr(Scrawl, name, None)) and callable(getattr(AsyncScrawl, name, None)), name
    args, kwargs = CALLS[route]
    rec = Recorder()
    getattr(make_client(rec), name)(*args, **kwargs)
    assert len(rec.requests) == 1
    recorded = as_recorded(rec.requests[0])
    problems = check_contracts.check_request(OPENAPI, route, recorded, entry["sends"], exact=True)
    assert problems == []
    # Path parameters are the method's leading positional arguments, in template order: the exact path.
    template = route.split(" ", 1)[1]
    values = iter(args)
    expected = "/".join(quote(str(next(values)), safe="") if part.startswith("{") else part
                        for part in template.split("/"))
    assert recorded["path"] == expected


@pytest.mark.parametrize("route", sorted(COVERED))
async def test_the_async_client_sends_the_same_request(route: str) -> None:
    name = COVERED[route]["python"]
    args, kwargs = CALLS[route]
    sync_rec, async_rec = Recorder(), Recorder()
    getattr(make_client(sync_rec), name)(*args, **kwargs)
    async with make_async_client(async_rec) as client:
        await getattr(client, name)(*args, **kwargs)
    sync_req, async_req = as_recorded(sync_rec.requests[0]), as_recorded(async_rec.requests[0])
    assert {k: v for k, v in sync_req.items() if k != "headers"} == {k: v for k, v in async_req.items() if k != "headers"}
    assert ("idempotency-key" in sync_req["headers"]) == ("idempotency-key" in async_req["headers"])


def test_sync_and_async_clients_have_the_same_public_methods() -> None:
    def public(cls: type) -> set[str]:
        return {name for name, _ in inspect.getmembers(cls, callable) if not name.startswith("_")}

    assert public(Scrawl) == public(AsyncScrawl)


def _parser_for(words: list[str]) -> argparse.ArgumentParser:
    parser: argparse.ArgumentParser = build_parser()
    for word in words:
        actions = [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]
        assert actions, f"{' '.join(words)}: {word!r} has no subcommands"
        assert word in actions[0].choices, f"no CLI command {' '.join(words)!r}"
        parser = actions[0].choices[word]
    return parser


@pytest.mark.parametrize("route", sorted(COVERED))
def test_each_covered_operation_has_its_cli_command(route: str) -> None:
    words = COVERED[route]["cli"].split()
    command = [w for w in words if not w.startswith("--")]
    flags = [w for w in words if w.startswith("--")]
    parser = _parser_for(command)
    options = {flag for action in parser._actions for flag in action.option_strings}
    assert set(flags) <= options, (route, flags)


def test_the_vendored_contracts_match_their_manifest_and_the_sdk_records_its_digest() -> None:
    assert check_contracts.verify_manifest() == []
    digest = check_contracts.manifest_digest()
    assert scrawl.__contract__ == scrawl.CONTRACT_DIGEST == digest
    ts_contract = (REPO / "typescript" / "src" / "contract.js").read_text(encoding="utf-8")
    assert f'"{digest}"' in ts_contract


def test_the_live_suite_exercises_every_covered_operation() -> None:
    """Static check (no server needed): each covered route is named by a live test's ``covers(...)``."""
    named: set[str] = set()
    source = Path(__file__).with_name("live") / "test_live.py"
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "covers":
            named.update(arg.value for arg in node.args if isinstance(arg, ast.Constant))
    assert named == set(COVERED), f"missing {sorted(set(COVERED) - named)}, stale {sorted(named - set(COVERED))}"
