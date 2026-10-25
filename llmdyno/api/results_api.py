"""Results: scored runs and configurations for the dashboard, judge agreement, exports and the sample dataset."""
import csv
import io
import json
import statistics
import time
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import Response

from .. import __version__, config, db, events, scoring
from ..benchmarks import registry as benches
from ..harnesses import catalog, images
from ..judge import judge as judge_mod

router = APIRouter()
SAMPLE = Path(__file__).resolve().parent.parent / "sample" / "round1.json"
SAMPLE_JUDGES = {"judge_sample_luna": "openai", "judge_sample_claude": "anthropic"}
FLAT = ("total_prompt_tokens", "prefill_tokens", "cached_prompt_tokens", "generated_tokens", "reasoning_tokens",
        "cache_hit_ratio", "peak_context_tokens", "context_utilization", "decode_tps", "prefill_tps", "ttft_median_s",
        "model_time_s", "requests", "turns", "n_tool_calls", "tool_errors", "gpu_energy_wh", "gpu_peak_vram_mib",
        "gpu_vram_total_mib", "spill_detected", "gpu_spill_mib", "tests_passed", "tests_total", "timed_out",
        "length_truncations", "http_errors", "budget_blocked")


def _labels():
    with db.Session() as s:
        profs = {}
        for p in s.query(db.Profile).all():
            m = s.get(db.Model, p.model_id) if p.model_id else None
            v = s.get(db.Provider, p.provider_id) if p.provider_id else None
            profs[p.id] = {"name": p.name, "kind": p.kind, "quant": m.quant if m else "", "model": m.name if m else p.remote_model,
                           "vendor": v.vendor if v else None, "provider": v.name if v else None,
                           "arch": (m.meta or {}).get("arch") if m else None, "ctx": (p.params or {}).get("ctx"),
                           "size_bytes": m.size_bytes if m else None}
    harn = {h.id: h.name for h in catalog.BUILTIN}
    for m in images.custom_manifests():
        harn[m["id"]] = m["name"]
    bl = {b["id"]: {"title": b["title"], "category": b["category"], "difficulty": b["difficulty"]} for b in benches.all_benchmarks()}
    return profs, harn, bl


def collect(plan_ids=None, include_sample=True, benchmark_ids=None):
    with db.Session() as s:
        q = s.query(db.Run).filter(db.Run.status == "done")
        if benchmark_ids:
            q = q.filter(db.Run.benchmark_id.in_(benchmark_ids))
        if plan_ids:
            q = q.filter(db.Run.plan_id.in_(plan_ids))
        elif not include_sample:
            sample_ids = [p.id for p in s.query(db.Plan).filter(db.Plan.sample.is_(True))]
            q = q.filter(db.Run.plan_id.notin_(sample_ids))
        runs = [db.row(r) for r in q.all()]
        ids = [r["id"] for r in runs]
        reviews = [db.row(r) for r in s.query(db.Review).filter(db.Review.run_id.in_(ids)).all()] if ids else []
    profs, harn, bl = _labels()
    fam = judge_mod.judge_families()
    flat = []
    for r in runs:
        m = r.get("metrics") or {}
        snap = (r.get("snapshot") or {}).get("profile") or {}
        p = profs.get(r["profile_id"]) or {"name": snap.get("name", r["profile_id"]), "kind": snap.get("kind", "local")}
        d = {"id": r["id"], "plan_id": r["plan_id"], "profile_id": r["profile_id"], "harness_id": r["harness_id"],
             "benchmark_id": r["benchmark_id"], "iteration": r["iteration"], "kind": p.get("kind", "local"),
             "correctness": r["correctness"], "instruction_following": r["instruction_following"], "wall_s": r["wall_s"],
             "cost_usd": r["cost_usd"], "quality_raw": r.get("quality") or {}, "started_at": r["started_at"],
             "family": (r.get("snapshot") or {}).get("family") or fam.get(r["profile_id"])}
        for k in FLAT:
            d[k] = m.get(k)
        st = (d["quality_raw"].get("static") or {})
        d["sloc_total"] = st.get("sloc_total")
        d["lint_per_100"] = st.get("ruff_per_100_sloc")
        d["own_tests"] = st.get("own_test_functions")
        flat.append(d)
    for rv in reviews:
        rv["judge_family"] = fam.get(rv["judge_id"]) or SAMPLE_JUDGES.get(rv["judge_id"])
    return flat, reviews, profs, harn, bl


