"""GGUF models: Hugging Face search, fit estimates, downloads, imports and the recommended list."""
from pathlib import Path
from .. import config, db, events, jobs, memory, profiles
from ..hub import hf
from ..system import specs as sysspecs
from .. import errors
from ._common import OS_NAME, _context_table, _full_meta, _get


RECOMMENDED = [
    {"repo": "unsloth/Qwen3.8-27B-GGUF", "family": "Qwen3.8 27B", "kind": "dense", "why": "Best local coder in round 1 (91/100, 100% correctness at Q3_K_XL)."},
    {"repo": "unsloth/Qwen3.6-35B-A3B-GGUF", "family": "Qwen3.6 35B-A3B", "kind": "MoE", "why": "MoE: 3B active parameters, very fast (about 165 tok/s on an RTX 5080)."},
    {"repo": "unsloth/gemma-4-26B-A4B-it-GGUF", "family": "Gemma 4 26B-A4B", "kind": "MoE", "why": "Strong MoE with sliding-window attention: long contexts are cheap."},
    {"repo": "unsloth/gemma-4-12b-it-GGUF", "family": "Gemma 4 12B", "kind": "dense", "why": "Good mid-size option for 12-16 GB cards."},
    {"repo": "unsloth/Qwen3.5-9B-GGUF", "family": "Qwen3.5 9B", "kind": "dense", "why": "Fits 8-12 GB cards with a 64k context."},
    {"repo": "ggml-org/gpt-oss-20b-GGUF", "family": "gpt-oss 20B", "kind": "MoE", "why": "OpenAI's open-weight MoE; a useful reference point."},
    {"repo": "unsloth/gemma-4-E4B-it-GGUF", "family": "Gemma 4 E4B", "kind": "edge", "why": "Edge model for 6-8 GB GPUs or CPU."},
]


def hub_search(q: str = '', sort: str = 'downloads', limit: int = 30):
    if len(q.strip()) < 2:
        return []
    return hf.search(q.strip(), limit=min(limit, 60), sort=sort if sort in ("downloads", "likes", "lastModified") else "downloads")


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


def hub_estimate(body: dict):
    repo, vid = body["repo"], body["variant_id"]
    info = hf.repo_files(repo)
    v = next((x for x in info["variants"] if x["id"] == vid), None)
    if not v:
        raise errors.http(404, "variant not found")
    meta = hf.remote_meta(repo, v)
    params = profiles.merge(profiles.default_local(meta), body.get("params") or {})
    chk = memory.check(meta, params, sysspecs.detect(), os_name=OS_NAME)
    return {"meta": _meta_public(meta), "params": params, "check": chk,
            "contexts": _context_table(meta, params)}


def _meta_public(meta):
    return {k: v for k, v in (meta or {}).items() if k not in ("layer_bytes", "expert_bytes", "swa_layers",
                                                                 "recurrent_layers", "n_head_kv")}


def list_models():
    with db.Session() as s:
        return [hf.model_dict(m) for m in s.query(db.Model).order_by(db.Model.created_at.desc()).all()]


def model_download(body: dict):
    repo, vid = body["repo"], body["variant_id"]
    info = hf.repo_files(repo)
    v = next((x for x in info["variants"] if x["id"] == vid), None)
    if not v:
        raise errors.http(404, "variant not found")
    target = hf.local_dir_for(repo)
    need = v["size_bytes"]
    if need > hf.free_bytes(config.path("models_dir")) - 512 * 2**20:
        raise errors.http(507, f"not enough disk space: {need / 2**30:.1f} GB needed, "
                                 f"{hf.free_bytes(config.path('models_dir')) / 2**30:.1f} GB free in {config.get('models_dir')}")
    with db.Session() as s:
        existing = [m for m in s.query(db.Model).filter(db.Model.repo == repo).all()
                    if m.files == [Path(f["path"]).name for f in v["files"]]]
        if existing and existing[0].status == "ready":
            raise errors.http(409, "this model is already downloaded")
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


def model_pause(mid: str):
    with db.Session() as s:
        j = s.query(db.Job).filter(db.Job.ref == mid, db.Job.kind == "download", db.Job.status.in_(["queued", "running"])).first()
    if not j:
        raise errors.http(409, "no active download for this model")
    jobs.cancel(j.id)
    return {"ok": True}


def model_resume(mid: str):
    m = _get(db.Model, mid)
    if m["status"] == "ready":
        raise errors.http(409, "already downloaded")
    info = hf.repo_files(m["repo"])
    v = next((x for x in info["variants"] if [Path(f["path"]).name for f in x["files"]] == m["files"]), None)
    if not v:
        raise errors.http(404, "the variant is no longer in the repository")
    job = jobs.submit("download", f"Download {m['repo']} · {m['quant']}", hf.download, {"model_id": mid, "files": v["files"]},
                      ref=mid)
    return {"job_id": job}


def model_delete(mid: str, delete_files: bool = False):
    m = _get(db.Model, mid)
    with db.Session() as s:
        active = s.query(db.Job).filter(db.Job.ref == mid, db.Job.status.in_(["queued", "running"])).first()
        if active:
            raise errors.http(409, "pause or finish the download first")
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


def model_import(body: dict):
    folder = body.get("folder", "")
    if not folder or not Path(folder).is_dir():
        raise errors.http(400, "choose an existing folder")
    added = hf.import_folder(folder)
    return {"added": len(added), "ids": added}


def model_detail(mid: str):
    with db.Session() as s:
        m = s.get(db.Model, mid)
        if not m:
            raise errors.http(404, "model not found")
        d = hf.model_dict(m)
    d["contexts"] = _context_table(_full_meta(mid), profiles.default_local(_full_meta(mid))) if d["status"] == "ready" else []
    return d


def recommended():
    s = sysspecs.detect()
    g = sysspecs.primary_gpu(s)
    with db.Session() as ss:
        have = {m.repo for m in ss.query(db.Model).all()}
    return {"gpu": g and {"name": g["name"], "vram_total_mib": g["vram_total_mib"]},
            "items": [{**r, "downloaded": r["repo"] in have} for r in RECOMMENDED]}
