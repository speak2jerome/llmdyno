"""REST endpoints for setup, models, profiles, providers, harnesses, benchmarks, plans, runs and jobs."""
import json
import os
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse, Response

from .. import __version__, config, db, events, jobs, memory, profiles, secrets, smoke
from ..benchmarks import registry as benches
from ..benchmarks import validate as bvalidate
from ..harnesses import catalog, images
from ..hub import hf
from ..inference import llamacpp
from ..judge import judge as judge_mod
from ..providers import registry as providers
from ..runner import executor, metrics
from ..system import deps
from ..system import specs as sysspecs

router = APIRouter()
OS_NAME = "nt" if os.name == "nt" else "posix"


def _get(model, key):
    with db.Session() as s:
        obj = s.get(model, key)
        if obj is None:
            raise HTTPException(404, f"{model.__tablename__[:-1]} {key} not found")
        return db.row(obj)


# ================================================================== system & settings
@router.get("/system/specs")
def get_specs(refresh: bool = False):
    s = sysspecs.detect(force=refresh)
    return {**s, "shared_gpu_mib": sysspecs.shared_gpu_usage_mib() if refresh else None}


@router.get("/system/deps")
def get_deps(refresh: bool = False):
    return deps.check(force=refresh)


@router.post("/system/deps/{dep_id}/action")
def dep_action(dep_id: str, body: dict = Body(default={})):
    action = body.get("action")
    if action == "start_docker":
        deps.start_docker_desktop()
        return {"ok": True, "message": "Docker Desktop is starting; this takes about a minute."}
    if action == "install_docker":
        return {"job_id": jobs.submit("install", "Install Docker Desktop", deps.install_docker, ref="docker")}
    if action == "install_llama":
        variant = body.get("variant") or llamacpp.variants()[0]["id"]
        return {"job_id": jobs.submit("install", f"Install llama.cpp ({variant})", llamacpp.install, {"variant": variant},
                                      ref="llama_cpp")}
    if action == "use_existing_llama":
        return {"ok": True, "llama_cpp": llamacpp.use_existing(body.get("path", ""))}
    if action == "build_sandbox":
        return {"job_id": jobs.submit("build", "Build sandbox image", images.build_sandbox, ref="sandbox_image")}
    if action == "build_quality":
        return {"job_id": jobs.submit("build", "Build code-quality image", images.build_quality, ref="quality_image")}
    if action.startswith("build_harness_"):
        hid = action.removeprefix("build_harness_")
        return {"job_id": _build_harness(hid)}
    raise HTTPException(400, f"unknown action {action}")


@router.get("/settings")
def get_settings():
    s = config.load_settings()
    s["hf_token_set"] = secrets.has("hf_token")
    s["data_dir"] = str(config.DATA)
    return s


@router.patch("/settings")
def patch_settings(body: dict = Body(...)):
    allowed = {"models_dir", "runs_dir", "electricity_usd_per_kwh", "theme", "onboarded", "default_vram_margin_mib",
               "cloud_concurrency", "weights", "quality_weights", "llama_port"}
    bad = set(body) - allowed
    if bad:
        raise HTTPException(400, f"cannot change {', '.join(sorted(bad))}")
    for k in ("models_dir", "runs_dir"):
        if k in body:
            p = Path(body[k])
            if not p.is_absolute():
                raise HTTPException(400, f"{k} must be an absolute path")
            p.mkdir(parents=True, exist_ok=True)
    if "electricity_usd_per_kwh" in body and not 0 <= float(body["electricity_usd_per_kwh"]) <= 5:
        raise HTTPException(400, "electricity price must be between 0 and 5 USD/kWh")
    if "cloud_concurrency" in body and not 1 <= int(body["cloud_concurrency"]) <= 16:
        raise HTTPException(400, "cloud concurrency must be 1-16")
    return config.save_settings(body)


@router.put("/settings/hf-token")
def set_hf_token(body: dict = Body(...)):
    secrets.set("hf_token", body.get("token", ""))
    return {"hf_token_set": secrets.has("hf_token")}


@router.delete("/settings/hf-token")
def del_hf_token():
    secrets.delete("hf_token")
    return {"hf_token_set": False}


@router.post("/system/cleanup")
def cleanup_containers():
    return {"removed": sandbox_cleanup()}


def sandbox_cleanup():
    from ..runner import sandbox
    return sandbox.cleanup_stale()


@router.get("/system/gpu")
def system_gpu():
    return sysspecs.gpu_usage()


@router.get("/system/active")
def system_active():
    """What a panic stop would halt right now; shown in its confirmation dialog."""
    from .. import safety
    return safety.active()


@router.post("/system/panic")
def system_panic():
    from .. import safety
    return safety.panic()


# ================================================================== hub & models
@router.get("/hub/search")
def hub_search(q: str = "", sort: str = "downloads", limit: int = 30):
    if len(q.strip()) < 2:
        return []
    return hf.search(q.strip(), limit=min(limit, 60), sort=sort if sort in ("downloads", "likes", "lastModified") else "downloads")


@router.get("/hub/repo")
def hub_repo(repo: str):
    info = hf.repo_files(repo)
    s = sysspecs.detect()
    g = sysspecs.primary_gpu(s)
    for v in info["variants"]:
        v["fits_hint"] = None
        if g and not v["mmproj"]:
            # weights alone vs VRAM gives a first hint before the header is read
            v["fits_hint"] = "likely" if v["size_bytes"] < (g["vram_total_mib"] - 2500) * 2**20 else (
                "tight" if v["size_bytes"] < (g["vram_total_mib"] - 900) * 2**20 else "no")
    return info


@router.post("/hub/estimate")
def hub_estimate(body: dict = Body(...)):
    repo, vid = body["repo"], body["variant_id"]
    info = hf.repo_files(repo)
    v = next((x for x in info["variants"] if x["id"] == vid), None)
    if not v:
        raise HTTPException(404, "variant not found")
    meta = hf.remote_meta(repo, v)
    params = profiles.merge(profiles.default_local(meta), body.get("params") or {})
    chk = memory.check(meta, params, sysspecs.detect(), os_name=OS_NAME)
    return {"meta": _meta_public(meta), "params": params, "check": chk,
            "contexts": _context_table(meta, params)}


