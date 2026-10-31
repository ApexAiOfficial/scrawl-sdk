"""Every example runs to completion against the fake ApexAPI, and every request it sends is contract-valid."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
RUNS = {
    "scrape_to_markdown.py": ["https://shop.example/products/lamp"],
    "map_site.py": ["https://shop.example/", "50"],
    "batch_with_wait.py": ["https://shop.example/a", "https://shop.example/b"],
    "crawl_to_dataset.py": ["example-target"],
    "extract_with_ai_profile.py": ["https://shop.example/products/lamp"],
    "ask_with_citations.py": ["Which lamp is cheapest?", "ds-1"],
    "download_artifacts.py": ["https://shop.example/products/lamp", "{tmp}/artifacts"],
    "browser_rendering.py": ["https://shop.example/app"],
    "errors_and_retries.py": ["https://shop.example/products/lamp"],
}


def test_every_example_is_listed() -> None:
    assert sorted(p.name for p in EXAMPLES.glob("*.py")) == sorted(RUNS)


@pytest.mark.parametrize("name", sorted(RUNS))
def test_example_runs_against_the_fake_api(name: str, fake_api, tmp_path: Path) -> None:
    from fake_apexapi import API_KEY

    base_url, fake = fake_api
    env = {key: value for key, value in os.environ.items() if not key.startswith("SCRAWL_")}
    env.update(SCRAWL_BASE_URL=base_url, SCRAWL_API_KEY=API_KEY, SCRAWL_AI_PROVIDER="example",
               SCRAWL_AI_API_KEY="sk-ai-example-test")
    args = [arg.replace("{tmp}", str(tmp_path)) for arg in RUNS[name]]
    result = subprocess.run([sys.executable, str(EXAMPLES / name), *args], env=env, capture_output=True, text=True,
                            timeout=60, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "an example prints its result"
    assert fake.requests, "the example talked to the API"
    assert fake.problems == []
    assert "sk-ai-example-test" not in result.stdout + result.stderr
