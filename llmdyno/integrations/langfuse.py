"""Langfuse: each run as a trace, each model request as a generation with tokens and cost, grader scores as Langfuse
scores ("llmdyno[langfuse]").

    results.log_to_langfuse()          # LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_HOST from the environment
    results.log_to_langfuse(client=Langfuse(public_key=..., secret_key=..., host=...))

The run's agent is an "agent" observation; under it one "generation" per request through LLMDyno's proxy, with the
messages sent, the reply, usage, cost and time to first token, read from the run's transcript and proxy log. Scores:
correctness, instruction following, quality and final. Langfuse's SDK stamps observations with the time you log them;
the runs' real start and end times are kept in metadata. For exact timings in Langfuse's timeline, send the same data
with results.to_otel(endpoint=<your Langfuse OTLP endpoint>) instead."""
from __future__ import annotations

from .. import __version__
from ..errors import LLMDynoError
from . import require

__all__ = ["log_to_langfuse"]


def _pairs(transcript) -> dict:
    """seq -> (messages sent, reply blocks) from a run's transcript."""
    out = {}
    for req, resp in transcript._pairs():
        out[resp.get("seq")] = ((req or {}).get("new") or [], resp.get("blocks") or [])
    return out


def log_to_langfuse(results, client=None, public_key: str | None = None, secret_key: str | None = None,
                    host: str | None = None, flush: bool = True) -> list:
    """Log every run of these results to Langfuse; returns the trace ids."""
    if client is None:
        lf = require("langfuse", "langfuse", "log_to_langfuse()")
        client = lf.Langfuse(public_key=public_key, secret_key=secret_key, host=host, release=f"llmdyno {__version__}")
    from ..sdk.runs import Run
    labels = results._labels.get("profiles") or {}
    blabels = results._labels.get("benchmarks") or {}
    trace_ids = []
    for r in results.data.get("runs") or []:
        prof = labels.get(r["profile_id"]) or {}
        meta = {"llmdyno_run_id": r["id"], "plan_id": r["plan_id"], "benchmark_id": r["benchmark_id"],
                "benchmark": (blabels.get(r["benchmark_id"]) or {}).get("title"), "harness": r["harness_id"],
                "profile": prof.get("name") or r["profile_id"], "iteration": r.get("iteration"),
                "status": r.get("status"), "started_at": r.get("started_at"), "ended_at": r.get("ended_at"),
                "wall_s": r.get("wall_s"), "cost_usd": r.get("cost_usd")}
        root = client.start_observation(name=f"{r['benchmark_id']} · {prof.get('name') or r['profile_id']}",
                                        as_type="agent", metadata=meta, model=prof.get("model") or None)
        try:
            run = Run(r["id"])
            try:
                reqs, pairs = run.requests(), _pairs(run.transcript())
            except LLMDynoError:
                reqs, pairs = [], {}
            for q in reqs:
                usage = q.get("usage_norm") or {}
                sent, reply = pairs.get(q.get("seq"), (None, None))
                gen = root.start_observation(
                    name="chat", as_type="generation", model=q.get("model") or prof.get("model") or None,
                    input=sent, output=reply,
                    usage_details={k: int(v) for k, v in (("input", usage.get("input")), ("output", usage.get("output")),
                                                          ("cache_read_input_tokens", usage.get("cached")),
                                                          ("reasoning", usage.get("reasoning"))) if v},
                    cost_details={"total": float(q["cost_usd"])} if q.get("cost_usd") is not None else None,
                    metadata={"seq": q.get("seq"), "ts": q.get("ts"), "t_end": q.get("t_end"), "ttft_s": q.get("ttft_s"),
                              "wall_s": q.get("wall_s"), "finish_reason": q.get("finish_reason"), "api": q.get("api")})
                gen.end()
            for name in ("correctness", "instruction_following", "quality", "final"):
                if isinstance(r.get(name), (int, float)):
                    root.score_trace(name=name, value=float(r[name]))
            trace_ids.append(getattr(root, "trace_id", None))
        finally:
            root.end()
    if flush:
        client.flush()
    return trace_ids
