"""Plans: preflight, creation, status, pause / resume / cancel / retry, rename and delete."""
import json
import shutil
from .. import config, db, events, jobs
from ..runner import executor
import re
from ..benchmarks import swebench
from .. import errors
from ._common import _get, download


def _plan_spec(body):
    spec = {"name": (body.get("name") or "").strip(), "profile_ids": body.get("profile_ids") or [],
            "harness_ids": body.get("harness_ids") or [], "benchmark_ids": body.get("benchmark_ids") or [],
            "iterations": int(body.get("iterations") or 1), "options": body.get("options") or {}}
    if not 1 <= spec["iterations"] <= 20:
        raise errors.http(400, "iterations must be 1-20")
    return spec


def plan_preflight(body: dict):
    return executor.preflight(_plan_spec(body))


def create_plan(body: dict):
    spec = _plan_spec(body)
    pf = executor.preflight(spec)
    if not pf["ok"]:
        raise errors.http(409, "; ".join(b["text"] for b in pf["blocking"]))
    unacked = [w for w in pf["warnings"] if w.get("ack")]
    if unacked and not body.get("acknowledge_risks"):
        raise errors.http(428, "acknowledge the danger warnings first: " + "; ".join(w["text"] for w in unacked))
    spec["preflight"] = pf
    pid = executor.create_plan(spec)
    job = executor.start_plan(pid) if body.get("start", True) else None
    return {"plan_id": pid, "job_id": job}


def _plan_out(p, with_runs = False):
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


def list_plans():
    with db.Session() as s:
        plans = [db.row(p) for p in s.query(db.Plan).order_by(db.Plan.created_at.desc()).all()]
    return [_plan_out(p) for p in plans]


def get_plan(pid: str):
    return _plan_out(_get(db.Plan, pid), with_runs=True)


def pause_plan(pid: str):
    p = _get(db.Plan, pid)
    if p["status"] not in ("running", "queued"):
        raise errors.http(409, f"plan is {p['status']}")
    executor._set_plan(pid, status="paused")
    return {"ok": True, "message": "Runs already in progress finish; no new runs start."}


def resume_plan(pid: str):
    p = _get(db.Plan, pid)
    if p["status"] in ("running", "queued"):
        raise errors.http(409, "plan is already running")
    with db.Session() as s:
        if not s.query(db.Run).filter(db.Run.plan_id == pid, db.Run.status == "queued").count():
            raise errors.http(409, "no queued runs left; use retry to rerun failed ones")
    return {"job_id": executor.start_plan(pid)}


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


def retry_plan(pid: str, body: dict | None = None):
    body = {} if body is None else body
    p = _get(db.Plan, pid)
    if p["status"] in ("running", "queued"):
        raise errors.http(409, "wait for the plan to stop or pause it first")
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
        raise errors.http(409, "nothing to retry")
    return {"requeued": n, "job_id": executor.start_plan(pid)}


def rename_plan(pid: str, body: dict):
    _get(db.Plan, pid)
    if not (body.get("name") or "").strip():
        raise errors.http(400, "name is required")
    executor._set_plan(pid, name=body["name"].strip())
    return _get(db.Plan, pid)


def delete_plan(pid: str, delete_files: bool = True):
    p = _get(db.Plan, pid)
    if p["status"] in ("running", "queued"):
        raise errors.http(409, "cancel the plan before deleting it")
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


def swebench_predictions(pid: str):
    with db.Session() as s:
        runs = [db.row(r) for r in s.query(db.Run).filter(db.Run.plan_id == pid, db.Run.status == "done").all()]
        profs = {p.id: p.name for p in s.query(db.Profile).all()}
    runs = [r for r in runs if r["benchmark_id"].startswith("swe_")]
    if not runs:
        raise errors.http(404, "this plan has no finished SWE-bench runs")
    for r in runs:
        r["label"] = re.sub(r"[^A-Za-z0-9_.-]+", "-", f"{profs.get(r['profile_id'], r['profile_id'])}__{r['harness_id']}")
    lines = swebench.predictions(runs)
    body = "".join(json.dumps(x) + "\n" for x in lines)
    return download(body, f"{pid}-swebench-predictions.jsonl", "application/x-ndjson")