def _context_table(meta, params):
    """Projected GPU memory at common context sizes, for the fit chart."""
    out = []
    train = meta.get("ctx_train") or 262144
    sizes = sorted({c for c in (4096, 8192, 16384, 32768, 65536, 98304, 131072, 196608, 262144, 524288) if c <= train}
                   | {min(train, 1048576)})
    for c in sizes[-8:]:
        e = memory.estimate(meta, {**params, "ctx": c})
        out.append({"ctx": c, "gpu_total": e["gpu_total"], "kv": e["gpu"]["kv"]})
    return out


def _meta_public(meta):
    return {k: v for k, v in (meta or {}).items() if k not in ("layer_bytes", "expert_bytes", "swa_layers",
                                                                 "recurrent_layers", "n_head_kv")}


@router.get("/models")
def list_models():
    with db.Session() as s:
        return [hf.model_dict(m) for m in s.query(db.Model).order_by(db.Model.created_at.desc()).all()]


@router.post("/models/download")
def model_download(body: dict = Body(...)):
    repo, vid = body["repo"], body["variant_id"]
    info = hf.repo_files(repo)
    v = next((x for x in info["variants"] if x["id"] == vid), None)
    if not v:
        raise HTTPException(404, "variant not found")
    target = hf.local_dir_for(repo)
    need = v["size_bytes"]
    if need > hf.free_bytes(config.path("models_dir")) - 512 * 2**20:
        raise HTTPException(507, f"not enough disk space: {need / 2**30:.1f} GB needed, "
                                 f"{hf.free_bytes(config.path('models_dir')) / 2**30:.1f} GB free in {config.get('models_dir')}")
    with db.Session() as s:
        existing = [m for m in s.query(db.Model).filter(db.Model.repo == repo).all()
                    if m.files == [Path(f["path"]).name for f in v["files"]]]
        if existing and existing[0].status == "ready":
            raise HTTPException(409, "this model is already downloaded")
        if existing:
            mid = existing[0].id
        else:
            mid = db.new_id("mdl")
            name = Path(v["id"]).stem
            s.add(db.Model(id=mid, repo=repo, name=name, quant=v["quant"], files=[Path(f["path"]).name for f in v["files"]],
                           local_dir=str(target), size_bytes=need, status="queued", source="hf"))
            s.commit()
    job = jobs.submit("download", f"Download {repo} · {v['quant']}", hf.download, {"model_id": mid, "files": v["files"]},
                      ref=mid)
    return {"model_id": mid, "job_id": job}


@router.post("/models/{mid}/pause")
def model_pause(mid: str):
    with db.Session() as s:
        j = s.query(db.Job).filter(db.Job.ref == mid, db.Job.kind == "download", db.Job.status.in_(["queued", "running"])).first()
    if not j:
        raise HTTPException(409, "no active download for this model")
    jobs.cancel(j.id)
    return {"ok": True}


@router.post("/models/{mid}/resume")
def model_resume(mid: str):
    m = _get(db.Model, mid)
    if m["status"] == "ready":
        raise HTTPException(409, "already downloaded")
    info = hf.repo_files(m["repo"])
    v = next((x for x in info["variants"] if [Path(f["path"]).name for f in x["files"]] == m["files"]), None)
    if not v:
        raise HTTPException(404, "the variant is no longer in the repository")
    job = jobs.submit("download", f"Download {m['repo']} · {m['quant']}", hf.download, {"model_id": mid, "files": v["files"]},
                      ref=mid)
    return {"job_id": job}


@router.delete("/models/{mid}")
def model_delete(mid: str, delete_files: bool = False):
    m = _get(db.Model, mid)
    with db.Session() as s:
        active = s.query(db.Job).filter(db.Job.ref == mid, db.Job.status.in_(["queued", "running"])).first()
        if active:
            raise HTTPException(409, "pause or finish the download first")
        used = s.query(db.Profile).filter(db.Profile.model_id == mid).count()
    removed = []
    if delete_files and m["source"] == "hf":
        for f in m["files"]:
            for p in (Path(m["local_dir"]) / f, Path(m["local_dir"]) / (f + ".part")):
                if p.exists():
                    p.unlink()
                    removed.append(str(p))
    with db.Session() as s:
        s.query(db.Model).filter(db.Model.id == mid).delete()
        s.commit()
    events.publish("models", "deleted", {"id": mid})
    return {"ok": True, "removed_files": removed, "profiles_detached": used,
            "note": "Imported files are never deleted from disk." if delete_files and m["source"] != "hf" else ""}


@router.post("/models/import")
def model_import(body: dict = Body(...)):
    folder = body.get("folder", "")
    if not folder or not Path(folder).is_dir():
        raise HTTPException(400, "choose an existing folder")
    added = hf.import_folder(folder)
    return {"added": len(added), "ids": added}


@router.get("/models/{mid}")
def model_detail(mid: str):
    with db.Session() as s:
        m = s.get(db.Model, mid)
        if not m:
            raise HTTPException(404, "model not found")
        d = hf.model_dict(m)
    d["contexts"] = _context_table(_full_meta(mid), profiles.default_local(_full_meta(mid))) if d["status"] == "ready" else []
    return d


def _full_meta(mid):
    with db.Session() as s:
        m = s.get(db.Model, mid)
        return m.meta if m else {}


