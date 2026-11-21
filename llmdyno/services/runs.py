"""Runs: details, transcripts, files, logs, GPU telemetry, cancel, retry and re-grade."""
import shutil
import time
from pathlib import Path
from .. import db, jobs
from ..runner import executor, metrics
from .. import errors
from ._common import _get, file_download


SKIP = {"__pycache__", ".pytest_cache", "node_modules", ".git", ".ruff_cache", ".mypy_cache", "htmlcov"}


def get_run(rid: str):
    r = _get(db.Run, rid)
    reviews = []
    with db.Session() as s:
        reviews = [db.row(x) for x in s.query(db.Review).filter(db.Review.run_id == rid).all()]
    q = r.get("quality") or {}
    static = (q.get("static") or {})
    return {**r, "quality": {**q, "static": {k: v for k, v in static.items() if k != "files"},
                             "files": static.get("files")}, "reviews": reviews}


def cancel_run(rid: str):
    if not executor.cancel_run(rid):
        raise errors.http(409, "run is not active")
    return {"ok": True}


def retry_run(rid: str):
    r = _get(db.Run, rid)
    if r["status"] in ("queued", "running", "grading"):
        raise errors.http(409, "run is still active")
    plan = _get(db.Plan, r["plan_id"])
    with db.Session() as s:
        obj = s.get(db.Run, rid)
        assert obj is not None              # checked by _get() above
        obj.status, obj.error, obj.stage, obj.metrics, obj.quality = "queued", "", "", {}, {}
        obj.correctness = obj.instruction_following = obj.wall_s = obj.cost_usd = None
        s.commit()
    job = executor.start_plan(r["plan_id"]) if plan["status"] not in ("running", "queued") else None
    return {"ok": True, "job_id": job}


def regrade_run(rid: str):
    r = _get(db.Run, rid)
    if r["status"] != "done":
        raise errors.http(409, "only finished runs can be graded again")
    return {"job_id": jobs.submit("validate", f"Re-grade {r['benchmark_id']}", executor.regrade_run, {"run_id": rid},
                                  ref=rid)}


def run_transcript(rid: str, start: int = 0, limit: int = 20000):
    r = _get(db.Run, rid)
    lines = metrics.read_jsonl(Path(r["dir"]) / "transcript.jsonl") if r["dir"] else []
    return {"start": start, "total": len(lines), "events": lines[start:start + limit]}


def run_proxy(rid: str):
    r = _get(db.Run, rid)
    recs = metrics.read_jsonl(Path(r["dir"]) / "proxy.jsonl") if r["dir"] else []
    keep = ("seq", "ts", "t_end", "wall_s", "ttft_s", "finish_reason", "usage_norm", "timings", "n_tool_calls",
            "tool_names", "cost_usd", "status", "budget_blocked", "api", "model")
    return [{k: x.get(k) for k in keep} for x in recs if "usage_norm" in x or "timings" in x or x.get("budget_blocked")]


def run_files(rid: str, root: str = 'workspace'):
    r = _get(db.Run, rid)
    if root not in ("workspace", "home") or not r["dir"]:
        raise errors.http(400, "unknown root")
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


def run_file(rid: str, path: str, root: str = 'workspace'):
    r = _get(db.Run, rid)
    if root not in ("workspace", "home") or not r["dir"]:
        raise errors.http(400, "unknown root")
    base = (Path(r["dir"]) / root).resolve()
    f = (base / path).resolve()
    if base not in f.parents or not f.is_file():
        raise errors.http(404, "file not found")
    if f.stat().st_size > 2 * 2**20:
        return f"(file is {f.stat().st_size / 2**20:.1f} MB; too large to show)"
    data = f.read_bytes()
    if b"\0" in data[:4096]:
        return "(binary file)"
    return data.decode("utf-8", "replace")


def run_log(rid: str, name: str):
    r = _get(db.Run, rid)
    allowed = {"server"} | {f"{k}_stage{i}.log" for k in ("stdout", "stderr") for i in range(1, 21)}
    if name not in allowed or not r["dir"]:
        raise errors.http(400, "unknown log")
    if name == "server":
        f = Path(r["dir"]).parent / f"server_{r['profile_id']}.log"
    else:
        f = Path(r["dir"]) / name
    if not f.exists():
        return ""
    data = f.read_bytes()[-400_000:]
    return data.decode("utf-8", "replace")


def run_gpu(rid: str, max_points: int = 600):
    r = _get(db.Run, rid)
    if not r["dir"] or not r["started_at"]:
        return []
    f = Path(r["dir"]).parent / f"gpu_{r['profile_id']}.jsonl"
    end = (r["ended_at"] or time.time()) + 2
    rows = [x for x in metrics.read_jsonl(f) if r["started_at"] - 2 <= x.get("ts", 0) <= end]
    step = max(1, len(rows) // max_points)
    return rows[::step]


def run_download(rid: str):
    r = _get(db.Run, rid)
    if not r["dir"] or not Path(r["dir"]).exists():
        raise errors.http(404, "run folder not found")
    import tempfile
    tmp = Path(tempfile.mkdtemp())
    archive = shutil.make_archive(str(tmp / rid), "zip", r["dir"], "workspace")
    return file_download(archive, f"{rid}-workspace.zip", "application/zip")