@router.get("/results")
def results(plan_ids: str = "", weights: str = "", quality_weights: str = "", pass_threshold: float = 0.8,
            efficiency_ref: str = "local", include_sample: bool = True, benchmark_ids: str = ""):
    ids = [x for x in plan_ids.split(",") if x]
    w = json.loads(weights) if weights else config.get("weights")
    qw = json.loads(quality_weights) if quality_weights else config.get("quality_weights")
    bids = [x for x in benchmark_ids.split(",") if x]
    flat, reviews, profs, harn, bl = collect(ids, include_sample, bids)
    out = scoring.compute(flat, reviews, w, qw, efficiency_ref=efficiency_ref, pass_threshold=pass_threshold)
    for r in out["runs"]:
        r.pop("quality_raw", None)
        r.pop("static_components", None)
    out["agreement"] = scoring.agreement(reviews, flat)
    dims = {}
    for rv in reviews:
        run = next((x for x in flat if x["id"] == rv["run_id"]), None)
        if not run:
            continue
        key = (run["profile_id"], run["harness_id"])
        for k, v in (rv.get("scores") or {}).items():
            if isinstance(v, (int, float)):
                dims.setdefault(key, {}).setdefault(k, []).append(v)
    out["rubric"] = [{"profile_id": k[0], "harness_id": k[1], **{d: round(statistics.mean(v), 2) for d, v in ds.items()}}
                     for k, ds in dims.items()]
    out["labels"] = {"profiles": profs, "harnesses": harn, "benchmarks": bl}
    with db.Session() as s:
        out["plans"] = [{"id": p.id, "name": p.name, "sample": p.sample, "status": p.status, "created_at": p.created_at}
                        for p in s.query(db.Plan).order_by(db.Plan.created_at.desc()).all()]
    if bids:
        all_flat = collect(ids, include_sample)[0]
        out["benchmarks_available"] = sorted({r["benchmark_id"] for r in all_flat})
    else:
        out["benchmarks_available"] = sorted({r["benchmark_id"] for r in flat})
    out["weights"], out["quality_weights"], out["pass_threshold"] = w, qw, pass_threshold
    out["reviews"] = [{k: rv.get(k) for k in ("run_id", "judge_id", "judge_name", "overall", "summary", "issues", "extras")}
                      for rv in reviews]
    return out


@router.get("/results/export")
def export(plan_ids: str = "", level: str = "runs", fmt: str = "csv", weights: str = "", quality_weights: str = "",
           benchmark_ids: str = ""):
    data = results(plan_ids=plan_ids, weights=weights, quality_weights=quality_weights, benchmark_ids=benchmark_ids)
    profs, harn, bl = data["labels"]["profiles"], data["labels"]["harnesses"], data["labels"]["benchmarks"]
    rows = data["configs"] if level == "configs" else data["cells"] if level == "cells" else data["runs"]
    clean = []
    for r in rows:
        d = {"profile": (profs.get(r["profile_id"]) or {}).get("name", r["profile_id"]),
             "harness": harn.get(r["harness_id"], r["harness_id"])}
        if "benchmark_id" in r:
            d["benchmark"] = (bl.get(r["benchmark_id"]) or {}).get("title", r["benchmark_id"])
        for k, v in r.items():
            if isinstance(v, (dict, list)):
                if k == "points":
                    for pk, pv in v.items():
                        d[f"points_{pk}"] = pv
                continue
            d[k] = round(v, 5) if isinstance(v, float) else v
        clean.append(d)
    stamp = time.strftime("%Y%m%d-%H%M")
    name = f"llmdyno-{__version__}-{level}-{stamp}"       # the file name says which release computed the scores
    if fmt == "json":
        doc = {"llmdyno_version": __version__, "exported_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "level": level,
               "weights": data["weights"], "quality_weights": data["quality_weights"], "rows": clean}
        return Response(json.dumps(doc, indent=2, default=str), media_type="application/json",
                        headers={"Content-Disposition": f'attachment; filename="{name}.json"'})
    buf = io.StringIO()
    keys = []
    for r in clean:
        keys += [k for k in r if k not in keys]
    w = csv.DictWriter(buf, fieldnames=keys)
    w.writeheader()
    w.writerows(clean)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


