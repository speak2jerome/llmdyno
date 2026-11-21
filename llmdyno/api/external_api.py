"""External benchmarks and references: SWE-bench and Aider polyglot imports, the official SWE-bench harness, SWE-bench
predictions export, portable harness runtimes and Artificial Analysis reference numbers."""
import json
import re

from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import Response

from .. import config, db, jobs, secrets
from ..benchmarks import artificial_analysis as aa
from ..benchmarks import polyglot, swebench
from ..benchmarks import registry as benches
from ..harnesses import catalog, images, runtime

router = APIRouter()


# ------------------------------------------------------------------ catalog of importable benchmarks
def _count(prefix):
    return sum(1 for b in benches.all_benchmarks() if b["id"].startswith(prefix) and not b["builtin"])


@router.get("/imports")
def import_catalog():
    sw = swebench.harness_status()
    poly = images.image_exists(polyglot.IMAGE)
    return {
        "swebench": {"datasets": [{"id": k, "name": v["name"], "size": v["size"], "about": v["about"], "hf": v["hf"]}
                                  for k, v in swebench.DATASETS.items()],
                     "imported": _count("swe_"), "harness": sw, "homepage": swebench.HOMEPAGE,
                     "harness_version": (config.get("swebench") or {}).get("harness_version")},
        "polyglot": {"languages": polyglot.LANGS, "imported": _count("pg_"), "image": polyglot.IMAGE,
                     "image_info": poly, "context_ready": polyglot.context_ready(), "homepage": polyglot.HOMEPAGE,
                     "repo": f"https://github.com/{polyglot.REPO}"},
        "runtime_platform": runtime.host_platform(),
    }


@router.post("/imports/swebench")
def import_swebench(body: dict = Body(...)):
    key = body.get("dataset", "verified_mini")
    if key not in swebench.DATASETS:
        raise HTTPException(400, f"unknown dataset {key}")
    ids = [x for x in body.get("instance_ids") or [] if re.fullmatch(r"[\w.\-]+__[\w.\-]+-\d+", x)]
    limit = int(body.get("limit") or 0)
    if limit < 0 or limit > 2000:
        raise HTTPException(400, "limit must be 0-2000")
    name = swebench.DATASETS[key]["name"]
    return {"job_id": jobs.submit("import", f"Import {name}" + (f" (first {limit})" if limit else ""),
                                  swebench.import_job, {"dataset": key, "instance_ids": ids, "limit": limit},
                                  ref="swebench", group="import")}


@router.post("/imports/polyglot")
def import_polyglot(body: dict = Body(default={})):
    langs = [x for x in body.get("languages") or list(polyglot.LANGS) if x in polyglot.LANGS]
    if not langs:
        raise HTTPException(400, "choose at least one language")
    return {"job_id": jobs.submit("import", "Import Aider polyglot", polyglot.import_job, {"languages": langs},
                                  ref="polyglot", group="import")}


@router.post("/imports/swebench/harness")
def install_swebench_harness():
    v = (config.get("swebench") or {}).get("harness_version")
    return {"job_id": jobs.submit("install", f"Install SWE-bench harness {v}", swebench.install_harness, {"version": v},
                                  ref="swebench_harness")}


@router.post("/imports/polyglot/image")
def build_polyglot_image():
    if not polyglot.context_ready():
        raise HTTPException(409, "import the polyglot benchmark first")
    return {"job_id": jobs.submit("build", "Build polyglot toolchain image", polyglot.build_image, ref="polyglot_image")}


@router.delete("/imports/{kind}")
def remove_imported(kind: str):
    """Delete every imported benchmark of one kind (the dataset can be imported again at any time)."""
    prefix = {"swebench": "swe_", "polyglot": "pg_"}.get(kind)
    if not prefix:
        raise HTTPException(404, "unknown import")
    n = 0
    for b in benches.all_benchmarks():
        if b["id"].startswith(prefix) and not b["builtin"]:
            benches.delete_custom(b["id"])
            n += 1
    with db.Session() as s:
        s.query(db.Suite).filter(db.Suite.id.like(f"suite_{kind}%")).delete(synchronize_session=False)
        s.commit()
    return {"removed": n}


