# pyright: strict, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false
"""Live progress: watch() a plan, run or job as it works, the same events the dashboard shows."""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Iterator

from ._backend import backend
from ._core import TERMINAL, Handle, call, covers

__all__ = ["Event", "watch"]

RUN_FINISHED = ("done", "failed", "cancelled", "skipped")
_KINDS = {("plan", "run"): "run", ("plan", "plan"): "plan", ("plan", "gpu"): "gpu", ("run", "status"): "run",
          ("run", "transcript"): "transcript", ("run", "proxy"): "proxy", ("job", "update"): "job",
          ("job", "log"): "log"}


@dataclass(frozen=True)
class Event:
    """Something that happened while LLMDyno worked.

    kind is one of:
      "run"         a run changed state; data is the run summary (id, status, stage, correctness, wall_s, cost_usd, …)
      "plan"        the plan changed state; data has its status
      "gpu"         a GPU telemetry sample while a local model runs (utilisation, VRAM, power, …)
      "transcript"  one agent event in a run's transcript: {"i": index, "ev": event} (watch(..., transcript=True))
      "proxy"       one model request through LLMDyno's proxy: tokens, cost, latency (watch(..., transcript=True))
      "job"         a background job's progress: status, progress (0-1), detail
      "log"         one line of a job's log
    topic is where it came from (plan:<id>, run:<id>, job:<id>), ts the time it happened."""

    kind: str
    topic: str
    data: Any
    ts: float

    @property
    def status(self) -> str | None:
        return self.data.get("status") if isinstance(self.data, dict) else None

    @property
    def run_id(self) -> str | None:
        if self.topic.startswith("run:"):
            return self.topic[4:]
        return self.data.get("id") if self.kind == "run" and isinstance(self.data, dict) else None

    @property
    def finished(self) -> bool:
        """A run that reached done / failed / cancelled / skipped, or a plan or job that stopped."""
        if self.kind == "run":
            return self.status in RUN_FINISHED
        return self.kind in ("plan", "job") and self.status in TERMINAL


def _target(x: Any) -> tuple[str, str]:
    """(kind, id) for a Plan / Job / other handle or an id string."""
    from .plans import Plan
    from ._core import Job
    if isinstance(x, Plan):
        return "plan", x.id
    if isinstance(x, Job):
        return "job", x.id
    xid = x.id if isinstance(x, Handle) else str(x)
    for kind in ("plan", "run", "job"):
        if xid.startswith(kind + "_"):
            return kind, xid
    raise ValueError(f"watch() takes a plan, run or job (or its id), not {x!r}")


@covers("WS /ws")
def watch(target: Any, *, transcript: bool = False, gpu: bool = True, timeout: float | None = None,
          poll_s: float = 2.0, _stop: threading.Event | None = None) -> Iterator[Event]:
    """Iterate over what happens to a plan, run or job until it stops:

        plan = llmdyno.bench(qwen, "suite_quick", wait=False)
        for ev in llmdyno.watch(plan):
            if ev.kind == "run" and ev.finished:
                print(ev.data["benchmark_id"], ev.status, ev.data["correctness"])

    Events come live from work running in this process (bench(), review(), downloads, …) and from a remote LLMDyno.
    Work running elsewhere, such as in a separate web server on this machine, is followed by polling every poll_s
    seconds (run and plan changes only). transcript=True adds every agent event and model request; gpu=False drops
    the GPU samples. timeout (seconds) stops waiting early."""
    kind, tid = _target(target)
    q: queue.Queue[Event] = queue.Queue()
    runs: set[str] = set()
    last: dict[str, str] = {}                   # id -> last status reported (live or polled)
    polled: set[str] = set()                    # ids whose last status came from a poll, not a live event

    def snapshot():
        if kind == "plan":
            d = call("plans.get_plan", pid=tid)
            for r in d.get("runs") or []:
                runs.add(r["id"])
            return d
        if kind == "run":
            return call("runs.get_run", rid=tid)
        return call("system.get_job", jid=tid)

    def wanted(topic: str) -> bool:
        if kind == "plan":
            return topic == f"plan:{tid}" or (transcript and topic.startswith("run:") and topic[4:] in runs)
        return topic == f"{kind}:{tid}"

    def on_msg(msg: Any):
        area = msg["topic"].split(":", 1)[0]
        ev_kind = _KINDS.get((area, msg["kind"]))
        if ev_kind is None or (ev_kind == "gpu" and not gpu):
            return
        if kind == "plan" and ev_kind == "run" and area == "run":
            return                              # the plan topic already carries every run change
        if ev_kind in ("transcript", "proxy") and not transcript:
            return
        if ev_kind == "run" and isinstance(msg["data"], dict):
            rid = msg["data"].get("id")
            if transcript and sub is not None and rid not in runs:
                sub.add(f"run:{rid}")
            runs.add(rid)
        q.put(Event(ev_kind, msg["topic"], msg["data"], msg["ts"]))

    sub = backend().subscribe(on_msg, wanted, [f"{kind}:{tid}"])
    deadline = None if timeout is None else time.time() + timeout
    try:
        first = snapshot()
        if kind == "plan":
            for r in first.get("runs") or []:
                last[r["id"]] = r["status"]
                if transcript and sub is not None:
                    sub.add(f"run:{r['id']}")
        last[tid] = first["status"]
        if _stopped(kind, first):
            yield Event(kind, f"{kind}:{tid}", first, time.time())
            return
        next_poll = time.time() + poll_s
        while True:
            if _stop is not None and _stop.is_set():
                return
            wait = max(0.05, min(next_poll, deadline or next_poll) - time.time())
            try:
                ev = q.get(timeout=wait)
            except queue.Empty:
                ev = None
            if ev is not None:
                key = ev.run_id if ev.kind == "run" else tid if ev.kind in ("plan", "job") else None
                if key is not None and ev.status is not None:
                    if key in polled and last.get(key) == ev.status:
                        polled.discard(key)
                        continue                # a poll got there first and already reported this status
                    polled.discard(key)
                    last[key] = ev.status
                yield ev
                if ev.kind in ("plan", "job", "run") and key == tid and ev.status in (TERMINAL + RUN_FINISHED):
                    d = snapshot()              # a plan is over once its job has stopped too
                    if _stopped(kind, d):
                        return
            if deadline is not None and time.time() >= deadline:
                return
            if time.time() >= next_poll:
                next_poll = time.time() + poll_s
                d = snapshot()
                if kind == "plan":
                    for r in d.get("runs") or []:
                        if last.get(r["id"]) != r["status"]:
                            last[r["id"]] = r["status"]
                            polled.add(r["id"])
                            yield Event("run", f"plan:{tid}", r, time.time())
                if last.get(tid) != d["status"]:
                    last[tid] = d["status"]
                    polled.add(tid)
                    yield Event(kind, f"{kind}:{tid}", d, time.time())
                if _stopped(kind, d):
                    return
    finally:
        if sub is not None:
            sub.close()


def _stopped(kind: str, d: dict[str, Any]) -> bool:
    if kind == "plan":
        job = d.get("job") or {}
        return d["status"] in TERMINAL and job.get("status") in (*TERMINAL, None)
    if kind == "run":
        return d["status"] in RUN_FINISHED
    return d["status"] in TERMINAL
