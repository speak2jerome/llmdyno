"""Working with other tools: Inspect AI tasks and datasets, and regression checks for CI."""
from __future__ import annotations

import json
from pathlib import Path

from ..errors import InvalidError

__all__ = ["inspect_task", "import_inspect_samples", "compare_results"]


def inspect_task(benchmarks, profile, harness: str = "pi", name: str = "llmdyno", **bench_options):
    """An Inspect AI Task running LLMDyno benchmarks (or suites) with this profile and harness; evaluate it with
    inspect_ai.eval(task, model="none/none"). Needs "llmdyno[inspect]"."""
    from ..integrations.inspect_eval import inspect_task as make
    return make(benchmarks, profile, harness=harness, name=name, **bench_options)


def import_inspect_samples(samples, prefix: str = "inspect", suite: str | None = None, answer_file: str = "answer.txt",
                           timeout_s: int = 600):
    """LLMDyno benchmarks from an Inspect AI dataset: the agent writes its answer to answer_file and the grader
    checks it holds the sample's target. Returns a Suite of them. Needs "llmdyno[inspect]"."""
    from ..integrations.inspect_eval import import_inspect_samples as imp
    return imp(samples, prefix=prefix, suite=suite, answer_file=answer_file, timeout_s=timeout_s)


def _leaderboard(x) -> list:
    from .results import Results, results
    if isinstance(x, Results):
        return x.leaderboard()
    if isinstance(x, (str, Path)) and str(x).endswith(".json"):
        p = Path(x).expanduser()
        if not p.is_file():
            raise InvalidError(f"{p} does not exist")
        doc = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(doc, dict) and isinstance(doc.get("leaderboard"), list):
            return doc["leaderboard"]
        if isinstance(doc, list):
            return doc
        raise InvalidError(f"{p} is not a results file (save one with Results.to_json() or `llmdyno results --json`)")
    return results(x).leaderboard()


def compare_results(current, baseline, *, metric: str = "final", max_drop: float = 2.0,
                    allow_missing: bool = False) -> dict:
    """Compare results with a baseline, configuration by configuration (profile × harness), for CI. current and
    baseline are Results, plan ids, or results JSON files (Results.to_json(), `llmdyno results --json`).
    A configuration regresses when its metric (final, correctness, quality, … on 0-100) drops by more than max_drop
    points; one missing from current fails the check unless allow_missing. Returns {"ok", "rows", "regressions",
    "missing", "new"}."""
    cur = {(r["profile"], r["harness"]): r for r in _leaderboard(current)}
    base = {(r["profile"], r["harness"]): r for r in _leaderboard(baseline)}
    rows, regressions = [], []
    for key in sorted(set(cur) | set(base)):
        b, c = (base.get(key) or {}).get(metric), (cur.get(key) or {}).get(metric)
        change = None if b is None or c is None else round(c - b, 2)
        row = {"profile": key[0], "harness": key[1], "baseline": b, "current": c, "change": change}
        rows.append(row)
        if change is not None and change < -abs(max_drop):
            regressions.append(row)
    missing = [r for r in rows if r["current"] is None and r["baseline"] is not None]
    new = [r for r in rows if r["baseline"] is None and r["current"] is not None]
    ok = not regressions and (allow_missing or not missing)
    return {"ok": ok, "metric": metric, "max_drop": max_drop, "rows": rows, "regressions": regressions,
            "missing": missing, "new": new}
