"""Build llmdyno/sample/round1.json from the round-1 study's run folders (developer tool).

Usage: python scripts/build_sample.py <bench dir with configs.json> <bench-runs dir>"""
import json
import sys
from pathlib import Path

bench, runs_dir = Path(sys.argv[1]), Path(sys.argv[2])
cfg = json.loads((bench / "configs.json").read_text())
FAMILY = {"qwen38": "qwen35", "qwen35": "qwen35", "qwen36": "qwen35moe", "gemma4": "gemma4", "gpt-oss": "gpt-oss",
          "cloud": "openai"}
KEEP = ("total_prompt_tokens", "prefill_tokens", "cached_prompt_tokens", "generated_tokens", "reasoning_tokens",
        "cache_hit_ratio", "peak_context_tokens", "context_utilization", "decode_tps", "prefill_tps", "model_time_s",
        "requests", "turns", "gpu_energy_wh", "gpu_peak_vram_mib", "tests_passed", "tests_total", "timed_out",
        "length_truncations", "http_errors", "tool_errors", "compactions")
profiles, runs, reviews = [], [], []
t_min, t_max = 9e18, 0
for c in sorted(cfg["configs"], key=lambda c: c["priority"]):
    pid = "prof_sample_" + c["id"].replace("-", "_")[:40]
    quant = c["quant"].replace(" (native)", "").replace(" (Google)", "").replace(" (experts partly in system RAM)", "")
    fam_name = c["family"].replace(" (cloud baseline)", "")
    name = f"{fam_name} {quant}".strip() if c.get("type") != "cloud" else fam_name
    if c.get("breaks_vram_rule"):
        name += " (CPU offload)"
    kind = "cloud" if c.get("type") == "cloud" else "local"
    params = {"ctx": c["ctx"], "cache_k": c.get("cache_k"), "cache_v": c.get("cache_v")} if kind == "local" else \
        {"ctx": c["ctx"], "reasoning_effort": c.get("thinking")}
    profiles.append({"id": pid, "name": name, "kind": kind, "params": params, "remote_model": c.get("pi_model", ""),
                     "pricing": {"input": c["price_per_mtok"]["input"], "cached": c["price_per_mtok"]["cached"],
                                 "output": c["price_per_mtok"]["output"]} if kind == "cloud" else {}})
    family = next((v for k, v in FAMILY.items() if c["id"].startswith(k)), "other")
    for task in sorted(p.name for p in (runs_dir / c["id"]).iterdir() if (p / "result.json").exists()) if (runs_dir / c["id"]).exists() else []:
        d = runs_dir / c["id"] / task
        res = json.loads((d / "result.json").read_text())
        q = json.loads((d / "quality.json").read_text()) if (d / "quality.json").exists() else {}
        st = dict(q.get("static") or {})
        st.pop("files", None)
        rid = f"run_sample_{c['id'][:24]}_{task[:3]}".replace("-", "_")
        ts = __import__("datetime").datetime.fromisoformat(res["timestamp"]).timestamp()
        t_min, t_max = min(t_min, ts - res["wall_s"]), max(t_max, ts)
        m = {k: res.get(k) for k in KEEP}
        m["n_tool_calls"] = res.get("tool_calls")
        runs.append({"id": rid, "profile_id": pid, "benchmark_id": task, "correctness": res["correctness"],
                     "instruction_following": res["instruction_following"], "wall_s": res["wall_s"],
                     "cost_usd": res.get("cost_usd"), "metrics": m, "quality": {"static": st, "probes": q.get("probes")},
                     "started_at": ts - res["wall_s"], "ended_at": ts, "family": family})
        for jname, jid, jfam, label in (("gpt-6-luna", "judge_sample_luna", "openai", "GPT-6 Luna (judge)"),
                                        ("claude", "judge_sample_claude", "anthropic", "Claude (judge)")):
            jf = d / f"judge-{jname}.json"
            if jf.exists():
                j = json.loads(jf.read_text(encoding="utf-8"))
                reviews.append({"id": f"rev_{rid}_{jname[:6]}", "run_id": rid, "judge_id": jid, "judge_name": label,
                                "judge_family": jfam, "overall": j.get("overall"), "scores": j.get("scores") or {},
                                "summary": j.get("summary", ""), "issues": (j.get("top_issues") or [])[:8],
                                "extras": (j.get("extras_beyond_spec") or [])[:8]})
out = {"plan": {"name": "Sample: round 1 on an RTX 5080 (15 profiles × 5 tasks, Pi)",
                "benchmark_ids": ["t1_flask_site", "t2_fastapi_worker_ts", "t3_long_iterative", "t4_data_ml", "t5_bugfix_semver"],
                "created_at": t_min, "ended_at": t_max},
       "profiles": profiles, "runs": runs, "reviews": reviews}
Path("llmdyno/sample/round1.json").write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
print(len(profiles), "profiles", len(runs), "runs", len(reviews), "reviews")
