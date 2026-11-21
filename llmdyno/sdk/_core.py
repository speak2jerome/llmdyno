"""Pieces every SDK area uses: the data folder, the base Handle class, background jobs, printing and the route map.

Conventions for SDK modules (one per area, mirroring llmdyno/services):
* talk to LLMDyno only through call("area.function", **kwargs), never through the database or engine modules;
* mark each public function or method with @covers("METHOD /api/path") for every web API route it gives access to,
  so tests/test_parity.py can prove the library can do everything the web app does;
* never give a public name the name of a llmdyno submodule (jobs, profiles, benchmarks, judge, config, …): the
  package exports these names lazily and a submodule import would replace them.
"""
from __future__ import annotations

import copy
import sys
import time
from pathlib import Path
from typing import Any

from ..errors import LLMDynoError
from ._backend import LocalBackend, backend, call

TERMINAL = ("done", "failed", "cancelled", "paused")

# ------------------------------------------------------------------ route coverage
ROUTES: dict[str, list[str]] = {}


def covers(*routes: str):
    """Declare that the decorated SDK function, method or property gives access to these web API routes,
    written as "GET /api/runs/{rid}" (the path exactly as the server declares it)."""
    def deco(fn):
        target = fn.fget if isinstance(fn, property) else fn
        name = f"{target.__module__}.{target.__qualname__}"
        for r in routes:
            method, _, path = r.partition(" ")
            if not path.startswith("/"):
                raise ValueError(f"covers() takes 'METHOD /path', got {r!r}")
            ROUTES.setdefault(f"{method.upper()} {path}", []).append(name)
        return fn
    return deco


# ------------------------------------------------------------------ data folder
def init(data_dir=None) -> Path:
    """Open (and create if needed) a data folder. Optional: without it LLMDyno uses LLMDYNO_DATA or the default
    folder (./data in a git checkout, otherwise %LOCALAPPDATA%\\LLMDyno, ~/Library/Application Support/LLMDyno or
    ~/.local/share/llmdyno). Call it again with another folder to switch."""
    b = backend()
    if not isinstance(b, LocalBackend):
        raise LLMDynoError("init() opens a local data folder; this session is connected to a remote LLMDyno")
    return b.start(data_dir)


def data_dir() -> Path:
    """The data folder in use (models, runs, database, keys)."""
    b = backend()
    if isinstance(b, LocalBackend):
        from .. import config
        return config.DATA
    return Path(call("settings.get_settings")["data_dir"])


# ------------------------------------------------------------------ small helpers
def _say(quiet: bool, msg: str) -> None:
    if not quiet:
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:            # a console code page without · or …
            enc = getattr(sys.stdout, "encoding", None) or "ascii"
            print(msg.encode(enc, "replace").decode(enc), flush=True)


def _as_list(x) -> list:
    if x is None:
        return []
    if isinstance(x, (str, Handle)):
        return [x]
    return list(x)


def _id(x) -> str:
    return x.id if isinstance(x, Handle) else str(x)


# ------------------------------------------------------------------ handles
class Handle:
    """Base of the SDK's objects (Profile, Plan, Job, …): an id plus the latest data LLMDyno returned for it.

    h["field"] and h.get("field") read that data, to_dict() copies it, refresh() fetches it again. Two handles are
    equal when they are the same kind of thing with the same id."""

    _get_op = ""             # the service that returns this object's data
    _id_arg = "id"           # that service's id parameter

    def __init__(self, data: dict | str):
        if isinstance(data, str):
            self._id, self._d = data, None
        else:
            self._d = dict(data)
            self._id = self._d["id"]

    @property
    def id(self) -> str:
        return self._id

    @property
    def _data(self) -> dict:
        if self._d is None:
            self.refresh()
        return self._d

    def refresh(self):
        """Fetch the latest data; returns self."""
        self._d = call(self._get_op, **{self._id_arg: self._id})
        return self

    def to_dict(self) -> dict:
        """Everything LLMDyno knows about this object, as a plain dict (a copy)."""
        return copy.deepcopy(self._data)

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __eq__(self, other):
        return type(other) is type(self) and other.id == self.id

    def __hash__(self):
        return hash((type(self).__name__, self.id))

    def __repr__(self):
        return f"<llmdyno.{type(self).__name__} {self.id}>"