RECOMMENDED = [
    {"repo": "unsloth/Qwen3.8-27B-GGUF", "family": "Qwen3.8 27B", "kind": "dense", "why": "Best local coder in round 1 (91/100, 100% correctness at Q3_K_XL)."},
    {"repo": "unsloth/Qwen3.6-35B-A3B-GGUF", "family": "Qwen3.6 35B-A3B", "kind": "MoE", "why": "MoE: 3B active parameters, very fast (about 165 tok/s on an RTX 5080)."},
    {"repo": "unsloth/gemma-4-26B-A4B-it-GGUF", "family": "Gemma 4 26B-A4B", "kind": "MoE", "why": "Strong MoE with sliding-window attention: long contexts are cheap."},
    {"repo": "unsloth/gemma-4-12b-it-GGUF", "family": "Gemma 4 12B", "kind": "dense", "why": "Good mid-size option for 12-16 GB cards."},
    {"repo": "unsloth/Qwen3.5-9B-GGUF", "family": "Qwen3.5 9B", "kind": "dense", "why": "Fits 8-12 GB cards with a 64k context."},
    {"repo": "ggml-org/gpt-oss-20b-GGUF", "family": "gpt-oss 20B", "kind": "MoE", "why": "OpenAI's open-weight MoE; a useful reference point."},
    {"repo": "unsloth/gemma-4-E4B-it-GGUF", "family": "Gemma 4 E4B", "kind": "edge", "why": "Edge model for 6-8 GB GPUs or CPU."},
]


@router.get("/models/recommended/list")
def recommended():
    s = sysspecs.detect()
    g = sysspecs.primary_gpu(s)
    with db.Session() as ss:
        have = {m.repo for m in ss.query(db.Model).all()}
    return {"gpu": g and {"name": g["name"], "vram_total_mib": g["vram_total_mib"]},
            "items": [{**r, "downloaded": r["repo"] in have} for r in RECOMMENDED]}


# ================================================================== profiles
def _profile_out(p, model=None, provider=None):
    d = dict(p)
    d["model"] = model and {k: model[k] for k in ("id", "name", "quant", "repo", "size_bytes", "status")}
    d["provider"] = provider and {k: provider[k] for k in ("id", "name", "vendor", "api_style")}
    if d.get("fit", {}).get("raw"):
        d["fit"] = {k: v for k, v in d["fit"].items() if k != "raw"} | {"has_exact": True}
    return d


@router.get("/profiles")
def list_profiles():
    with db.Session() as s:
        out = []
        for p in s.query(db.Profile).order_by(db.Profile.created_at).all():
            m = s.get(db.Model, p.model_id) if p.model_id else None
            v = s.get(db.Provider, p.provider_id) if p.provider_id else None
            out.append(_profile_out(db.row(p), db.row(m) if m else None, db.row(v) if v else None))
        return out


@router.get("/profiles/defaults")
def profile_defaults(kind: str = "local", model_id: str | None = None):
    if kind == "local":
        return profiles.default_local(_full_meta(model_id) if model_id else None)
    return dict(profiles.CLOUD_DEFAULTS)


def _validate(kind, params):
    errs = profiles.validate_local(params) if kind == "local" else profiles.validate_cloud(params)
    if errs:
        raise HTTPException(400, "; ".join(errs))


@router.post("/profiles")
def create_profile(body: dict = Body(...)):
    kind = body.get("kind")
    if kind not in ("local", "cloud"):
        raise HTTPException(400, "kind must be local or cloud")
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "name is required")
    if kind == "local":
        m = _get(db.Model, body.get("model_id") or "")
        params = profiles.merge(profiles.default_local(m["meta"]), body.get("params"))
    else:
        _get(db.Provider, body.get("provider_id") or "")
        if not (body.get("remote_model") or "").strip():
            raise HTTPException(400, "choose a model id")
        params = profiles.merge(profiles.CLOUD_DEFAULTS, body.get("params"))
    _validate(kind, params)
    pid = db.new_id("prof")
    with db.Session() as s:
        s.add(db.Profile(id=pid, name=name, kind=kind, model_id=body.get("model_id") if kind == "local" else None,
                         provider_id=body.get("provider_id") if kind == "cloud" else None,
                         remote_model=(body.get("remote_model") or "").strip(), params=params,
                         pricing=body.get("pricing") or {}, notes=body.get("notes", ""), tags=body.get("tags") or []))
        s.commit()
    return get_profile(pid)


@router.get("/profiles/{pid}")
def get_profile(pid: str):
    p = _get(db.Profile, pid)
    m = _get(db.Model, p["model_id"]) if p["model_id"] else None
    v = _get(db.Provider, p["provider_id"]) if p["provider_id"] else None
    return _profile_out(p, m, v)


@router.patch("/profiles/{pid}")
def patch_profile(pid: str, body: dict = Body(...)):
    p = _get(db.Profile, pid)
    params = profiles.merge(p["params"], body.get("params")) if "params" in body else p["params"]
    if "params" in body and isinstance(body["params"].get("sampling"), dict):
        params["sampling"] = {**p["params"].get("sampling", {}), **body["params"]["sampling"]}
    _validate(p["kind"], params)
    with db.Session() as s:
        obj = s.get(db.Profile, pid)
        for k in ("name", "notes", "tags", "pricing", "remote_model"):
            if k in body:
                setattr(obj, k, body[k].strip() if isinstance(body[k], str) else body[k])
        if not obj.name:
            raise HTTPException(400, "name is required")
        obj.params = params
        obj.updated_at = time.time()
        if "params" in body:
            obj.fit = {}
        s.commit()
    return get_profile(pid)


@router.delete("/profiles/{pid}")
def delete_profile(pid: str):
    with db.Session() as s:
        n = s.query(db.Run).filter(db.Run.profile_id == pid, db.Run.status.in_(["queued", "running", "grading"])).count()
        if n:
            raise HTTPException(409, "this profile has queued or running runs")
        s.query(db.Profile).filter(db.Profile.id == pid).delete()
        s.commit()
    return {"ok": True}


@router.post("/profiles/{pid}/duplicate")
def duplicate_profile(pid: str):
    p = _get(db.Profile, pid)
    nid = db.new_id("prof")
    with db.Session() as s:
        s.add(db.Profile(id=nid, name=p["name"] + " (copy)", kind=p["kind"], model_id=p["model_id"],
                         provider_id=p["provider_id"], remote_model=p["remote_model"], params=p["params"],
                         pricing=p["pricing"], notes=p["notes"], tags=p["tags"]))
        s.commit()
    return get_profile(nid)


