"""Run metrics from the proxy log, the transcript and GPU sampling."""
import json
import re
import shutil
import statistics
import subprocess
import threading
import time
from pathlib import Path

from ..system import specs as sysspecs

NOWIN = subprocess.CREATE_NO_WINDOW if sysspecs.IS_WIN else 0
INSTALL_RE = re.compile(r"\b(pip3?|uv)\s+(install|add)|\bnpm\s+(i|install|add)\b|\b(apt|apt-get|yarn|pnpm|conda)\s+(install|add)\b")


def read_jsonl(path):
    out = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except ValueError:
                        pass
    except OSError:
        pass
    return out


def proxy_metrics(path, t0=None, t1=None):
    recs = [r for r in read_jsonl(path) if "usage_norm" in r or "timings" in r or r.get("budget_blocked")]
    if t0 is not None:
        recs = [r for r in recs if t0 - 1 <= r.get("ts", 0) <= (t1 or 9e18) + 1]
    out = {"requests": len(recs), "http_errors": sum(1 for r in recs if (r.get("status") or 200) >= 400),
           "budget_blocked": sum(1 for r in recs if r.get("budget_blocked")),
           "length_truncations": sum(1 for r in recs if r.get("finish_reason") in ("length", "incomplete", "max_tokens")),
           "reasoning_chars": sum(r.get("reasoning_chars", 0) for r in recs),
           "content_chars": sum(r.get("content_chars", 0) for r in recs),
           "model_time_s": round(sum(r.get("wall_s", 0) or 0 for r in recs), 1),
           "cost_usd": round(sum(r.get("cost_usd", 0) or 0 for r in recs), 6),
           "tool_calls_requested": sum(r.get("n_tool_calls", 0) or 0 for r in recs)}
    ttfts = [r["ttft_s"] for r in recs if r.get("ttft_s")]
    out["ttft_median_s"] = round(statistics.median(ttfts), 2) if ttfts else None
    tim = [r["timings"] for r in recs if r.get("timings")]
    us = [r["usage_norm"] for r in recs if r.get("usage_norm")]
    if tim:   # llama-server reports exact prefill/decode timings
        pn = sum(t.get("prompt_n", 0) for t in tim)
        cn = sum(t.get("cache_n", 0) for t in tim)
        gn = sum(t.get("predicted_n", 0) for t in tim)
        pms = sum(t.get("prompt_ms", 0) for t in tim)
        gms = sum(t.get("predicted_ms", 0) for t in tim)
        out.update({"prefill_tokens": pn, "cached_prompt_tokens": cn, "generated_tokens": gn, "total_prompt_tokens": pn + cn,
                    "cache_hit_ratio": round(cn / (pn + cn), 4) if pn + cn else None,
                    "prefill_tps": round(pn / pms * 1000, 1) if pms else None,
                    "decode_tps": round(gn / gms * 1000, 1) if gms else None,
                    "peak_context_tokens": max(t.get("prompt_n", 0) + t.get("cache_n", 0) + t.get("predicted_n", 0) for t in tim)})
    elif us:
        inp = sum(u.get("input") or 0 for u in us)
        cached = sum(u.get("cached") or 0 for u in us)
        gen = sum(u.get("output") or 0 for u in us)
        out.update({"total_prompt_tokens": inp, "cached_prompt_tokens": cached, "prefill_tokens": inp - cached,
                    "cache_write_tokens": sum(u.get("cache_write") or 0 for u in us), "generated_tokens": gen,
                    "reasoning_tokens": sum(u.get("reasoning") or 0 for u in us),
                    "cache_hit_ratio": round(cached / inp, 4) if inp else None,
                    "peak_context_tokens": max((u.get("input") or 0) + (u.get("output") or 0) for u in us)})
        gen_time = sum(max((r.get("wall_s") or 0) - (r.get("ttft_s") or 0), 0.001) for r in recs if r.get("usage_norm"))
        out["decode_tps"] = round(gen / gen_time, 1) if gen_time and gen else None
    return out


