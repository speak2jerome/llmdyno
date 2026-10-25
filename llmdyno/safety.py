"""Panic stop: halt every benchmark activity at once.

Order matters: first cancel jobs and plans so nothing new starts, then kill the proxy containers (which cuts every
agent off from paid APIs immediately), then the agents and graders, then llama-server and any stray copy of it."""
import os
import subprocess
import time

import psutil

from . import config, db, events, jobs
from .inference import llamacpp

IS_WIN = os.name == "nt"
NOWIN = subprocess.CREATE_NO_WINDOW if IS_WIN else 0


def _docker(args, timeout=60):
    try:
        return subprocess.run(["docker", *args], capture_output=True, text=True, timeout=timeout, creationflags=NOWIN)
    except (OSError, subprocess.TimeoutExpired):
        return None


def kill_containers(role=None):
    """Remove LLMDyno containers (all roles, or one of proxy/agent/grader). Returns how many were removed."""
    flt = f"label=org.llmdyno.role={role}" if role else "label=org.llmdyno.role"
    p = _docker(["ps", "-aq", "--filter", flt])
    ids = [x for x in (p.stdout.split() if p and p.returncode == 0 else []) if x]
    if ids:
        _docker(["rm", "-f", *ids], timeout=120)
    return len(ids)


def kill_stray_llama_servers():
    """llama-server processes started by LLMDyno (matched by our port), including ones a crash left behind."""
    port = str(config.get("llama_port"))
    killed = 0
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (proc.info["name"] or "").lower()
            cmd = proc.info["cmdline"] or []
            if "llama-server" in name and port in cmd:
                proc.kill()
                killed += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return killed


def list_containers():
    p = _docker(["ps", "--filter", "label=org.llmdyno.role", "--format", "{{.Names}}\t{{.Label \"org.llmdyno.role\"}}"],
                timeout=15)
    out = []
    for line in (p.stdout.splitlines() if p and p.returncode == 0 else []):
        name, _, role = line.partition("\t")
        if name:
            out.append({"name": name, "role": role})
    return out


def active():
    with db.Session() as s:
        jobs_ = [{"id": j.id, "kind": j.kind, "title": j.title} for j in
                 s.query(db.Job).filter(db.Job.status.in_(["queued", "running"])).all()]
        plans = [{"id": p.id, "name": p.name} for p in
                 s.query(db.Plan).filter(db.Plan.status.in_(["queued", "running"])).all()]
        runs = s.query(db.Run).filter(db.Run.status.in_(["running", "grading"])).count()
        queued = s.query(db.Run).filter(db.Run.status == "queued",
                                        db.Run.plan_id.in_([p["id"] for p in plans] or [""])).count()
    return {"jobs": jobs_, "plans": plans, "runs_running": runs, "runs_queued": queued,
            "containers": list_containers(), "llama_server": llamacpp.server.running(),
            "idle": not (jobs_ or plans or runs) and not llamacpp.server.running()}


def panic(reason="panic stop from the UI"):
    t0 = time.time()
    report = {"jobs_cancelled": 0, "plans_cancelled": 0, "runs_cancelled": 0}
    # 1. nothing new may start
    with db.Session() as s:
        for j in s.query(db.Job).filter(db.Job.status.in_(["queued", "running"])).all():
            if jobs.cancel(j.id):
                report["jobs_cancelled"] += 1
            else:                      # job from a previous server process: just close it
                j.status, j.ended_at, j.detail = "cancelled", time.time(), reason
        # paused plans are not running and stay resumable
        plan_ids = []
        for p in s.query(db.Plan).filter(db.Plan.status.in_(["queued", "running"])).all():
            p.status, p.ended_at = "cancelled", time.time()
            plan_ids.append(p.id)
        report["plans_cancelled"] = len(plan_ids)
        live = s.query(db.Run).filter(db.Run.status.in_(["running", "grading"])).all()
        queued = s.query(db.Run).filter(db.Run.status == "queued", db.Run.plan_id.in_(plan_ids or [""])).all()
        run_ids = []
        for r in live + queued:
            r.status, r.stage, r.error, r.ended_at = "cancelled", "", reason, time.time()
            run_ids.append(r.id)
        report["runs_cancelled"] = len(run_ids)
        s.commit()
    from .runner import executor
    with executor._alock:
        active = list(executor._active.values())
    for a in active:
        a["own"].set()
    for pid in plan_ids:            # open plan pages update live
        executor._set_plan(pid, status="cancelled")
    for rid in run_ids:
        executor._publish_run(rid)
    # 2. cut API access, then stop agents and graders
    report["proxies_killed"] = kill_containers("proxy")
    report["containers_killed"] = kill_containers()
    # 3. free the GPU
    was_running = llamacpp.server.running()
    llamacpp.server.stop(force=True)
    report["llama_server_stopped"] = was_running
    report["stray_llama_servers_killed"] = kill_stray_llama_servers()
    report["seconds"] = round(time.time() - t0, 2)
    events.publish("plans", "update", {"panic": True})
    events.publish("system", "panic", report)
    return report
