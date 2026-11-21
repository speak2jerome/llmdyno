"""System specs, dependencies and setup actions, GPU usage, cleanup, panic stop and background jobs."""
from .. import db, jobs
from ..harnesses import images
from ..inference import llamacpp
from ..system import deps
from ..system import specs as sysspecs
from .. import errors
from ._common import _build_harness


def get_specs(refresh: bool = False):
    s = sysspecs.detect(force=refresh)
    return {**s, "shared_gpu_mib": sysspecs.shared_gpu_usage_mib() if refresh else None}


def get_deps(refresh: bool = False):
    return deps.check(force=refresh)


def dep_action(dep_id: str, body: dict | None = None):
    body = {} if body is None else body
    action = body.get("action")
    if action == "start_docker":
        deps.start_docker_desktop()
        return {"ok": True, "message": "Docker Desktop is starting; this takes about a minute."}
    if action == "repair_docker":
        moved = deps.repair_docker_start()
        return {"ok": True, "message": "Docker Desktop is restarting; give it a minute."
                + (f" Moved aside: {', '.join(moved)}." if moved else "")}
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
    if action == "install_swebench":
        from . import imports as external_api
        return external_api.install_swebench_harness()
    if action == "build_polyglot":
        from . import imports as external_api
        return external_api.build_polyglot_image()
    if action.startswith("build_harness_"):
        hid = action.removeprefix("build_harness_")
        return {"job_id": _build_harness(hid)}
    raise errors.http(400, f"unknown action {action}")


def cleanup_containers():
    return {"removed": sandbox_cleanup()}


def sandbox_cleanup():
    from ..runner import sandbox
    return sandbox.cleanup_stale()


def system_gpu():
    return sysspecs.gpu_usage()


def system_active():
    """What a panic stop would halt right now; shown in its confirmation dialog."""
    from .. import safety
    return safety.active()


def system_panic():
    from .. import safety
    return safety.panic()


def list_jobs(active: bool = False, limit: int = 100, kind: str | None = None):
    with db.Session() as s:
        q = s.query(db.Job)
        if active:
            q = q.filter(db.Job.status.in_(["queued", "running"]))
        if kind:
            q = q.filter(db.Job.kind == kind)
        return [jobs.job_dict(j) for j in q.order_by(db.Job.created_at.desc()).limit(min(limit, 500)).all()]


def get_job(jid: str):
    with db.Session() as s:
        j = s.get(db.Job, jid)
        if not j:
            raise errors.http(404, "job not found")
        d = jobs.job_dict(j)
        d["log"] = j.log
        return d


def cancel_job(jid: str):
    if not jobs.cancel(jid):
        raise errors.http(409, "job is not active")
    return {"ok": True}


def clear_jobs():
    with db.Session() as s:
        n = s.query(db.Job).filter(db.Job.status.in_(["done", "failed", "cancelled", "interrupted"])).delete()
        s.commit()
    return {"removed": n}