def transcript_facts(path):
    """Harness-neutral facts from the proxy transcript: tool usage, install attempts, final message, turns."""
    tools, installs, final_text, turns, errors = {}, [], "", 0, []
    tool_errors = 0
    for ev in read_jsonl(path):
        if ev.get("ev") == "response":
            turns += 1
            text = "".join(b.get("text", "") for b in ev.get("blocks") or [] if b.get("type") == "text").strip()
            if text:
                final_text = text
            for b in ev.get("blocks") or []:
                if b.get("type") == "tool_call":
                    name = b.get("name") or "?"
                    tools[name] = tools.get(name, 0) + 1
                    if INSTALL_RE.search(b.get("args") or ""):
                        installs.append((b.get("args") or "")[:200])
            if ev.get("error"):
                errors.append(ev["error"][:300])
        elif ev.get("ev") == "request":
            for m in ev.get("new") or []:
                for b in m.get("blocks") or []:
                    if b.get("type") == "tool_result" and (b.get("is_error") or re.match(
                            r"^(error|traceback|command failed)", (b.get("text") or "")[:40], re.I)):
                        tool_errors += 1
        elif ev.get("ev") == "error":
            errors.append(ev.get("text", "")[:300])
    return {"tool_calls": tools, "n_tool_calls": sum(tools.values()), "install_attempts": installs,
            "final_text": final_text[:4000], "turns": turns, "errors": errors[:8], "tool_errors": tool_errors}


class GpuSampler:
    """Samples VRAM, power, utilisation and (on Windows) shared GPU memory every second during a local run."""

    def __init__(self, path, on_sample=None):
        self.path = Path(path)
        self.stop_ev = threading.Event()
        self.on_sample = on_sample
        self.thread = None
        self.baseline_shared = None

    def start(self):
        if not shutil.which("nvidia-smi"):
            return self
        self.thread = threading.Thread(target=self._loop, daemon=True, name="gpu-sampler")
        self.thread.start()
        return self

    def _loop(self):
        shared_every, n = 5, 0
        shared = None
        with open(self.path, "a", encoding="utf-8") as f:
            while not self.stop_ev.is_set():
                try:
                    out = subprocess.run(["nvidia-smi", "--query-gpu=power.draw,memory.used,memory.total,utilization.gpu,"
                                          "temperature.gpu", "--format=csv,noheader,nounits"], capture_output=True,
                                         text=True, timeout=10, creationflags=NOWIN).stdout.strip().splitlines()[0]
                    pw, used, total, util, temp = [float(x) if re.fullmatch(r"[\d.]+", x.strip()) else 0.0
                                                   for x in out.split(",")[:5]]
                    if sysspecs.IS_WIN and n % shared_every == 0:
                        adapters = sysspecs.shared_gpu_usage_mib() or {}
                        shared = max((a.get("shared", 0) for a in adapters.values()), default=0)
                        if self.baseline_shared is None:
                            self.baseline_shared = shared
                    rec = {"ts": time.time(), "power_w": pw, "vram_mib": used, "vram_total_mib": total, "util_pct": util,
                           "temp_c": temp, "shared_mib": shared}
                    f.write(json.dumps(rec) + "\n")
                    f.flush()
                    if self.on_sample:
                        self.on_sample(rec)
                except (OSError, subprocess.TimeoutExpired, IndexError, ValueError):
                    pass
                n += 1
                self.stop_ev.wait(1.0)

    def stop(self):
        self.stop_ev.set()
        if self.thread:
            self.thread.join(10)


def gpu_metrics(path, t0, t1, baseline_shared=None):
    rows = [r for r in read_jsonl(path) if t0 <= r.get("ts", 0) <= t1]
    if len(rows) < 2:
        return {}
    energy_ws = sum((b["ts"] - a["ts"]) * (a["power_w"] + b["power_w"]) / 2 for a, b in zip(rows, rows[1:]))
    shared = [r["shared_mib"] for r in rows if r.get("shared_mib") is not None]
    peak = max(r["vram_mib"] for r in rows)
    total = rows[0].get("vram_total_mib") or 0
    out = {"gpu_energy_wh": round(energy_ws / 3600, 3), "gpu_avg_power_w": round(statistics.mean(r["power_w"] for r in rows), 1),
           "gpu_peak_vram_mib": peak, "gpu_vram_total_mib": total,
           "gpu_avg_util_pct": round(statistics.mean(r["util_pct"] for r in rows), 1),
           "gpu_max_temp_c": max(r["temp_c"] for r in rows)}
    if shared:
        base = baseline_shared if baseline_shared is not None else min(shared)
        out["gpu_shared_peak_mib"] = max(shared)
        out["gpu_spill_mib"] = max(0, max(shared) - base)
        out["spill_detected"] = out["gpu_spill_mib"] > 256 or (total and peak > total - 64)
    return out