@router.post("/profiles/check")
def check_profile(body: dict = Body(...)):
    """Live memory check for the profile editor. exact=true also runs llama-fit-params (local files only)."""
    m = _get(db.Model, body["model_id"])
    params = profiles.merge(profiles.default_local(m["meta"]), body.get("params"))
    errs = profiles.validate_local(params)
    if errs:
        return {"errors": errs}
    fit = None
    if body.get("exact") and m["status"] == "ready" and llamacpp.installed()["installed"]:
        try:
            fit = llamacpp.fit_params(Path(m["local_dir"]) / m["files"][0], profiles.launch_params(params),
                                      int(config.get("default_vram_margin_mib")))
        except Exception as e:  # noqa: BLE001 - fall back to the estimate
            fit = {"error": str(e)}
    bench_list = [benches.get(b) for b in body.get("benchmark_ids", []) if b]
    chk = memory.check(m["meta"], params, sysspecs.detect(force=bool(body.get("exact"))),
                       fit=fit if fit and fit.get("devices") else None, os_name=OS_NAME, benchmarks=bench_list)
    if fit and fit.get("devices") and body.get("profile_id"):
        with db.Session() as s:
            obj = s.get(db.Profile, body["profile_id"])
            if obj:
                obj.fit = {"verdict": chk["verdict"], "at": time.time(), "memory": chk["memory"], "raw": fit}
                s.commit()
    chk["fit_error"] = (fit or {}).get("error")
    chk["contexts"] = _context_table(m["meta"], params)
    return chk


@router.post("/profiles/{pid}/smoke")
def smoke_profile(pid: str):
    p = _get(db.Profile, pid)
    return {"job_id": jobs.submit("smoke", f"Test profile {p['name']}", smoke.run, {"profile_id": pid}, ref=pid)}


