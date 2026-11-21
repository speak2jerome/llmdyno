"""Hugging Face Hub: publish results as a dataset (Parquet tables plus a dataset card) and read them back
("llmdyno[hub]").

    results.push_to_hub("you/llmdyno-results")                 # private by default; token from `hf auth login`
    r = llmdyno.load_results_from_hub("you/llmdyno-results")    # a Results object again"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from .. import __version__
from . import require
from .data import to_parquet

__all__ = ["push_results", "load_results"]

TABLES = ("configs", "runs", "cells")


def _card(results, repo_id: str) -> str:
    lb = results.leaderboard()
    rows = "\n".join(f"| {r['rank']} | {r['profile']} | {r['harness']} | {r['final']} | {r['correctness']} | "
                     f"{r['quality']} |" for r in lb[:20])
    w = results.data.get("weights") or {}
    return f"""---
tags: [llmdyno, benchmark, coding-agents, llm-evaluation]
configs:
- config_name: configs
  data_files: configs.parquet
- config_name: runs
  data_files: runs.parquet
- config_name: cells
  data_files: cells.parquet
---

# {repo_id}

Coding-agent benchmark results measured with [LLMDyno](https://github.com/speak2jerome/llmdyno) {__version__}:
real agent harnesses in offline sandboxes, graded by hidden tests, static analysis, behaviour probes and LLM judges.

Score weights: correctness {w.get('correctness')}, instruction following {w.get('instruction_following')},
code quality {w.get('quality')}, efficiency {w.get('efficiency')} (scores are 0-100).

| # | Profile | Harness | Final | Correctness | Quality |
|---|---|---|---|---|---|
{rows}

Tables: `configs` (one row per profile × harness), `runs` (one row per run), `cells` (profile × harness × benchmark).
`results.json` holds everything LLMDyno computed; `llmdyno.load_results_from_hub("{repo_id}")` loads it back.
"""


def push_results(results, repo_id: str, private: bool = True, token: str | None = None,
                 commit_message: str | None = None) -> str:
    """Upload the results as a Hub dataset repository (created if needed); returns its URL."""
    hub = require("huggingface_hub", "hub", "push_to_hub()")
    api = hub.HfApi(token=token)
    api.create_repo(repo_id, repo_type="dataset", private=private, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        folder = Path(tmp)
        for level in TABLES:
            to_parquet(results.rows(level), folder / f"{level}.parquet")
        (folder / "results.json").write_text(json.dumps({"llmdyno_version": __version__, "plan_ids": results.plan_ids,
                                                         "data": results.data}, default=str), encoding="utf-8")
        (folder / "README.md").write_text(_card(results, repo_id), encoding="utf-8")
        api.upload_folder(repo_id=repo_id, repo_type="dataset", folder_path=str(folder),
                          commit_message=commit_message or f"LLMDyno results ({len(results.leaderboard())} configurations)")
    return f"https://huggingface.co/datasets/{repo_id}"


def load_results(repo_id: str, revision: str | None = None, token: str | None = None):
    """Results published with push_to_hub(), as a Results object."""
    hub = require("huggingface_hub", "hub", "load_results_from_hub()")
    from ..sdk.results import Results
    path = hub.hf_hub_download(repo_id, "results.json", repo_type="dataset", revision=revision, token=token)
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return Results(doc["data"], doc.get("plan_ids") or [])
