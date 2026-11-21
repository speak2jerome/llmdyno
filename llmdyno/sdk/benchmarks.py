"""Benchmarks and suites: built-in, your own and imported (SWE-bench, Aider polyglot)."""
from __future__ import annotations

from typing import Sequence

from ._core import Job, call, covers

__all__ = ["list_benchmarks", "list_suites", "import_swebench", "import_polyglot"]

# Web API routes this module does not cover yet (see sdk/parity.py); remove each one as it gets a library call.
PENDING_ROUTES = (
    "POST /api/benchmarks",
    "DELETE /api/benchmarks/{bid}",
    "GET /api/benchmarks/{bid}",
    "PUT /api/benchmarks/{bid}",
    "POST /api/benchmarks/{bid}/duplicate",
    "GET /api/benchmarks/{bid}/export",
    "GET /api/benchmarks/{bid}/spec",
    "POST /api/benchmarks/{bid}/validate",
    "GET /api/imports",
    "POST /api/imports/polyglot/image",
    "POST /api/imports/swebench/harness",
    "DELETE /api/imports/{kind}",
    "POST /api/suites",
    "DELETE /api/suites/{sid}",
    "PUT /api/suites/{sid}",
    "POST /api/upload/benchmark",
)

_SUMMARY_KEYS = ("id", "title", "category", "difficulty", "languages", "summary", "n_stages", "expected_minutes",
                 "builtin")


@covers("GET /api/benchmarks")
def list_benchmarks(category: str | None = None, search: str | None = None) -> list:
    """Benchmarks in the data folder (built-in, your own and imported), as dicts with id, title, category, …"""
    out = []
    for b in call("benchmarks.list_benchmarks"):
        if category and b.get("category", "").lower() != category.lower():
            continue
        text = f"{b['id']} {b.get('title', '')} {b.get('summary', '')} {' '.join(b.get('tags') or [])}".lower()
        if search and search.lower() not in text:
            continue
        out.append({k: b.get(k) for k in _SUMMARY_KEYS})
    return out


@covers("GET /api/suites")
def list_suites() -> list:
    """Suites (named groups of benchmarks): built-in ones plus yours and those created by imports."""
    return call("benchmarks.list_suites")


@covers("POST /api/imports/swebench")
def import_swebench(dataset: str = "verified_mini", *, limit: int | None = None,
                    instance_ids: Sequence[str] | None = None, quiet: bool = False) -> dict:
    """Import SWE-bench tasks as benchmarks: dataset "verified" (500), "lite" (300) or "verified_mini" (50).
    Grading needs the official harness: setup(swebench=True). Returns the new benchmark ids and suite id."""
    r = call("imports.import_swebench", body={"dataset": dataset, "limit": limit or 0,
                                              "instance_ids": list(instance_ids or [])})
    return Job(r["job_id"]).wait(quiet=quiet)


@covers("POST /api/imports/polyglot")
def import_polyglot(languages: Sequence[str] | None = None, *, quiet: bool = False) -> dict:
    """Import Aider's polyglot benchmark (cpp, go, java, javascript, python, rust). Needs the toolchain image:
    setup(polyglot=True)."""
    r = call("imports.import_polyglot", body={"languages": list(languages) if languages else None})
    return Job(r["job_id"]).wait(quiet=quiet)
