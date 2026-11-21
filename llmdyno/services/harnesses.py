"""Agent harnesses: built-in and custom, images, Dockerfiles, previews and portable runtimes."""
from .. import db, jobs
from ..harnesses import catalog, images
from ..harnesses import runtime
from .. import errors
from ._common import _build_harness


def list_harnesses():
    out = []
    for h in catalog.BUILTIN + [catalog.Custom(m) for m in images.custom_manifests()]:
        out.append({**h.info(), **images.harness_status(h)})
    return out


def build_harness(hid: str):
    return {"job_id": _build_harness(hid)}


def remove_harness_image(hid: str):
    h = catalog.get(hid, images.custom_manifests())
    ok, msg = images.remove_image(h.image())
    if not ok:
        raise errors.http(409, msg or "could not remove the image")
    return {"ok": True}


def harness_dockerfile(hid: str):
    return catalog.get(hid, images.custom_manifests()).dockerfile(images.SANDBOX)


def harness_preview(hid: str, api_style: str = 'openai-chat'):
    """Rendered config files and command for a sample endpoint, so users can see exactly what will run."""
    h = catalog.get(hid, images.custom_manifests())
    rc = catalog.RunCtx(model="example-model", base_url="http://dyno-proxy-example:8081", api_style=api_style if api_style in h.apis
                        else h.apis[0], ctx=65536, max_tokens=16384, reasoning="medium", session_id="bench-example")
    return {"files": h.files(rc), "env": h.env(rc), "command": h.command(rc, 1, 1), "continue_command": h.command(rc, 2, 2),
            "api_style": rc.api_style}


def harness_schema():
    return catalog.MANIFEST_SCHEMA


def add_custom_harness(body: dict):
    errs = catalog.validate_manifest(body)
    with db.Session() as s:
        if s.get(db.CustomHarness, body.get("id", "")):
            errs.append("a custom harness with this id exists")
        if errs:
            raise errors.http(400, "; ".join(errs))
        s.add(db.CustomHarness(id=body["id"], manifest=body))
        s.commit()
    return {**catalog.Custom(body).info(), **images.harness_status(catalog.Custom(body))}


def update_custom_harness(hid: str, body: dict):
    body["id"] = hid
    errs = [e for e in catalog.validate_manifest(body) if "clashes" not in e]
    if errs:
        raise errors.http(400, "; ".join(errs))
    with db.Session() as s:
        obj = s.get(db.CustomHarness, hid)
        if not obj:
            raise errors.http(404, "custom harness not found")
        obj.manifest = body
        s.commit()
    return {"ok": True}


def delete_custom_harness(hid: str):
    with db.Session() as s:
        s.query(db.CustomHarness).filter(db.CustomHarness.id == hid).delete()
        s.query(db.HarnessBuild).filter(db.HarnessBuild.harness_id == hid).delete()
        s.commit()
    return {"ok": True}


def harness_runtime(hid: str, platform: str = ''):
    h = catalog.get(hid, images.custom_manifests())
    pf = platform if platform in runtime.PLATFORM_ARCH else runtime.host_platform()
    return {**runtime.status(h, pf), "dockerfile": runtime.dockerfile(h)}


def build_harness_runtime(hid: str, body: dict | None = None):
    body = {} if body is None else body
    h = catalog.get(hid, images.custom_manifests())
    pf = body.get("platform") if body.get("platform") in runtime.PLATFORM_ARCH else runtime.host_platform()

    def job(ctx):
        ctx.result = runtime.ensure(ctx, h, pf, ctx.log)
    return {"job_id": jobs.submit("build", f"Build {h.name} runtime ({pf})", job, {"harness_id": hid, "platform": pf},
                                  ref=f"rt_{hid}")}