@router.get("/profiles/{pid}/export")
def export_profile(pid: str):
    p = get_profile(pid)
    out = {"llmdyno_profile": 1, "llmdyno_version": __version__, "name": p["name"], "kind": p["kind"], "params": p["params"],
           "pricing": p["pricing"], "notes": p["notes"], "tags": p["tags"], "remote_model": p["remote_model"],
           "model": p["model"] and {"repo": p["model"]["repo"], "name": p["model"]["name"], "quant": p["model"]["quant"]},
           "provider_vendor": p["provider"] and p["provider"]["vendor"]}
    return Response(json.dumps(out, indent=2), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{p["name"]}.profile.json"'})


@router.post("/profiles/import")
def import_profile(body: dict = Body(...)):
    if body.get("llmdyno_profile") != 1:
        raise HTTPException(400, "not a LLMDyno profile file")
    with db.Session() as s:
        if body["kind"] == "local":
            want = body.get("model") or {}
            m = next((m for m in s.query(db.Model).all() if m.repo == want.get("repo") and m.quant == want.get("quant")), None)
            if not m:
                raise HTTPException(409, f"download {want.get('repo')} {want.get('quant')} first, then import again")
            return create_profile({"kind": "local", "name": body["name"], "model_id": m.id, "params": body["params"],
                                   "notes": body.get("notes", ""), "tags": body.get("tags") or []})
        prov = next((v for v in s.query(db.Provider).all() if v.vendor == body.get("provider_vendor")), None)
        if not prov:
            raise HTTPException(409, f"add a {body.get('provider_vendor')} provider first, then import again")
        return create_profile({"kind": "cloud", "name": body["name"], "provider_id": prov.id,
                               "remote_model": body.get("remote_model"), "params": body["params"],
                               "pricing": body.get("pricing") or {}, "notes": body.get("notes", "")})


# ================================================================== providers
@router.get("/vendors")
def list_vendors():
    return providers.VENDORS


def _provider_out(p):
    d = dict(p)
    d["has_key"] = secrets.has(providers.secret_name(p["id"]))
    d["key_hint"] = secrets.masked(providers.secret_name(p["id"]))
    from .. import llm
    d["spent_usd"] = round(llm.ledger_spent(p["id"]), 6)
    return d


@router.get("/providers")
def list_providers():
    with db.Session() as s:
        return [_provider_out(db.row(p)) for p in s.query(db.Provider).order_by(db.Provider.created_at).all()]


@router.post("/providers")
def create_provider(body: dict = Body(...)):
    vendor = providers.BY_ID.get(body.get("vendor"))
    if not vendor:
        raise HTTPException(400, "unknown vendor")
    style = body.get("api_style") or vendor["api_style"]
    if style not in vendor["styles"]:
        raise HTTPException(400, f"{vendor['name']} supports {', '.join(vendor['styles'])}")
    base = (body.get("base_url") or vendor["styles"].get(style) or vendor["base_url"]).strip()
    if not base.startswith(("http://", "https://")):
        raise HTTPException(400, "base URL must start with http:// or https://")
    budget = float(body.get("budget_usd", 5))
    if budget < 0:
        raise HTTPException(400, "budget cannot be negative")
    pid = db.new_id("prov")
    with db.Session() as s:
        s.add(db.Provider(id=pid, vendor=vendor["id"], name=(body.get("name") or vendor["name"]).strip(), base_url=base,
                          api_style=style, budget_usd=budget))
        s.commit()
    if body.get("api_key"):
        secrets.set(providers.secret_name(pid), body["api_key"])
    return _provider_out(_get(db.Provider, pid))


@router.patch("/providers/{pid}")
def patch_provider(pid: str, body: dict = Body(...)):
    p = _get(db.Provider, pid)
    vendor = providers.BY_ID.get(p["vendor"], providers.BY_ID["custom"])
    with db.Session() as s:
        obj = s.get(db.Provider, pid)
        if "name" in body:
            obj.name = body["name"].strip() or obj.name
        if "budget_usd" in body:
            if float(body["budget_usd"]) < 0:
                raise HTTPException(400, "budget cannot be negative")
            obj.budget_usd = float(body["budget_usd"])
        if "api_style" in body:
            if body["api_style"] not in vendor["styles"]:
                raise HTTPException(400, f"{vendor['name']} supports {', '.join(vendor['styles'])}")
            obj.api_style = body["api_style"]
            if p["vendor"] != "custom":
                obj.base_url = vendor["styles"][body["api_style"]] or obj.base_url
        if "base_url" in body:
            if not body["base_url"].startswith(("http://", "https://")):
                raise HTTPException(400, "base URL must start with http:// or https://")
            obj.base_url = body["base_url"].strip()
        s.commit()
    return _provider_out(_get(db.Provider, pid))


@router.put("/providers/{pid}/key")
def set_provider_key(pid: str, body: dict = Body(...)):
    _get(db.Provider, pid)
    secrets.set(providers.secret_name(pid), body.get("api_key", ""))
    return _provider_out(_get(db.Provider, pid))


@router.delete("/providers/{pid}/key")
def del_provider_key(pid: str):
    secrets.delete(providers.secret_name(pid))
    return _provider_out(_get(db.Provider, pid))


@router.post("/providers/{pid}/test")
def test_provider(pid: str):
    p = _get(db.Provider, pid)
    key = secrets.get(providers.secret_name(pid))
    if not key and p["vendor"] != "custom":
        raise HTTPException(400, "add an API key first")
    try:
        res = providers.list_models(p["base_url"], p["api_style"], key)
        ok, err = True, None
    except (PermissionError, ConnectionError) as e:
        res, ok, err = {"models": [], "latency_ms": None}, False, str(e)
    with db.Session() as s:
        obj = s.get(db.Provider, pid)
        obj.last_check = {"ok": ok, "error": err, "at": time.time(), "latency_ms": res["latency_ms"], "n_models": len(res["models"])}
        if ok:
            obj.models_cache = res["models"]
        s.commit()
    return {"ok": ok, "error": err, "models": res["models"], "latency_ms": res["latency_ms"]}


@router.post("/providers/{pid}/reset-spend")
def reset_spend(pid: str):
    from .. import llm
    _get(db.Provider, pid)
    llm.ledger_reset(f"provider_{pid}")
    return _provider_out(_get(db.Provider, pid))


@router.delete("/providers/{pid}")
def delete_provider(pid: str):
    with db.Session() as s:
        n = s.query(db.Profile).filter(db.Profile.provider_id == pid).count()
        if n:
            raise HTTPException(409, f"{n} profile(s) use this provider; delete them first")
        s.query(db.Provider).filter(db.Provider.id == pid).delete()
        s.commit()
    secrets.delete(providers.secret_name(pid))
    return {"ok": True}


@router.get("/pricing/lookup")
def pricing_lookup(vendor: str, model: str):
    hit = providers.lookup_price(vendor, model)
    return {"match": hit}


# ================================================================== harnesses
def _build_harness(hid):
    h = catalog.get(hid, images.custom_manifests())
    return jobs.submit("build", f"Build {h.name} {h.version}", images.build_harness, {"harness_id": h.id}, ref=h.id)


@router.get("/harnesses")
def list_harnesses():
    out = []
    for h in catalog.BUILTIN + [catalog.Custom(m) for m in images.custom_manifests()]:
        out.append({**h.info(), **images.harness_status(h)})
    return out


@router.post("/harnesses/{hid}/build")
def build_harness(hid: str):
    return {"job_id": _build_harness(hid)}


@router.delete("/harnesses/{hid}/image")
def remove_harness_image(hid: str):
    h = catalog.get(hid, images.custom_manifests())
    ok, msg = images.remove_image(h.image())
    if not ok:
        raise HTTPException(409, msg or "could not remove the image")
    return {"ok": True}


@router.get("/harnesses/{hid}/dockerfile", response_class=PlainTextResponse)
def harness_dockerfile(hid: str):
    return catalog.get(hid, images.custom_manifests()).dockerfile(images.SANDBOX)


@router.get("/harnesses/{hid}/preview")
def harness_preview(hid: str, api_style: str = "openai-chat"):
    """Rendered config files and command for a sample endpoint, so users can see exactly what will run."""
    h = catalog.get(hid, images.custom_manifests())
    rc = catalog.RunCtx(model="example-model", base_url="http://dyno-proxy-example:8081", api_style=api_style if api_style in h.apis
                        else h.apis[0], ctx=65536, max_tokens=16384, reasoning="medium", session_id="bench-example")
    return {"files": h.files(rc), "env": h.env(rc), "command": h.command(rc, 1, 1), "continue_command": h.command(rc, 2, 2),
            "api_style": rc.api_style}


@router.get("/harnesses-schema")
def harness_schema():
    return catalog.MANIFEST_SCHEMA


@router.post("/harnesses/custom")
def add_custom_harness(body: dict = Body(...)):
    errs = catalog.validate_manifest(body)
    with db.Session() as s:
        if s.get(db.CustomHarness, body.get("id", "")):
            errs.append("a custom harness with this id exists")
        if errs:
            raise HTTPException(400, "; ".join(errs))
        s.add(db.CustomHarness(id=body["id"], manifest=body))
        s.commit()
    return {**catalog.Custom(body).info(), **images.harness_status(catalog.Custom(body))}


@router.put("/harnesses/custom/{hid}")
def update_custom_harness(hid: str, body: dict = Body(...)):
    body["id"] = hid
    errs = [e for e in catalog.validate_manifest(body) if "clashes" not in e]
    if errs:
        raise HTTPException(400, "; ".join(errs))
    with db.Session() as s:
        obj = s.get(db.CustomHarness, hid)
        if not obj:
            raise HTTPException(404, "custom harness not found")
        obj.manifest = body
        s.commit()
    return {"ok": True}


@router.delete("/harnesses/custom/{hid}")
def delete_custom_harness(hid: str):
    with db.Session() as s:
        s.query(db.CustomHarness).filter(db.CustomHarness.id == hid).delete()
        s.query(db.HarnessBuild).filter(db.HarnessBuild.harness_id == hid).delete()
        s.commit()
    return {"ok": True}


# ================================================================== benchmarks & suites
@router.get("/benchmarks")
def list_benchmarks():
    return benches.all_benchmarks()


@router.get("/benchmarks/{bid}")
def benchmark_detail(bid: str):
    return benches.detail(bid)


@router.get("/benchmarks/{bid}/spec")
def benchmark_spec(bid: str):
    return benches.custom_spec(bid)


@router.post("/benchmarks")
def create_benchmark(body: dict = Body(...)):
    return benches.save_custom(body)


@router.put("/benchmarks/{bid}")
def update_benchmark(bid: str, body: dict = Body(...)):
    body["id"] = bid
    if benches.get(bid)["builtin"]:
        raise HTTPException(403, "built-in benchmarks are read-only; duplicate it to edit")
    return benches.save_custom(body, overwrite=True)


@router.delete("/benchmarks/{bid}")
def delete_benchmark(bid: str):
    benches.delete_custom(bid)
    return {"ok": True}


@router.post("/benchmarks/{bid}/duplicate")
def duplicate_benchmark(bid: str, body: dict = Body(...)):
    return benches.duplicate(bid, body.get("new_id", ""))


@router.get("/benchmarks/{bid}/export")
def export_benchmark(bid: str):
    return Response(benches.export_zip(bid), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{bid}.zip"'})


@router.post("/benchmarks/{bid}/validate")
def validate_benchmark(bid: str):
    benches.get(bid)
    return {"job_id": jobs.submit("validate", f"Validate grader: {bid}", bvalidate.validate, {"benchmark_id": bid}, ref=bid)}


@router.get("/suites")
def list_suites():
    return benches.suites()


@router.post("/suites")
def create_suite(body: dict = Body(...)):
    name = (body.get("name") or "").strip()
    ids = body.get("benchmark_ids") or []
    if not name or not ids:
        raise HTTPException(400, "a suite needs a name and at least one benchmark")
    known = {b["id"] for b in benches.all_benchmarks()}
    if set(ids) - known:
        raise HTTPException(400, f"unknown benchmarks: {', '.join(sorted(set(ids) - known))}")
    sid = db.new_id("suite")
    with db.Session() as s:
        s.add(db.Suite(id=sid, name=name, description=body.get("description", ""), benchmark_ids=ids))
        s.commit()
    return _get(db.Suite, sid)


@router.put("/suites/{sid}")
def update_suite(sid: str, body: dict = Body(...)):
    if sid.startswith("suite_") and any(s["id"] == sid for s in benches.BUILTIN_SUITES):
        raise HTTPException(403, "built-in suites are read-only")
    with db.Session() as s:
        obj = s.get(db.Suite, sid)
        if not obj:
            raise HTTPException(404, "suite not found")
        if "name" in body:
            obj.name = body["name"].strip() or obj.name
        if "description" in body:
            obj.description = body["description"]
        if "benchmark_ids" in body:
            if not body["benchmark_ids"]:
                raise HTTPException(400, "a suite needs at least one benchmark")
            obj.benchmark_ids = body["benchmark_ids"]
        s.commit()
    return _get(db.Suite, sid)


@router.delete("/suites/{sid}")
def delete_suite(sid: str):
    if any(s["id"] == sid for s in benches.BUILTIN_SUITES):
        raise HTTPException(403, "built-in suites cannot be deleted")
    with db.Session() as s:
        s.query(db.Suite).filter(db.Suite.id == sid).delete()
        s.commit()
    return {"ok": True}


# ================================================================== plans & runs
def _plan_spec(body):
    spec = {"name": (body.get("name") or "").strip(), "profile_ids": body.get("profile_ids") or [],
            "harness_ids": body.get("harness_ids") or [], "benchmark_ids": body.get("benchmark_ids") or [],
            "iterations": int(body.get("iterations") or 1), "options": body.get("options") or {}}
    if not 1 <= spec["iterations"] <= 20:
        raise HTTPException(400, "iterations must be 1-20")
    return spec


@router.post("/plans/preflight")
def plan_preflight(body: dict = Body(...)):
    return executor.preflight(_plan_spec(body))


@router.post("/plans")
def create_plan(body: dict = Body(...)):
    spec = _plan_spec(body)
    pf = executor.preflight(spec)
    if not pf["ok"]:
        raise HTTPException(409, "; ".join(b["text"] for b in pf["blocking"]))
    unacked = [w for w in pf["warnings"] if w.get("ack")]
    if unacked and not body.get("acknowledge_risks"):
        raise HTTPException(428, "acknowledge the danger warnings first: " + "; ".join(w["text"] for w in unacked))
    spec["preflight"] = pf
    pid = executor.create_plan(spec)
    job = executor.start_plan(pid) if body.get("start", True) else None
    return {"plan_id": pid, "job_id": job}


def _plan_out(p, with_runs=False):
    with db.Session() as s:
        runs = s.query(db.Run).filter(db.Run.plan_id == p["id"]).all()
        counts = {}
        for r in runs:
            counts[r.status] = counts.get(r.status, 0) + 1
        d = {**p, "counts": counts, "n_runs": len(runs),
             "spent_usd": round(sum(r.cost_usd or 0 for r in runs if (r.snapshot or {}).get("profile", {}).get("kind") == "cloud"), 4)}
        if with_runs:
            d["runs"] = [executor.run_summary(r) for r in runs]
        job = s.query(db.Job).filter(db.Job.ref == p["id"], db.Job.kind == "plan").order_by(db.Job.created_at.desc()).first()
        d["job"] = jobs.job_dict(job) if job else None
    return d


@router.get("/plans")
def list_plans():
    with db.Session() as s:
        plans = [db.row(p) for p in s.query(db.Plan).order_by(db.Plan.created_at.desc()).all()]
    return [_plan_out(p) for p in plans]


@router.get("/plans/{pid}")
def get_plan(pid: str):
    return _plan_out(_get(db.Plan, pid), with_runs=True)


@router.post("/plans/{pid}/pause")
def pause_plan(pid: str):
    p = _get(db.Plan, pid)
    if p["status"] not in ("running", "queued"):
        raise HTTPException(409, f"plan is {p['status']}")
    executor._set_plan(pid, status="paused")
    return {"ok": True, "message": "Runs already in progress finish; no new runs start."}


@router.post("/plans/{pid}/resume")
def resume_plan(pid: str):
    p = _get(db.Plan, pid)
    if p["status"] in ("running", "queued"):
        raise HTTPException(409, "plan is already running")
    with db.Session() as s:
        if not s.query(db.Run).filter(db.Run.plan_id == pid, db.Run.status == "queued").count():
            raise HTTPException(409, "no queued runs left; use retry to rerun failed ones")
    return {"job_id": executor.start_plan(pid)}


@router.post("/plans/{pid}/cancel")
def cancel_plan(pid: str):
    _get(db.Plan, pid)
    executor._set_plan(pid, status="cancelled")
    with db.Session() as s:
        for j in s.query(db.Job).filter(db.Job.ref == pid, db.Job.kind == "plan", db.Job.status.in_(["queued", "running"])):
            jobs.cancel(j.id)
        for r in s.query(db.Run).filter(db.Run.plan_id == pid, db.Run.status == "queued"):
            r.status = "cancelled"
        s.commit()
    for r in _get_runs(pid):
        if r["status"] in ("running", "grading"):
            executor.cancel_run(r["id"])
    return {"ok": True}


def _get_runs(pid):
    with db.Session() as s:
        return [db.row(r) for r in s.query(db.Run).filter(db.Run.plan_id == pid).all()]


@router.post("/plans/{pid}/retry")
def retry_plan(pid: str, body: dict = Body(default={})):
    p = _get(db.Plan, pid)
    if p["status"] in ("running", "queued"):
        raise HTTPException(409, "wait for the plan to stop or pause it first")
    statuses = body.get("statuses") or ["failed", "cancelled"]
    with db.Session() as s:
        n = 0
        for r in s.query(db.Run).filter(db.Run.plan_id == pid, db.Run.status.in_(statuses)):
            r.status, r.error, r.stage, r.metrics, r.quality = "queued", "", "", {}, {}
            r.correctness = r.instruction_following = r.wall_s = r.cost_usd = None
            n += 1
        if n:
            pl = s.get(db.Plan, pid)
            pl.started_at, pl.ended_at = None, None     # a retry is a new execution: elapsed time restarts
        s.commit()
    if not n:
        raise HTTPException(409, "nothing to retry")
    return {"requeued": n, "job_id": executor.start_plan(pid)}


@router.patch("/plans/{pid}")
def rename_plan(pid: str, body: dict = Body(...)):
    _get(db.Plan, pid)
    if not (body.get("name") or "").strip():
        raise HTTPException(400, "name is required")
    executor._set_plan(pid, name=body["name"].strip())
    return _get(db.Plan, pid)


@router.delete("/plans/{pid}")
def delete_plan(pid: str, delete_files: bool = True):
    p = _get(db.Plan, pid)
    if p["status"] in ("running", "queued"):
        raise HTTPException(409, "cancel the plan before deleting it")
    with db.Session() as s:
        run_ids = [r.id for r in s.query(db.Run).filter(db.Run.plan_id == pid)]
        s.query(db.Review).filter(db.Review.run_id.in_(run_ids)).delete(synchronize_session=False)
        s.query(db.Run).filter(db.Run.plan_id == pid).delete()
        s.query(db.Plan).filter(db.Plan.id == pid).delete()
        s.commit()
    if delete_files:
        shutil.rmtree(config.path("runs_dir") / pid, ignore_errors=True)
    events.publish("plans", "deleted", {"id": pid})
    return {"ok": True}


@router.get("/runs/{rid}")
def get_run(rid: str):
    r = _get(db.Run, rid)
    reviews = []
    with db.Session() as s:
        reviews = [db.row(x) for x in s.query(db.Review).filter(db.Review.run_id == rid).all()]
    q = r.get("quality") or {}
    static = (q.get("static") or {})
    return {**r, "quality": {**q, "static": {k: v for k, v in static.items() if k != "files"},
                             "files": static.get("files")}, "reviews": reviews}


@router.post("/runs/{rid}/cancel")
def cancel_run(rid: str):
    if not executor.cancel_run(rid):
        raise HTTPException(409, "run is not active")
    return {"ok": True}


@router.post("/runs/{rid}/retry")
def retry_run(rid: str):
    r = _get(db.Run, rid)
    if r["status"] in ("queued", "running", "grading"):
        raise HTTPException(409, "run is still active")
    plan = _get(db.Plan, r["plan_id"])
    with db.Session() as s:
        obj = s.get(db.Run, rid)
        obj.status, obj.error, obj.stage, obj.metrics, obj.quality = "queued", "", "", {}, {}
        obj.correctness = obj.instruction_following = obj.wall_s = obj.cost_usd = None
        s.commit()
    job = executor.start_plan(r["plan_id"]) if plan["status"] not in ("running", "queued") else None
    return {"ok": True, "job_id": job}


@router.get("/runs/{rid}/transcript")
def run_transcript(rid: str, start: int = 0, limit: int = 20000):
    r = _get(db.Run, rid)
    lines = metrics.read_jsonl(Path(r["dir"]) / "transcript.jsonl") if r["dir"] else []
    return {"start": start, "total": len(lines), "events": lines[start:start + limit]}


@router.get("/runs/{rid}/proxy")
def run_proxy(rid: str):
    r = _get(db.Run, rid)
    recs = metrics.read_jsonl(Path(r["dir"]) / "proxy.jsonl") if r["dir"] else []
    keep = ("seq", "ts", "t_end", "wall_s", "ttft_s", "finish_reason", "usage_norm", "timings", "n_tool_calls",
            "tool_names", "cost_usd", "status", "budget_blocked", "api", "model")
    return [{k: x.get(k) for k in keep} for x in recs if "usage_norm" in x or "timings" in x or x.get("budget_blocked")]


SKIP = {"__pycache__", ".pytest_cache", "node_modules", ".git", ".ruff_cache", ".mypy_cache", "htmlcov"}


@router.get("/runs/{rid}/files")
def run_files(rid: str, root: str = "workspace"):
    r = _get(db.Run, rid)
    if root not in ("workspace", "home") or not r["dir"]:
        raise HTTPException(400, "unknown root")
    base = Path(r["dir"]) / root
    out = []
    if base.exists():
        for p in sorted(base.rglob("*")):
            rel = p.relative_to(base)
            if set(rel.parts) & SKIP:
                continue
            if p.is_file():
                out.append({"path": rel.as_posix(), "size": p.stat().st_size, "mtime": p.stat().st_mtime})
                if len(out) >= 3000:
                    break
    return out


@router.get("/runs/{rid}/file")
def run_file(rid: str, path: str, root: str = "workspace"):
    r = _get(db.Run, rid)
    if root not in ("workspace", "home") or not r["dir"]:
        raise HTTPException(400, "unknown root")
    base = (Path(r["dir"]) / root).resolve()
    f = (base / path).resolve()
    if base not in f.parents or not f.is_file():
        raise HTTPException(404, "file not found")
    if f.stat().st_size > 2 * 2**20:
        return PlainTextResponse(f"(file is {f.stat().st_size / 2**20:.1f} MB; too large to show)")
    data = f.read_bytes()
    if b"\0" in data[:4096]:
        return PlainTextResponse("(binary file)")
    return PlainTextResponse(data.decode("utf-8", "replace"))


@router.get("/runs/{rid}/log")
def run_log(rid: str, name: str):
    r = _get(db.Run, rid)
    allowed = {"server"} | {f"{k}_stage{i}.log" for k in ("stdout", "stderr") for i in range(1, 21)}
    if name not in allowed or not r["dir"]:
        raise HTTPException(400, "unknown log")
    if name == "server":
        f = Path(r["dir"]).parent / f"server_{r['profile_id']}.log"
    else:
        f = Path(r["dir"]) / name
    if not f.exists():
        return PlainTextResponse("")
    data = f.read_bytes()[-400_000:]
    return PlainTextResponse(data.decode("utf-8", "replace"))


@router.get("/runs/{rid}/gpu")
def run_gpu(rid: str, max_points: int = 600):
    r = _get(db.Run, rid)
    if not r["dir"] or not r["started_at"]:
        return []
    f = Path(r["dir"]).parent / f"gpu_{r['profile_id']}.jsonl"
    end = (r["ended_at"] or time.time()) + 2
    rows = [x for x in metrics.read_jsonl(f) if r["started_at"] - 2 <= x.get("ts", 0) <= end]
    step = max(1, len(rows) // max_points)
    return rows[::step]


@router.get("/runs/{rid}/download")
def run_download(rid: str):
    r = _get(db.Run, rid)
    if not r["dir"] or not Path(r["dir"]).exists():
        raise HTTPException(404, "run folder not found")
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    archive = shutil.make_archive(str(tmp / rid), "zip", r["dir"], "workspace")
    return FileResponse(archive, filename=f"{rid}-workspace.zip", media_type="application/zip")


# ================================================================== jobs
@router.get("/jobs")
def list_jobs(active: bool = False, limit: int = 100, kind: str | None = None):
    with db.Session() as s:
        q = s.query(db.Job)
        if active:
            q = q.filter(db.Job.status.in_(["queued", "running"]))
        if kind:
            q = q.filter(db.Job.kind == kind)
        return [jobs.job_dict(j) for j in q.order_by(db.Job.created_at.desc()).limit(min(limit, 500)).all()]


@router.get("/jobs/{jid}")
def get_job(jid: str):
    with db.Session() as s:
        j = s.get(db.Job, jid)
        if not j:
            raise HTTPException(404, "job not found")
        d = jobs.job_dict(j)
        d["log"] = j.log
        return d


@router.post("/jobs/{jid}/cancel")
def cancel_job(jid: str):
    if not jobs.cancel(jid):
        raise HTTPException(409, "job is not active")
    return {"ok": True}


@router.delete("/jobs")
def clear_jobs():
    with db.Session() as s:
        n = s.query(db.Job).filter(db.Job.status.in_(["done", "failed", "cancelled", "interrupted"])).delete()
        s.commit()
    return {"removed": n}


# ================================================================== judging
@router.get("/judge/defaults")
def judge_defaults():
    return {"rubric": judge_mod.DEFAULT_RUBRIC, "guidance": judge_mod.DEFAULT_GUIDANCE, "max_output_tokens": 12000,
            "concurrency": 4, "budget_usd": 1.0, "blind": True, "include_static": False, "skip_reviewed": True}


@router.post("/judge")
def start_judge(body: dict = Body(...)):
    jp = body.get("judge_profile_ids") or []
    if not jp:
        raise HTTPException(400, "choose at least one judge profile")
    for p in jp:
        _get(db.Profile, p)
    if not body.get("plan_ids") and not body.get("run_ids"):
        raise HTTPException(400, "choose plans or runs to review")
    rubric = body.get("rubric") or judge_mod.DEFAULT_RUBRIC
    if not rubric or any(not r.get("key") for r in rubric):
        raise HTTPException(400, "every rubric dimension needs a key")
    cfg = {k: body.get(k) for k in ("judge_profile_ids", "plan_ids", "run_ids", "rubric", "guidance", "include_static",
                                    "budget_usd", "skip_reviewed", "concurrency", "max_output_tokens")}
    cfg["rubric"] = rubric
    return {"job_id": jobs.submit("judge", "Judge: " + ", ".join(_get(db.Profile, p)["name"] for p in jp),
                                  judge_mod.run_judge, cfg, ref=",".join(body.get("plan_ids") or []))}


@router.get("/reviews")
def list_reviews(plan_id: str | None = None, run_id: str | None = None):
    with db.Session() as s:
        q = s.query(db.Review)
        if run_id:
            q = q.filter(db.Review.run_id == run_id)
        elif plan_id:
            ids = [r.id for r in s.query(db.Run).filter(db.Run.plan_id == plan_id)]
            q = q.filter(db.Review.run_id.in_(ids))
        return [db.row(r) for r in q.all()]


@router.delete("/reviews")
def delete_reviews(judge_id: str = Query(...), plan_id: str | None = None):
    with db.Session() as s:
        q = s.query(db.Review).filter(db.Review.judge_id == judge_id)
        if plan_id:
            ids = [r.id for r in s.query(db.Run).filter(db.Run.plan_id == plan_id)]
            q = q.filter(db.Review.run_id.in_(ids))
        n = q.delete(synchronize_session=False)
        s.commit()
    return {"removed": n}