# ------------------------------------------------------------------ background jobs
class Job(Handle):
    """A background task: a download, image build, plan, review or import. Most SDK calls wait for their job;
    the ones with wait=False return it so you can follow it yourself."""

    _get_op, _id_arg = "system.get_job", "jid"

    @property
    def status(self) -> str:
        """queued, running, done, failed, cancelled or paused (fetched fresh)."""
        return self.refresh()._d["status"]

    @property
    def title(self) -> str:
        return self._data.get("title") or ""

    @property
    def progress(self) -> float | None:
        """0-1 when the job reports it (fetched fresh)."""
        return self.refresh()._d.get("progress")

    @property
    def result(self) -> dict:
        return self.refresh()._d.get("result") or {}

    @property
    def log(self) -> str:
        """The tail of the job's log (fetched fresh)."""
        return self.refresh()._d.get("log") or ""

    @covers("POST /api/jobs/{jid}/cancel")
    def cancel(self) -> None:
        """Stop the job (a download keeps what it has, a plan keeps finished runs)."""
        call("system.cancel_job", jid=self.id)

    def wait(self, quiet: bool = False, verbose: bool = False, every_s: float = 2.0) -> dict:
        """Block until the job ends, printing its progress, and return its result. Ctrl+C cancels the job;
        a failed or cancelled job raises LLMDynoError."""
        seen, last_detail, last_print = 0, None, 0.0
        j = self.refresh()._d
        try:
            while True:
                j = self.refresh()._d
                log = j.get("log") or ""
                if verbose and not quiet:
                    if len(log) < seen:
                        seen = 0                                   # the stored log keeps a tail only
                    for line in log[seen:].splitlines():
                        _say(False, "    " + line)
                    seen = len(log)
                detail = j.get("detail") or ""
                if not quiet and detail and detail != last_detail and time.time() - last_print >= every_s:
                    pct = f"{int((j.get('progress') or 0) * 100):>3}% " if j.get("progress") else ""
                    _say(False, f"  {pct}{j['title']}: {detail}")
                    last_detail, last_print = detail, time.time()
                if j["status"] in TERMINAL:
                    break
                time.sleep(0.5)
        except KeyboardInterrupt:
            _say(quiet, f"  cancelling {j.get('title') or self.id} …")
            self.cancel()
            self._drain()
            raise
        if j["status"] == "failed":
            tail = "\n".join(ln for ln in (j.get("log") or "").splitlines()[-12:] if ln.strip())
            raise LLMDynoError(f"{j['title']} failed: {j.get('detail')}\n{tail}".rstrip())
        if j["status"] in ("cancelled", "paused"):
            raise LLMDynoError(f"{j['title']} was {j['status']}")
        return j.get("result") or {}

    def _drain(self, timeout_s: float = 120) -> None:
        """Wait (quietly) for a cancelled job to actually stop."""
        end = time.time() + timeout_s
        while time.time() < end:
            if self.refresh()._d["status"] in TERMINAL:
                return
            time.sleep(0.5)

    def __repr__(self):
        d = self._d or {}
        return f"<llmdyno.Job {self.id} {d.get('title', '')!r} {d.get('status', '')}>".replace("  ", " ")


@covers("GET /api/jobs/{jid}")
def job(job_id: str) -> Job:
    """A background job by id."""
    return Job(job_id).refresh()


def _run_job(op: str, quiet: bool = False, verbose: bool = False, **kwargs) -> dict:
    """Start a job-returning service and wait for it."""
    r = call(op, **kwargs)
    return Job(r["job_id"]).wait(quiet=quiet, verbose=verbose)
