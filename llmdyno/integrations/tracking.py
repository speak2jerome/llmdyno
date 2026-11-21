"""Shared pieces for the tracking integrations (MLflow, Weights & Biases, Langfuse, OpenTelemetry)."""
from __future__ import annotations

import json

from ..errors import LLMDynoError

__all__ = ["config_params", "config_metrics", "runs_of", "transcript_jsonl", "auto_log"]

METRICS = ("final", "correctness", "instruction_following", "quality", "efficiency", "pass_at_k", "runs",
           "wall_s_total", "cost_usd_total", "decode_tps", "peak_vram_mib")


def _flatten(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in (d or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        elif v is not None and v != "" and v != []:
            out[key] = v if isinstance(v, (int, float, str, bool)) else json.dumps(v)
    return out


def config_params(results, row: dict) -> dict:
    """What a configuration is: the profile's settings, model and harness, flattened for a tracking tool."""
    from ..sdk._core import call
    label = (results._labels.get("profiles") or {}).get(row["profile_id"]) or {}
    params = {"profile": row["profile"], "profile_id": row["profile_id"], "harness": row["harness"],
              "harness_id": row["harness_id"], "kind": label.get("kind"), "model": label.get("model"),
              "quant": label.get("quant"), "vendor": label.get("vendor")}
    try:
        prof = call("profiles.get_profile", pid=row["profile_id"])
        params.update(_flatten(prof.get("params") or {}, "param."))
        params.update(_flatten(prof.get("pricing") or {}, "pricing."))
    except LLMDynoError:
        pass                                   # the profile was deleted since; its label is enough
    params.update(_flatten({"weights": results.data.get("weights") or {}}))
    return {k: v for k, v in params.items() if v not in (None, "")}


def config_metrics(row: dict) -> dict:
    return {k: float(row[k]) for k in METRICS if isinstance(row.get(k), (int, float))}


def runs_of(results, row: dict) -> list:
    return [r for r in results.runs() if r["run_id"] in {
        x["id"] for x in results.data.get("runs") or []
        if x["profile_id"] == row["profile_id"] and x["harness_id"] == row["harness_id"]}]


def transcript_jsonl(run_id: str) -> str:
    """A run's transcript as JSON lines ("" when it has none, such as the bundled sample's runs)."""
    from ..sdk.runs import Run
    try:
        events = Run(run_id).transcript()
    except LLMDynoError:
        return ""
    return "".join(json.dumps(e, default=str) + "\n" for e in events)


def auto_log(results, spec) -> dict:
    """bench(auto_log=…): "mlflow", ["mlflow", "otel"], or {"mlflow": {"experiment": "x"}, "wandb": {"mode": "offline"}}."""
    if not spec:
        return {}
    targets = {spec: {}} if isinstance(spec, str) else dict(spec) if isinstance(spec, dict) else {s: {} for s in spec}
    out = {}
    for name, options in targets.items():
        fn = {"mlflow": results.log_to_mlflow, "wandb": results.log_to_wandb, "langfuse": results.log_to_langfuse,
              "otel": results.to_otel}.get(name)
        if fn is None:
            raise LLMDynoError(f"auto_log knows mlflow, wandb, langfuse and otel, not {name!r}")
        out[name] = fn(**(options or {}))
    return out
