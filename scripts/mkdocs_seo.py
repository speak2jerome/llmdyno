"""MkDocs hook for the docs site's search and share metadata.

- Gives each page the description listed under ``extra.page_descriptions`` in mkdocs.yml, keyed by the page's path
  inside docs/, so the Markdown files need no front matter (front matter shows up as a table on GitHub).
- Puts the package version in ``extra.version`` for the structured data on the home page.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def on_config(config):
    init = (ROOT / "llmdyno" / "__init__.py").read_text(encoding="utf-8")
    config["extra"]["version"] = re.search(r'__version__ = "([^"]+)"', init).group(1)
    return config


def on_page_markdown(markdown, page, config, files):
    description = (config["extra"].get("page_descriptions") or {}).get(page.file.src_uri)
    if description and "description" not in page.meta:
        page.meta["description"] = description
    return markdown
