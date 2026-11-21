"""Helpers shared by several service areas."""
import os
from .. import db, jobs, memory
from ..benchmarks import registry as benches
from ..harnesses import catalog, images
from .. import errors


OS_NAME = "nt" if os.name == "nt" else "posix"


def download(content, filename, media_type):
    """A file the caller should save or send: content in memory (bytes or text)."""
    return {"download": True, "filename": filename, "media_type": media_type, "content": content}


def file_download(path, filename, media_type):
    """A file the caller should save or send, already on disk (large archives)."""
    return {"download": True, "filename": filename, "media_type": media_type, "path": str(path)}


def _get(model, key):
    with db.Session() as s:
        obj = s.get(model, key)
        if obj is None:
            raise errors.http(404, f"{model.__tablename__[:-1]} {key} not found")
        return db.row(obj)


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


def _full_meta(mid):
    with db.Session() as s:
        m = s.get(db.Model, mid)
        return m.meta if m else {}


def _build_harness(hid):
    h = catalog.get(hid, images.custom_manifests())
    return jobs.submit("build", f"Build {h.name} {h.version}", images.build_harness, {"harness_id": h.id}, ref=h.id)


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
