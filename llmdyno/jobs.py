"""Background jobs: persisted in the jobs table, executed by a thread pool, streamed over the event bus.

A job function receives a JobContext and may call ctx.progress(), ctx.log() and ctx.check() (raises Cancelled).
Jobs in the same exclusive group (for example "gpu") run one at a time; others wait in order."""
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor

from . import db, events

MAX_LOG = 200_000
_pool = ThreadPoolExecutor(max_workers=12, thread_name_prefix="job")
_cancel: dict[str, threading.Event] = {}
_groups: dict[str, threading.Lock] = {}
_glock = threading.Lock()


class Cancelled(Exception):
    pass


def job_dict(j):
    d = db.row(j)
    d["log_tail"] = (j.log or "")[-4000:]
    d.pop("log", None)
    return d


class JobContext:
    def __init__(self, job_id, params):
        self.id = job_id
        self.params = params
        self.cancel_event = _cancel[job_id]
        self._log = []
        self._last_flush = 0.0
        self._progress = 0.0
        self._detail = ""
        self.result = {}
        self.cancel_status = "cancelled"     # a download sets "paused" so the activity list says what happened

    def check(self):
        if self.cancel_event.is_set():
            raise Cancelled()

    @property
    def cancelled(self):
        return self.cancel_event.is_set()

    def log(self, line):
        line = str(line).rstrip("\n")
        self._log.append(line)
        events.publish(f"job:{self.id}", "log", line)
        self._flush()

    def progress(self, fraction=None, detail=None):
        if fraction is not None:
            self._progress = max(0.0, min(1.0, float(fraction)))
        if detail is not None:
            self._detail = detail
        self._flush()

    def _flush(self, force=False):
        now = time.time()
        if not force and now - self._last_flush < 0.5:
            return
        self._last_flush = now
        with db.Session() as s:
            j = s.get(db.Job, self.id)
            if not j:
                return
            j.progress, j.detail = self._progress, self._detail
            if self._log:
                j.log = ((j.log or "") + "\n".join(self._log) + "\n")[-MAX_LOG:]
                self._log = []
            s.commit()
            d = job_dict(j)
        events.publish("jobs", "update", d)
        events.publish(f"job:{self.id}", "update", d)


def _set(job_id, **fields):
    with db.Session() as s:
        j = s.get(db.Job, job_id)
        for k, v in fields.items():
            setattr(j, k, v)
        s.commit()
        d = job_dict(j)
    events.publish("jobs", "update", d)
    events.publish(f"job:{job_id}", "update", d)
    return d


def _group_lock(name):
    with _glock:
        return _groups.setdefault(name, threading.Lock())


def submit(kind, title, fn, params=None, ref="", group=None):
    """Queue fn(ctx) and return the job id immediately."""
    job_id = db.new_id("job")
    with db.Session() as s:
        s.add(db.Job(id=job_id, kind=kind, title=title, ref=ref, params=params or {}, status="queued"))
        s.commit()
    _cancel[job_id] = threading.Event()
    events.publish("jobs", "created", {"id": job_id, "kind": kind, "title": title, "ref": ref, "status": "queued"})

    def runner():
        lock = _group_lock(group) if group else None
        if lock:
            if not lock.acquire(blocking=False):
                _set(job_id, detail=f"waiting for {group}")
                while not lock.acquire(timeout=1):
                    if _cancel[job_id].is_set():
                        _set(job_id, status="cancelled", ended_at=time.time(), detail="cancelled before start")
                        return
        ctx = JobContext(job_id, params or {})
        try:
            _set(job_id, status="running", started_at=time.time(), detail="")
            fn(ctx)
            ctx._flush(force=True)
            _set(job_id, status="done", progress=1.0, ended_at=time.time(), result=ctx.result or {})
        except Cancelled:
            ctx._flush(force=True)
            _set(job_id, status=ctx.cancel_status, ended_at=time.time(), result=ctx.result or {})
        except Exception as e:  # noqa: BLE001 - every failure is reported on the job
            ctx.log(traceback.format_exc())
            ctx._flush(force=True)
            _set(job_id, status="failed", ended_at=time.time(), detail=f"{type(e).__name__}: {e}"[:500],
                 result=ctx.result or {})
        finally:
            if lock:
                lock.release()

    _pool.submit(runner)
    return job_id


def cancel(job_id):
    ev = _cancel.get(job_id)
    if ev:
        ev.set()
        return True
    return False


def mark_interrupted():
    """Called at startup: jobs that were running when the server stopped cannot continue."""
    with db.Session() as s:
        for j in s.query(db.Job).filter(db.Job.status.in_(["queued", "running"])).all():
            j.status, j.ended_at = "interrupted", time.time()
            j.detail = "server restarted while this job was active"
        s.commit()
