"""MLflow: one MLflow run per configuration ("llmdyno[mlflow]").

    results.log_to_mlflow(experiment="coding-agents")                     # the tracking server MLflow is set up for
    results.log_to_mlflow(tracking_uri="http://localhost:5000")           # an MLflow server
    results.log_to_mlflow(tracking_uri="sqlite:///mlflow.db")             # a local database (needs full mlflow)

Params are the profile's settings, model and harness; metrics are the scores (0-100), time, cost, speed and VRAM;
artifacts are the configuration's result JSON, its runs, and each run's transcript."""
from __future__ import annotations

import re

from .. import __version__
from . import require
from .tracking import config_metrics, config_params, runs_of, transcript_jsonl

__all__ = ["log_to_mlflow"]


def _key(k: str) -> str:
    return re.sub(r"[^\w\-. /]", "_", k)[:250]


def log_to_mlflow(results, experiment: str = "llmdyno", tracking_uri: str | None = None,
                  transcripts: bool = True) -> list:
    """Log every configuration of these results as an MLflow run; returns the MLflow run ids."""
    mlflow = require("mlflow", "mlflow", "log_to_mlflow()")
    if tracking_uri:
        mlflow.set_tracking_uri(tracking_uri)
    mlflow.set_experiment(experiment)
    ids = []
    for row in results.leaderboard():
        with mlflow.start_run(run_name=f"{row['profile']} · {row['harness']}") as run:
            mlflow.set_tags({"llmdyno.version": __version__, "llmdyno.plans": ",".join(results.plan_ids),
                             "llmdyno.profile_id": row["profile_id"], "llmdyno.harness_id": row["harness_id"]})
            mlflow.log_params({_key(k): str(v)[:500] for k, v in config_params(results, row).items()})
            mlflow.log_metrics(config_metrics(row))
            runs = runs_of(results, row)
            mlflow.log_dict({"configuration": row, "weights": results.data.get("weights")}, "llmdyno/configuration.json")
            mlflow.log_dict({"runs": runs}, "llmdyno/runs.json")
            if transcripts:
                for r in runs:
                    text = transcript_jsonl(r["run_id"])
                    if text:
                        mlflow.log_text(text, f"transcripts/{r['benchmark_id']}-{r['iteration']}-{r['run_id']}.jsonl")
            ids.append(run.info.run_id)
    return ids
