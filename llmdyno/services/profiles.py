"""LLM profiles: a model plus the exact settings it is benchmarked with."""
import json
import time
from pathlib import Path
from .. import __version__, config, db, jobs, memory, profiles, smoke
from ..benchmarks import registry as benches
from ..inference import llamacpp
from ..system import specs as sysspecs
from .. import errors
from ._common import OS_NAME, _context_table, _full_meta, _get, download


def _profile_out(p, model = None, provider = None):
    d = dict(p)
    d["model"] = model and {k: model[k] for k in ("id", "name", "quant", "repo", "size_bytes", "status")}
    d["provider"] = provider and {k: provider[k] for k in ("id", "name", "vendor", "api_style")}
    if d.get("fit", {}).get("raw"):
        d["fit"] = {k: v for k, v in d["fit"].items() if k != "raw"} | {"has_exact": True}
    return d


def list_profiles():
    with db.Session() as s:
        out = []
        for p in s.query(db.Profile).order_by(db.Profile.created_at).all():
            m = s.get(db.Model, p.model_id) if p.model_id else None
            v = s.get(db.Provider, p.provider_id) if p.provider_id else None
            out.append(_profile_out(db.row(p), db.row(m) if m else None, db.row(v) if v else None))
        return out


def profile_defaults(kind: str = 'local', model_id: str | None = None):
    if kind == "local":
        return profiles.default_local(_full_meta(model_id) if model_id else None)
    return dict(profiles.CLOUD_DEFAULTS)


def _validate(kind, params):
    errs = profiles.validate_local(params) if kind == "local" else profiles.validate_cloud(params)
    if errs:
        raise errors.http(400, "; ".join(errs))


def create_profile(body: dict):
    kind = body.get("kind")
    if kind not in ("local", "cloud"):
        raise errors.http(400, "kind must be local or cloud")
    name = (body.get("name") or "").strip()
    if not name:
        raise errors.http(400, "name is required")
    if kind == "local":
        m = _get(db.Model, body.get("model_id") or "")
        params = profiles.merge(profiles.default_local(m["meta"]), body.get("params"))
    else:
        _get(db.Provider, body.get("provider_id") or "")
        if not (body.get("remote_model") or "").strip():
            raise errors.http(400, "choose a model id")
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


def get_profile(pid: str):
    p = _get(db.Profile, pid)
    m = _get(db.Model, p["model_id"]) if p["model_id"] else None
    v = _get(db.Provider, p["provider_id"]) if p["provider_id"] else None
    return _profile_out(p, m, v)


def patch_profile(pid: str, body: dict):
    p = _get(db.Profile, pid)
    params = profiles.merge(p["params"], body.get("params")) if "params" in body else p["params"]
    if "params" in body and isinstance(body["params"].get("sampling"), dict):
        params["sampling"] = {**p["params"].get("sampling", {}), **body["params"]["sampling"]}
    _validate(p["kind"], params)
    with db.Session() as s:
        obj = s.get(db.Profile, pid)
        assert obj is not None              # checked by _get() above
        for k in ("name", "notes", "tags", "pricing", "remote_model"):
            if k in body:
                setattr(obj, k, body[k].strip() if isinstance(body[k], str) else body[k])
        if not obj.name:
            raise errors.http(400, "name is required")
        obj.params = params
        obj.updated_at = time.time()
        if "params" in body:
            obj.fit = {}
        s.commit()
    return get_profile(pid)


def delete_profile(pid: str):
    with db.Session() as s:
        n = s.query(db.Run).filter(db.Run.profile_id == pid, db.Run.status.in_(["queued", "running", "grading"])).count()
        if n:
            raise errors.http(409, "this profile has queued or running runs")
        s.query(db.Profile).filter(db.Profile.id == pid).delete()
        s.commit()
    return {"ok": True}


def duplicate_profile(pid: str):
    p = _get(db.Profile, pid)
    nid = db.new_id("prof")
    with db.Session() as s:
        s.add(db.Profile(id=nid, name=p["name"] + " (copy)", kind=p["kind"], model_id=p["model_id"],
                         provider_id=p["provider_id"], remote_model=p["remote_model"], params=p["params"],
                         pricing=p["pricing"], notes=p["notes"], tags=p["tags"]))
        s.commit()
    return get_profile(nid)


def check_profile(body: dict):
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


def smoke_profile(pid: str):
    p = _get(db.Profile, pid)
    return {"job_id": jobs.submit("smoke", f"Test profile {p['name']}", smoke.run, {"profile_id": pid}, ref=pid)}


def export_profile(pid: str):
    p = get_profile(pid)
    out = {"llmdyno_profile": 1, "llmdyno_version": __version__, "name": p["name"], "kind": p["kind"], "params": p["params"],
           "pricing": p["pricing"], "notes": p["notes"], "tags": p["tags"], "remote_model": p["remote_model"],
           "model": p["model"] and {"repo": p["model"]["repo"], "name": p["model"]["name"], "quant": p["model"]["quant"]},
           "provider_vendor": p["provider"] and p["provider"]["vendor"]}
    return download(json.dumps(out, indent=2), f'{p["name"]}.profile.json', "application/json")


def import_profile(body: dict):
    if body.get("llmdyno_profile") != 1:
        raise errors.http(400, "not a LLMDyno profile file")
    with db.Session() as s:
        if body["kind"] == "local":
            want = body.get("model") or {}
            m = next((m for m in s.query(db.Model).all() if m.repo == want.get("repo") and m.quant == want.get("quant")), None)
            if not m:
                raise errors.http(409, f"download {want.get('repo')} {want.get('quant')} first, then import again")
            return create_profile({"kind": "local", "name": body["name"], "model_id": m.id, "params": body["params"],
                                   "notes": body.get("notes", ""), "tags": body.get("tags") or []})
        prov = next((v for v in s.query(db.Provider).all() if v.vendor == body.get("provider_vendor")), None)
        if not prov:
            raise errors.http(409, f"add a {body.get('provider_vendor')} provider first, then import again")
        return create_profile({"kind": "cloud", "name": body["name"], "provider_id": prov.id,
                               "remote_model": body.get("remote_model"), "params": body["params"],
                               "pricing": body.get("pricing") or {}, "notes": body.get("notes", "")})
