"""One version everywhere, a changelog entry for it, a working bump script and a guarded database schema."""
import json
import re
import runpy
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from llmdyno import __version__, db

ROOT = Path(__file__).resolve().parents[1]
SEMVER = r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(-[0-9A-Za-z.-]+)?$"


def test_version_is_semver_and_consistent():
    assert re.match(SEMVER, __version__)
    assert json.loads((ROOT / "frontend/package.json").read_text())["version"] == __version__
    lock = json.loads((ROOT / "frontend/package-lock.json").read_text())
    assert lock["version"] == __version__ and lock["packages"][""]["version"] == __version__


def test_changelog_has_this_release():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{__version__}]" in text and "## [Unreleased]" in text


BUMPED = {"INIT": "llmdyno/__init__.py", "PKG": "frontend/package.json", "LOCK": "frontend/package-lock.json",
          "CHANGELOG": "CHANGELOG.md", "CITATION": "CITATION.cff", "BUG_TEMPLATE": ".github/ISSUE_TEMPLATE/bug_report.yml",
          "JS_PKG": "js/package.json", "JS_LOCK": "js/package-lock.json", "JS_VERSION": "js/src/version.ts",
          "CODEMETA": "codemeta.json"}


def test_bump_script(tmp_path, monkeypatch):
    mod = runpy.run_path(str(ROOT / "scripts/bump_version.py"), run_name="bump")
    g = mod["main"].__globals__
    # every path the script writes must be redirected here, or the test edits the real repository
    targets = {k for k, v in g.items() if k.isupper() and isinstance(v, Path) and v.suffix and v != ROOT}
    assert targets == set(BUMPED), f"bump_version.py writes {sorted(targets)}; add them to BUMPED in this test"
    before = {rel: (ROOT / rel).read_bytes() for rel in BUMPED.values()}
    for name, rel in BUMPED.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
        g[name] = tmp_path / rel
    monkeypatch.setattr(sys, "argv", ["bump_version.py", "minor"])
    mod["main"]()
    assert {rel: (ROOT / rel).read_bytes() for rel in BUMPED.values()} == before, "the test changed real files"
    major, minor, _ = (int(x) for x in __version__.split("-")[0].split("."))
    new = f"{major}.{minor + 1}.0"
    assert f'__version__ = "{new}"' in (tmp_path / "llmdyno/__init__.py").read_text()
    assert json.loads((tmp_path / "frontend/package.json").read_text())["version"] == new
    changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{new}] - " in changelog and f"[{new}]: https://github.com/speak2jerome/llmdyno/compare/v{__version__}...v{new}" in changelog
    assert f"version: {new}" in (tmp_path / "CITATION.cff").read_text(encoding="utf-8")
    js_lock = json.loads((tmp_path / "js/package-lock.json").read_text())
    assert json.loads((tmp_path / "js/package.json").read_text())["version"] == new
    assert js_lock["version"] == js_lock["packages"][""]["version"] == new
    assert f'VERSION = "{new}"' in (tmp_path / "js/src/version.ts").read_text(encoding="utf-8")
    assert json.loads((tmp_path / "codemeta.json").read_text(encoding="utf-8"))["version"] == new


def test_project_metadata_agrees():
    """codemeta.json, CITATION.cff, pyproject and package.json name the same version, author and project page."""
    meta = json.loads((ROOT / "codemeta.json").read_text(encoding="utf-8"))
    pkg = json.loads((ROOT / "js/package.json").read_text(encoding="utf-8"))
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    citation = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    assert meta["version"] == pkg["version"] == __version__ and f"version: {__version__}" in citation
    page = meta["url"]
    assert pkg["homepage"] == page and f'Homepage = "{page}"' in pyproject and f'url: "{page}"' in citation
    author = meta["author"][0]
    assert pkg["author"]["email"] == author["email"] and author["email"] in pyproject and author["email"] in citation


def test_database_schema_version(tmp_path):
    path = tmp_path / "schema.db"
    eng = create_engine(f"sqlite:///{path}")
    db.Base.metadata.create_all(eng)
    db._migrate(eng)
    assert sqlite3.connect(path).execute("PRAGMA user_version").fetchone()[0] == db.SCHEMA_VERSION


def test_newer_database_is_refused(tmp_path):
    path = tmp_path / "future.db"
    con = sqlite3.connect(path)
    con.execute(f"PRAGMA user_version = {db.SCHEMA_VERSION + 1}")
    con.close()
    with pytest.raises(RuntimeError, match="newer LLMDyno"):
        db._migrate(create_engine(f"sqlite:///{path}"))


def test_readme_links_work_on_pypi():
    """README.md is the PyPI project page, where relative links and images are broken: they must be absolute."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    relative = re.findall(r'(?:src|href)="(?!https?:|#|mailto:)[^"]+"|\]\((?!https?:|#|mailto:)[^)\s]+\)', text)
    assert not relative, f"make these absolute (raw.githubusercontent.com for images): {relative}"