# ------------------------------------------------------------------ SWE-bench predictions
@router.get("/plans/{pid}/swebench-predictions")
def swebench_predictions(pid: str):
    with db.Session() as s:
        runs = [db.row(r) for r in s.query(db.Run).filter(db.Run.plan_id == pid, db.Run.status == "done").all()]
        profs = {p.id: p.name for p in s.query(db.Profile).all()}
    runs = [r for r in runs if r["benchmark_id"].startswith("swe_")]
    if not runs:
        raise HTTPException(404, "this plan has no finished SWE-bench runs")
    for r in runs:
        r["label"] = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{profs.get(r['profile_id'], r['profile_id'])}__{r['harness_id']}")
    lines = swebench.predictions(runs)
    body = "".join(json.dumps(x) + "\n" for x in lines)
    return Response(body, media_type="application/x-ndjson",
                    headers={"Content-Disposition": f'attachment; filename="{pid}-swebench-predictions.jsonl"'})


# ------------------------------------------------------------------ harness runtimes
@router.get("/harnesses/{hid}/runtime")
def harness_runtime(hid: str, platform: str = ""):
    h = catalog.get(hid, images.custom_manifests())
    pf = platform if platform in runtime.PLATFORM_ARCH else runtime.host_platform()
    return {**runtime.status(h, pf), "dockerfile": runtime.dockerfile(h)}


@router.post("/harnesses/{hid}/runtime")
def build_harness_runtime(hid: str, body: dict = Body(default={})):
    h = catalog.get(hid, images.custom_manifests())
    pf = body.get("platform") if body.get("platform") in runtime.PLATFORM_ARCH else runtime.host_platform()

    def job(ctx):
        ctx.result = runtime.ensure(ctx, h, pf, ctx.log)
    return {"job_id": jobs.submit("build", f"Build {h.name} runtime ({pf})", job, {"harness_id": hid, "platform": pf},
                                  ref=f"rt_{hid}")}


# ------------------------------------------------------------------ Artificial Analysis
@router.get("/references/aa")
def aa_reference():
    from .results_api import _labels
    profs = _labels()[0]
    ref = aa.reference(profs)
    return {**aa.status(), "matches": {pid: {"score": m["score"], "manual": m["manual"], "model": m["model"]}
                                       for pid, m in ref.items()},
            "model_list": [{k: m.get(k) for k in ("slug", "name", "creator")} for m in aa.load_cache().get("models") or []]}


@router.post("/references/aa/refresh")
def aa_refresh(body: dict = Body(default={})):
    try:
        c = aa.refresh(force=bool(body.get("force")))
    except PermissionError as e:
        raise HTTPException(400, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(429, str(e)) from e
    except Exception as e:  # noqa: BLE001 - network and API errors go back to the user as text
        raise HTTPException(502, f"Artificial Analysis request failed: {e}") from e
    return {"models": len(c.get("models") or []), "fetched_at": c.get("fetched_at")}


@router.put("/settings/aa-key")
def set_aa_key(body: dict = Body(...)):
    key = (body.get("key") or "").strip()
    if not key:
        raise HTTPException(400, "the key is empty")
    secrets.set(aa.SECRET, key)
    return aa.status()


@router.delete("/settings/aa-key")
def delete_aa_key():
    secrets.delete(aa.SECRET)
    return aa.status()


@router.put("/references/aa/override")
def aa_override(body: dict = Body(...)):
    pid = body.get("profile_id")
    if not pid:
        raise HTTPException(400, "profile_id is required")
    ov = dict(aa.overrides())
    if body.get("slug"):
        ov[pid] = str(body["slug"])[:120]
    else:
        ov.pop(pid, None)
    cur = config.get("aa_reference") or {}
    config.save_settings({"aa_reference": {**cur, "overrides": ov}})
    return {"overrides": ov}
