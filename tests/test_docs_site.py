"""The docs site's search metadata stays in step with its pages."""
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
SITE = "https://speak2jerome.github.io/llmdyno/"


def _config():
    return yaml.safe_load((ROOT / "mkdocs.yml").read_text(encoding="utf-8"))


def _nav_files(nav):
    for item in nav:
        for value in item.values():
            if isinstance(value, list):
                yield from _nav_files(value)
            else:
                yield value


def _site_url(md):
    """docs/LIBRARY.md is served at LIBRARY/, docs/reference/index.md at reference/."""
    path = md.removesuffix(".md")
    if path == "index":
        return SITE
    return SITE + (path.removesuffix("index") if path.endswith("/index") else path + "/")


def test_every_page_has_a_description():
    config = _config()
    descriptions = config["extra"]["page_descriptions"]
    assert set(descriptions) == set(_nav_files(config["nav"])) - {"index.md"}
    for page, text in descriptions.items():
        assert 50 <= len(text) <= 200, f"{page}: search engines cut descriptions around 160 characters"
    assert len(config["site_description"]) <= 200


def test_llms_txt_links_every_page():
    links = re.findall(r"\((" + re.escape(SITE) + r"[^)]*)\)", (ROOT / "docs" / "llms.txt").read_text(encoding="utf-8"))
    assert set(links) == {_site_url(page) for page in _nav_files(_config()["nav"])}
