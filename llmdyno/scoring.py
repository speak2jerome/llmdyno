"""Scores: per-run components, configurable weights, and per-configuration aggregates with iteration statistics.

final   = w_c·correctness + w_i·instruction following + w_q·quality + w_e·efficiency
quality = w_s·static hygiene + w_p·robustness probes + w_r·blind review (re-weighted over the parts that exist)
Size-neutral: static metrics are per line or per function; raw size is reported, never scored."""
import math
import statistics

TESTS_EXPECTED_MIN = 1


def clamp(x):
    return max(0.0, min(1.0, x))


def lin(v, good, bad):
    if v is None:
        return None
    return clamp((v - bad) / (good - bad))


def weighted(parts):
    parts = [(v, w) for v, w in parts if v is not None and w]
    tw = sum(w for _, w in parts)
    return sum(v * w for v, w in parts) / tw if tw else None


def static_score(s):
    """0-1 hygiene score from the analyzer summary (same formula as the round-1 report)."""
    if not s or "bandit" not in s:
        return None, {}
    py = (s.get("sloc") or {}).get("python", 0) + (s.get("sloc") or {}).get("python_tests", 0)
    dead_per_100 = 100 * (s.get("dead_code_findings") or 0) / max(py, 1)
    b = s.get("bandit") or {}
    sec = 1 - min(1, ((b.get("HIGH") or 0) + 0.5 * (b.get("MEDIUM") or 0)) / 2)
    tests = None
    if s.get("own_test_functions") is not None:
        passed = 1.0 if s.get("own_tests_pass") else 0.0
        tests = 0.5 * passed + 0.5 * (s.get("own_test_coverage") or 0.0) if s.get("own_test_functions") else 0.0
    cx = weighted([(lin(s.get("cc_avg"), 3, 10), 1), (1 - min(1, (s.get("cc_over_10_share") or 0) * 4), 1)])
    comps = {"lint": lin(s.get("ruff_per_100_sloc"), 0, 8), "complexity": cx,
             "function_size": 1 - min(1, (s.get("long_funcs_share") or 0) * 3), "nesting": lin(s.get("max_nesting"), 3, 7),
             "duplication": 1 - min(1, (s.get("duplication") or 0) * 5), "dead_code": 1 - min(1, dead_per_100 / 3),
             "security": sec, "typing": s.get("type_hint_coverage"), "docs": s.get("docstring_coverage"), "own_tests": tests}
    w = {"lint": .15, "complexity": .15, "function_size": .10, "nesting": .05, "duplication": .10, "dead_code": .05,
         "security": .15, "typing": .05, "docs": .05, "own_tests": .15}
    return weighted([(comps[k], w[k]) for k in comps]), comps


def run_components(run, reviews, quality_weights):
    """Per-run 0-1 components (efficiency is filled in later, relative to the benchmark)."""
    q = run.get("quality_raw") or (run.get("quality") if isinstance(run.get("quality"), dict) else None) or {}
    st, comps = static_score(q.get("static"))
    probes = (q.get("probes") or {}).get("rate")
    judges = {rv["judge_id"]: rv["overall"] / 10 for rv in reviews if isinstance(rv.get("overall"), (int, float))}
    review = statistics.mean(judges.values()) if judges else None
    qw = quality_weights
    quality = weighted([(st, qw.get("static", 35)), (probes, qw.get("probes", 30)), (review, qw.get("review", 35))])
    return {"static": st, "static_components": comps, "probes": probes, "review": review, "reviews_by_judge": judges,
            "quality": quality}


