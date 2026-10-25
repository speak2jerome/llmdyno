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


def test_bump_script(tmp_path, monkeypatch):
    for rel in ("llmdyno/__init__.py", "frontend/package.json", "frontend/package-lock.json", "CHANGELOG.md"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, tmp_path / rel)
    mod = runpy.run_path(str(ROOT / "scripts/bump_version.py"), run_name="bump")
    g = mod["main"].__globals__
    g.update(INIT=tmp_path / "llmdyno/__init__.py", PKG=tmp_path / "frontend/package.json",
             LOCK=tmp_path / "frontend/package-lock.json", CHANGELOG=tmp_path / "CHANGELOG.md")
    monkeypatch.setattr(sys, "argv", ["bump_version.py", "minor"])
    mod["main"]()
    major, minor, _ = (int(x) for x in __version__.split("-")[0].split("."))
    new = f"{major}.{minor + 1}.0"
    assert f'__version__ = "{new}"' in (tmp_path / "llmdyno/__init__.py").read_text()
    assert json.loads((tmp_path / "frontend/package.json").read_text())["version"] == new
    changelog = (tmp_path / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [{new}] - " in changelog and f"[{new}]: https://github.com/speak2jerome/llmdyno/compare/v{__version__}...v{new}" in changelog


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
