"""Quick profile test: load (local), measure speed and real VRAM, and check that tool calling works."""
import json
import time
from pathlib import Path

from . import config, db, events, llm, memory, profiles
from .inference import llamacpp
from .runner import executor
from .system import specs as sysspecs

TOOLS = [{"name": "read_file", "description": "Read a text file from the project and return its contents.",
          "parameters": {"type": "object", "properties": {"path": {"type": "string", "description": "file path"}},
                         "required": ["path"]}}]
SPEED_PROMPT = ("Write a short Python function that returns the n-th Fibonacci number iteratively, then explain it "
                "in three sentences.")
TOOL_PROMPT = "Use the read_file tool to open notes/todo.txt. Do not answer from memory; call the tool."


def _gpu_used():
    g = sysspecs.primary_gpu(sysspecs.detect(force=True))
    return (g or {}).get("vram_used_mib")


def _shared():
    a = sysspecs.shared_gpu_usage_mib() or {}
    return max((x.get("shared", 0) for x in a.values()), default=None)


def tool_check(res):
    calls = res.get("tool_calls") or []
    if not calls:
        return False, "no tool call: the model answered in text" + (f" ({res['text'][:120]!r})" if res.get("text") else "")
    c = calls[0]
    args = c.get("args")
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return False, f"tool call arguments are not valid JSON: {args[:120]!r}"
    if c.get("name") != "read_file":
        return False, f"called an unknown tool {c.get('name')!r}"
    if not isinstance(args, dict) or "todo" not in str(args.get("path", "")):
        return False, f"unexpected arguments {json.dumps(args)[:120]}"
    return True, f"read_file({json.dumps(args)})"


def run(ctx):
    pid = ctx.params["profile_id"]
    prof, model, prov = executor.load_profile(pid)
    out = {"at": time.time(), "ok": False}
    try:
        if prof["kind"] == "local":
            if not model or model["status"] != "ready":
                raise RuntimeError("the model file is not downloaded yet")
            ctx.progress(0.05, "waiting for the GPU")
            with executor.GPU_LOCK:
                spec = sysspecs.detect(force=True)
                chk = memory.check(model["meta"], prof["params"], spec, os_name="nt" if sysspecs.IS_WIN else "posix")
                out["projected_gpu_mib"] = chk["memory"]["gpu_total"]
                before, shared0 = _gpu_used(), _shared()
                ctx.progress(0.15, "loading the model")
                paths = [str(Path(model["local_dir"]) / f) for f in model["files"]]
                log = config.path("runs_dir") / "_smoke" / f"server_{pid}.log"
                try:
                    out["load_s"] = llamacpp.server.start(paths[0], profiles.launch_params(prof["params"]), log, ctx=ctx)
                    after, shared1 = _gpu_used(), _shared()
                    out["vram_used_mib"] = (after - before) if after is not None and before is not None else None
                    out["shared_delta_mib"] = (shared1 - shared0) if shared1 is not None and shared0 is not None else None
                    ctx.progress(0.5, "measuring speed")
                    r1 = llm.complete(prof, None, SPEED_PROMPT, max_tokens=400, json_mode=False)
                    t = (r1.get("usage") or {}).get("timings") or {}
                    out.update({"decode_tps": round(t.get("predicted_per_second") or 0, 1) or None,
                                "prefill_tps": round(t.get("prompt_per_second") or 0, 1) or None,
                                "sample": r1["text"][:400]})
                    ctx.progress(0.8, "checking tool calls")
                    r2 = llm.complete(prof, None, TOOL_PROMPT, max_tokens=1024, json_mode=False, tools=TOOLS)
                    out["tool_call_ok"], out["tool_call_detail"] = tool_check(r2)
                finally:
                    llamacpp.server.stop()
            spill = (out.get("shared_delta_mib") or 0) > 256
            out["spill_detected"] = spill
            out["ok"] = out["tool_call_ok"] and not spill
            if spill:
                out["error"] = (f"{out['shared_delta_mib']} MiB spilled into shared system memory: the model does not fit "
                                "in free VRAM right now.")
        else:
            ctx.progress(0.2, "calling the provider")
            t0 = time.time()
            r1 = llm.complete(prof, prov, SPEED_PROMPT, max_tokens=600, json_mode=False)
            out["latency_s"] = round(time.time() - t0, 2)
            gen = (r1.get("usage") or {}).get("output") or 0
            out["decode_tps"] = round(gen / max(out["latency_s"], 0.01), 1) if gen else None
            out["sample"] = r1["text"][:400]
            ctx.progress(0.6, "checking tool calls")
            r2 = llm.complete(prof, prov, TOOL_PROMPT, max_tokens=2048, json_mode=False, tools=TOOLS)
            out["tool_call_ok"], out["tool_call_detail"] = tool_check(r2)
            out["cost_usd"] = round((r1.get("cost_usd") or 0) + (r2.get("cost_usd") or 0), 6)
            out["ok"] = out["tool_call_ok"]
    except Exception as e:  # noqa: BLE001 - the error is the test result
        out["error"] = f"{type(e).__name__}: {e}"[:800]
        ctx.log(out["error"])
    with db.Session() as s:
        p = s.get(db.Profile, pid)
        p.smoke = out
        s.commit()
    events.publish("profiles", "update", {"id": pid, "smoke": out})
    ctx.result = out
