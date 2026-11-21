"""Weights & Biases: the leaderboard and every run as W&B tables, transcripts as an artifact ("llmdyno[wandb]").

    results.log_to_wandb(project="coding-agents")
    results.log_to_wandb(project="coding-agents", mode="offline")       # no account or network needed; sync later"""
from __future__ import annotations

import tempfile
from pathlib import Path

from .. import __version__
from . import require
from .tracking import config_params, transcript_jsonl

__all__ = ["log_to_wandb"]


def _table(wandb, rows: list):
    cols = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    data = [[r.get(c) if isinstance(r.get(c), (int, float, str, bool, type(None))) else str(r.get(c)) for c in cols]
            for r in rows]
    return wandb.Table(columns=cols, data=data)


def log_to_wandb(results, project: str = "llmdyno", entity: str | None = None, name: str | None = None,
                 mode: str | None = None, dir: str | None = None, transcripts: bool = True) -> str:
    """Log these results as one W&B run: tables "leaderboard", "configurations" (with profile settings) and "runs",
    summary metrics for the best configuration, and an artifact of transcripts. Returns the W&B run id."""
    wandb = require("wandb", "wandb", "log_to_wandb()")
    run = wandb.init(project=project, entity=entity, name=name or f"llmdyno {', '.join(results.plan_ids) or 'results'}",
                     mode=mode, dir=dir, job_type="benchmark",
                     config={"llmdyno_version": __version__, "plans": results.plan_ids,
                             "weights": results.data.get("weights"), "quality_weights": results.data.get("quality_weights")})
    try:
        lb = results.leaderboard()
        run.log({"leaderboard": _table(wandb, lb),
                 "configurations": _table(wandb, [{**row, **config_params(results, row)} for row in lb]),
                 "runs": _table(wandb, results.runs())})
        best = results.best()
        if best:
            run.summary.update({f"best/{k}": v for k, v in best.items() if isinstance(v, (int, float))})
            run.summary["best/configuration"] = f"{best['profile']} · {best['harness']}"
        if transcripts:
            art = wandb.Artifact(f"llmdyno-transcripts-{run.id}", type="transcripts")
            with tempfile.TemporaryDirectory() as tmp:
                n = 0
                for r in results.runs():
                    text = transcript_jsonl(r["run_id"])
                    if text:
                        p = Path(tmp) / f"{r['run_id']}.jsonl"
                        p.write_text(text, encoding="utf-8")
                        art.add_file(str(p), name=f"{r['benchmark_id']}/{r['run_id']}.jsonl")
                        n += 1
                if n:
                    run.log_artifact(art)
        return run.id
    finally:
        run.finish()