def mean_ci(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None, None, None
    m = statistics.mean(vals)
    if len(vals) < 2:
        return m, None, None
    sd = statistics.stdev(vals)
    t = {2: 12.71, 3: 4.30, 4: 3.18, 5: 2.78, 6: 2.57, 7: 2.45, 8: 2.36, 9: 2.31, 10: 2.26}.get(len(vals), 1.96)
    return m, sd, t * sd / math.sqrt(len(vals))


def compute(runs, reviews, weights, quality_weights, efficiency_ref="local", pass_threshold=0.8):
    """runs: plain dicts (done runs, with profile/harness info attached); reviews: list of review dicts.

    Returns {"runs": [...], "configs": [...], "cells": [...]} where a config is one profile × harness."""
    by_run = {}
    for rv in reviews:
        by_run.setdefault(rv["run_id"], []).append(rv)
    rows = []
    for r in runs:
        c = run_components(r, by_run.get(r["id"], []), quality_weights)
        rows.append({**r, **c})
    # efficiency: wall time vs the fastest run on the same benchmark that reached the pass threshold
    for bid in {r["benchmark_id"] for r in rows}:
        br = [r for r in rows if r["benchmark_id"] == bid and r.get("wall_s")]
        ref_pool = [r for r in br if r["kind"] == "local"] if efficiency_ref == "local" else br
        ref_pool = ref_pool or br
        good = [r["wall_s"] for r in ref_pool if (r.get("correctness") or 0) >= pass_threshold] or [r["wall_s"] for r in ref_pool]
        best = min(good) if good else None
        for r in br:
            r["efficiency"] = clamp(1 - math.log2(r["wall_s"] / best) / 4) if best else None
    w = weights
    for r in rows:
        r.setdefault("efficiency", None)
        r["final"] = weighted([(r.get("correctness"), w.get("correctness", 50)),
                               (r.get("instruction_following"), w.get("instruction_following", 15)),
                               (r.get("quality"), w.get("quality", 25)), (r.get("efficiency"), w.get("efficiency", 10))])
        r["passed"] = (r.get("correctness") or 0) >= pass_threshold
    # cells: config × benchmark, aggregated over iterations
    cells = {}
    for r in rows:
        cells.setdefault((r["profile_id"], r["harness_id"], r["benchmark_id"]), []).append(r)
    cell_rows = []
    keys = ("final", "correctness", "instruction_following", "quality", "static", "probes", "review", "efficiency",
            "wall_s", "cost_usd", "generated_tokens", "total_prompt_tokens", "decode_tps", "peak_context_tokens",
            "gpu_energy_wh", "sloc_total")
    for (pid, hid, bid), rs in cells.items():
        d = {"profile_id": pid, "harness_id": hid, "benchmark_id": bid, "n": len(rs),
             "pass_any": any(x["passed"] for x in rs), "pass_all": all(x["passed"] for x in rs),
             "pass_rate": sum(x["passed"] for x in rs) / len(rs)}
        for k in keys:
            m, sd, ci = mean_ci([x.get(k) for x in rs])
            d[k], d[f"{k}_sd"], d[f"{k}_ci"] = m, sd, ci
        cell_rows.append(d)
    configs = {}
    for c in cell_rows:
        configs.setdefault((c["profile_id"], c["harness_id"]), []).append(c)
    cfg_rows = []
    for (pid, hid), cs in configs.items():
        rs = [r for r in rows if r["profile_id"] == pid and r["harness_id"] == hid]
        d = {"profile_id": pid, "harness_id": hid, "benchmarks": len(cs), "runs": len(rs),
             "iterations": max(c["n"] for c in cs)}
        for k in ("final", "correctness", "instruction_following", "quality", "static", "probes", "review", "efficiency",
                  "decode_tps", "prefill_tps", "cache_hit_ratio"):
            vals = [c[k] for c in cs if c.get(k) is not None] if k in keys else [r.get(k) for r in rs if r.get(k) is not None]
            d[k] = statistics.mean(vals) if vals else None
        for k in ("wall_s", "cost_usd", "generated_tokens", "total_prompt_tokens", "gpu_energy_wh", "sloc_total"):
            d[k + "_total"] = sum((r.get(k) or 0) for r in rs)
        sds = [c["final_sd"] for c in cs if c.get("final_sd") is not None]
        d["consistency"] = clamp(1 - statistics.mean(sds) * 4) if sds else None      # sd of 0.25 -> 0
        d["final_sd"] = statistics.mean(sds) if sds else None
        _, _, ci = mean_ci([r["final"] for r in rs])
        d["final_ci"] = ci
        d["pass_at_k"] = sum(c["pass_any"] for c in cs) / len(cs)
        d["pass_all_k"] = sum(c["pass_all"] for c in cs) / len(cs)
        d["pass_rate"] = sum(r["passed"] for r in rs) / len(rs)
        d["spill_runs"] = sum(1 for r in rs if r.get("spill_detected"))
        d["failed_runs"] = 0
        d["peak_vram_mib"] = max((r.get("gpu_peak_vram_mib") or 0) for r in rs) or None
        d["peak_context_tokens"] = max((r.get("peak_context_tokens") or 0) for r in rs) or None
        cost = d["cost_usd_total"]
        d["score_per_dollar"] = (d["final"] * 100 / cost) if cost and d["final"] is not None else None
        d["points"] = {"correctness": (d["correctness"] or 0) * weights.get("correctness", 50),
                       "instruction_following": (d["instruction_following"] or 0) * weights.get("instruction_following", 15),
                       "quality": (d["quality"] or 0) * weights.get("quality", 25),
                       "efficiency": (d["efficiency"] or 0) * weights.get("efficiency", 10)}
        tw = sum(weights.values()) or 1
        d["points"] = {k: round(v * 100 / tw, 2) for k, v in d["points"].items()}
        cfg_rows.append(d)
    cfg_rows.sort(key=lambda d: -(d["final"] or 0))
    for i, d in enumerate(cfg_rows, 1):
        d["rank"] = i
    return {"runs": rows, "cells": cell_rows, "configs": cfg_rows}


def agreement(reviews, runs):
    """Pairwise judge agreement and self-preference (a judge rating its own model family higher than others do)."""
    by_run = {}
    for rv in reviews:
        if isinstance(rv.get("overall"), (int, float)):
            by_run.setdefault(rv["run_id"], {})[rv["judge_id"]] = rv
    judges = sorted({rv["judge_id"] for rv in reviews})
    names = {rv["judge_id"]: rv.get("judge_name") for rv in reviews}
    run_info = {r["id"]: r for r in runs}
    pairs = []
    for i, a in enumerate(judges):
        for b in judges[i + 1:]:
            xs = [(v[a]["overall"], v[b]["overall"]) for v in by_run.values() if a in v and b in v]
            if len(xs) < 3:
                continue
            x, y = zip(*xs)
            try:
                r = statistics.correlation(x, y)
            except statistics.StatisticsError:
                r = None
            pairs.append({"a": a, "b": b, "a_name": names[a], "b_name": names[b], "n": len(xs),
                          "pearson": round(r, 3) if r is not None else None,
                          "mean_abs_diff": round(statistics.mean(abs(p - q) for p, q in xs), 2),
                          "mean_diff": round(statistics.mean(p - q for p, q in xs), 2)})
    selfpref = []
    for j in judges:
        fam = (next((rv for rv in reviews if rv["judge_id"] == j), {}) or {}).get("judge_family")
        if not fam:
            continue
        own, other = [], []
        for rid, v in by_run.items():
            if j not in v or len(v) < 2:
                continue
            others = statistics.mean(x["overall"] for k, x in v.items() if k != j)
            delta = v[j]["overall"] - others
            (own if (run_info.get(rid) or {}).get("family") == fam else other).append(delta)
        if own and other:
            selfpref.append({"judge_id": j, "judge_name": names[j], "family": fam, "n_own": len(own),
                             "own_delta": round(statistics.mean(own), 2), "other_delta": round(statistics.mean(other), 2),
                             "self_preference": round(statistics.mean(own) - statistics.mean(other), 2)})
    return {"judges": [{"id": j, "name": names[j], "reviews": sum(1 for rv in reviews if rv["judge_id"] == j)} for j in judges],
            "pairs": pairs, "self_preference": selfpref}