# ------------------------------------------------------------------ sample dataset
@router.get("/sample")
def sample_status():
    with db.Session() as s:
        p = s.query(db.Plan).filter(db.Plan.sample.is_(True)).first()
    return {"available": SAMPLE.exists(), "loaded": bool(p), "plan_id": p.id if p else None}


@router.post("/sample")
def load_sample():
    if not SAMPLE.exists():
        raise HTTPException(404, "sample dataset is not bundled")
    data = json.loads(SAMPLE.read_text(encoding="utf-8"))
    with db.Session() as s:
        if s.query(db.Plan).filter(db.Plan.sample.is_(True)).first():
            raise HTTPException(409, "the sample is already loaded")
        pid = "plan_sample_round1"
        prof_ids = []
        for p in data["profiles"]:
            if not s.get(db.Profile, p["id"]):
                s.add(db.Profile(id=p["id"], name=p["name"], kind=p["kind"], remote_model=p.get("remote_model", ""),
                                 params=p.get("params") or {}, notes="Sample profile (round 1 results, RTX 5080)",
                                 tags=["sample"], pricing=p.get("pricing") or {}))
            prof_ids.append(p["id"])
        s.add(db.Plan(id=pid, name=data["plan"]["name"], profile_ids=prof_ids, harness_ids=["pi"],
                      benchmark_ids=data["plan"]["benchmark_ids"], iterations=1, options={}, status="done", sample=True,
                      created_at=data["plan"]["created_at"], started_at=data["plan"]["created_at"],
                      ended_at=data["plan"]["ended_at"]))
        for r in data["runs"]:
            s.add(db.Run(id=r["id"], plan_id=pid, profile_id=r["profile_id"], harness_id="pi", benchmark_id=r["benchmark_id"],
                         iteration=1, status="done", correctness=r["correctness"],
                         instruction_following=r["instruction_following"], wall_s=r["wall_s"], cost_usd=r["cost_usd"],
                         metrics=r["metrics"], quality=r["quality"], started_at=r["started_at"], ended_at=r["ended_at"],
                         snapshot={"profile": {"name": next(p["name"] for p in data["profiles"] if p["id"] == r["profile_id"]),
                                               "kind": next(p["kind"] for p in data["profiles"] if p["id"] == r["profile_id"])},
                                   "family": r.get("family"), "sample": True}))
        s.flush()                       # runs must exist before reviews reference them
        for rv in data["reviews"]:
            s.add(db.Review(id=rv["id"], run_id=rv["run_id"], judge_id=rv["judge_id"], judge_name=rv["judge_name"],
                            overall=rv["overall"], scores=rv["scores"], summary=rv["summary"], issues=rv["issues"],
                            extras=rv["extras"]))
        s.commit()
    events.publish("plans", "update", {"id": pid})
    return {"ok": True, "plan_id": pid, "runs": len(data["runs"]), "reviews": len(data["reviews"])}


@router.delete("/sample")
def unload_sample():
    with db.Session() as s:
        plans = s.query(db.Plan).filter(db.Plan.sample.is_(True)).all()
        for p in plans:
            ids = [r.id for r in s.query(db.Run).filter(db.Run.plan_id == p.id)]
            s.query(db.Review).filter(db.Review.run_id.in_(ids)).delete(synchronize_session=False)
            s.query(db.Run).filter(db.Run.plan_id == p.id).delete()
            s.delete(p)
        s.query(db.Profile).filter(db.Profile.id.like("prof_sample_%")).delete(synchronize_session=False)
        s.commit()
    return {"ok": True}


@router.post("/results/weights")
def save_weights(body: dict = Body(...)):
    patch = {}
    if "weights" in body:
        patch["weights"] = body["weights"]
    if "quality_weights" in body:
        patch["quality_weights"] = body["quality_weights"]
    return config.save_settings(patch)
