"""OpenTelemetry: each run as a trace with one span per model request, using the GenAI semantic conventions, so any
OTLP backend (Phoenix, Langfuse, Datadog, Honeycomb, Grafana Tempo, …) can show it ("llmdyno[otel]").

    results.to_otel()                                         # OTEL_EXPORTER_OTLP_ENDPOINT / _HEADERS from the environment
    results.to_otel(endpoint="http://localhost:6006/v1/traces")   # e.g. a local Phoenix
    results.to_otel(tracer_provider=my_provider)              # your own provider and exporters

Spans keep the real start and end times of the runs and requests."""
from __future__ import annotations

from .. import __version__
from ..errors import LLMDynoError
from . import require

__all__ = ["export_otel"]


def _ns(t) -> int | None:
    return int(float(t) * 1e9) if t else None


def export_otel(results, tracer_provider=None, endpoint: str | None = None, headers: dict | None = None,
                service_name: str = "llmdyno", requests: bool = True) -> int:
    """Send these results' runs as OpenTelemetry traces; returns how many spans were made."""
    trace = require("opentelemetry.trace", "otel", "to_otel()")
    own = tracer_provider is None
    if own:
        sdk_trace = require("opentelemetry.sdk.trace", "otel", "to_otel()")
        resources = require("opentelemetry.sdk.resources", "otel", "to_otel()")
        export = require("opentelemetry.sdk.trace.export", "otel", "to_otel()")
        otlp = require("opentelemetry.exporter.otlp.proto.http.trace_exporter", "otel", "to_otel()")
        tracer_provider = sdk_trace.TracerProvider(resource=resources.Resource.create({"service.name": service_name}))
        tracer_provider.add_span_processor(export.BatchSpanProcessor(otlp.OTLPSpanExporter(endpoint=endpoint,
                                                                                           headers=headers)))
    tracer = tracer_provider.get_tracer("llmdyno", __version__)
    labels = results._labels.get("profiles") or {}
    spans = 0
    from ..sdk.runs import Run
    for r in results.data.get("runs") or []:
        prof = labels.get(r["profile_id"]) or {}
        system = prof.get("vendor") or ("llama.cpp" if prof.get("kind") == "local" else "unknown")
        attrs = {"llmdyno.run_id": r["id"], "llmdyno.plan_id": r["plan_id"], "llmdyno.benchmark_id": r["benchmark_id"],
                 "llmdyno.harness_id": r["harness_id"], "llmdyno.profile": prof.get("name") or r["profile_id"],
                 "llmdyno.iteration": r.get("iteration") or 1, "llmdyno.status": r.get("status") or "",
                 "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": r["harness_id"],
                 "gen_ai.system": system, "gen_ai.provider.name": system,
                 "gen_ai.request.model": prof.get("model") or ""}
        for k in ("correctness", "instruction_following", "final", "quality", "cost_usd", "wall_s"):
            if isinstance(r.get(k), (int, float)):
                attrs[f"llmdyno.{k}"] = float(r[k])
        run_span = tracer.start_span(f"run {r['benchmark_id']}", start_time=_ns(r.get("started_at")), attributes=attrs)
        spans += 1
        ctx = trace.set_span_in_context(run_span)
        if requests:
            try:
                recs = Run(r["id"]).requests()
            except LLMDynoError:
                recs = []
            for q in recs:
                usage = q.get("usage_norm") or {}
                req_attrs = {"gen_ai.operation.name": "chat", "gen_ai.system": system, "gen_ai.provider.name": system,
                             "gen_ai.request.model": q.get("model") or prof.get("model") or "",
                             "gen_ai.usage.input_tokens": int(usage.get("input") or 0),
                             "gen_ai.usage.output_tokens": int(usage.get("output") or 0),
                             "llmdyno.seq": q.get("seq") or 0, "llmdyno.api": q.get("api") or ""}
                if q.get("finish_reason"):
                    req_attrs["gen_ai.response.finish_reasons"] = [str(q["finish_reason"])]
                if usage.get("cached") is not None:
                    req_attrs["gen_ai.usage.cached_input_tokens"] = int(usage["cached"])
                for k in ("cost_usd", "ttft_s", "wall_s"):
                    if isinstance(q.get(k), (int, float)):
                        req_attrs[f"llmdyno.{k}"] = float(q[k])
                start = q.get("ts") or (q.get("t_end") - (q.get("wall_s") or 0) if q.get("t_end") else None)
                span = tracer.start_span(f"chat {req_attrs['gen_ai.request.model']}".strip(), context=ctx,
                                         start_time=_ns(start), attributes=req_attrs)
                span.end(end_time=_ns(q.get("t_end")))
                spans += 1
        run_span.end(end_time=_ns(r.get("ended_at")))
    if own:
        tracer_provider.force_flush()
        tracer_provider.shutdown()
    return spans
