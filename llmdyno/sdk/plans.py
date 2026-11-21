"""Plans: profiles × harnesses × benchmarks × iterations, checked first, then run in the background."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Sequence, Union

from ..errors import LLMDynoError, PreflightError
from ._core import Handle, Job, _as_list, _say, call, covers
from .profiles import Profile, profile

if TYPE_CHECKING:  # pragma: no cover
    from .results import Results

__all__ = ["Plan", "bench", "preflight", "list_plans", "plan"]

def _plan_body(models, benchmarks, harnesses, iterations, name, options):
    ids = [profile(m).id for m in _as_list(models)]
    if not ids:
        raise LLMDynoError("pass at least one model (a Profile, or a profile name or id)")
    return {"name": name or "", "profile_ids": ids, "harness_ids": _as_list(harnesses),
            "benchmark_ids": _as_list(benchmarks), "iterations": iterations,
            "options": {k: v for k, v in options.items() if v is not None}}


@covers("POST /api/plans/preflight")
def preflight(models, benchmarks: Union[str, Sequence[str]] = "suite_quick",
              harnesses: Union[str, Sequence[str]] = "pi", *, iterations: int = 1, **options) -> dict:
    """What bench() would check before starting: blocking problems, warnings, and time and cost estimates."""
    return call("plans.plan_preflight", body=_plan_body(models, benchmarks, harnesses, iterations, None, options))


@covers("POST /api/plans")
def bench(models: Union[Profile, str, Sequence[Union[Profile, str]]],
          benchmarks: Union[str, Sequence[str]] = "suite_quick", harnesses: Union[str, Sequence[str]] = "pi", *,
          iterations: int = 1, name: str | None = None, budget_usd: float | None = None, quality: bool = True,
          timeout_multiplier: float | None = None, cloud_concurrency: int | None = None, allow_spill: bool = False,
          acknowledge_risks: bool = False, wait: bool = True, quiet: bool = False,
          on_event=None, auto_log=None) -> Union["Results", "Plan"]:
    """Run models × harnesses × benchmarks × iterations and return the scored Results.

    models: Profiles (from cloud_model / local_model) or profile names. benchmarks: benchmark or suite ids
    (see list_benchmarks() and list_suites()); harnesses: pi, opencode, codex, qwen-code, crush, aider, mini-swe-agent.
    budget_usd caps this plan's cloud spend on top of each provider's own cap. Local models share the GPU one at a time;
    cloud runs go in parallel. The plan is checked first and PreflightError lists anything that blocks it; danger
    warnings (spill, out of memory, …) need acknowledge_risks=True. wait=False returns the running Plan instead;
    on_event(ev) gets every live Event while it runs (see watch()). auto_log sends the results on when the plan
    finishes: "mlflow", "wandb", "langfuse", "otel", a list of them, or {"mlflow": {"experiment": "x"}, …}."""
    options = {"budget_usd": budget_usd, "quality": quality, "timeout_multiplier": timeout_multiplier,
               "cloud_concurrency": cloud_concurrency, "allow_spill": allow_spill or None}
    body = _plan_body(models, benchmarks, harnesses, iterations, name, options)
    pf = call("plans.plan_preflight", body=body)
    if not pf["ok"]:
        raise PreflightError([b["text"] for b in pf["blocking"]], [w["text"] for w in pf["warnings"]], pf)
    risky = [w["text"] for w in pf["warnings"] if w.get("ack")]
    if risky and not acknowledge_risks:
        raise PreflightError(risky + ["pass acknowledge_risks=True to run anyway (results will be flagged)"],
                             [w["text"] for w in pf["warnings"]], pf)
    for w in pf["warnings"]:
        _say(quiet, f"  {w['level']}: {w['text']}")
    est = pf["estimate"]
    _say(quiet, f"Plan: {pf['n_runs']} run(s), about {est['minutes']:.0f} min"
                + (f", about ${est['cost_usd']:.2f} in API costs" if est.get("cost_usd") else ""))
    created = call("plans.create_plan", body={**body, "start": True, "acknowledge_risks": acknowledge_risks})
    p = Plan(created["plan_id"], created.get("job_id"))
    if not wait:
        return p
    res = p.wait(quiet=quiet, on_event=on_event)
    if auto_log:
        from ..integrations.tracking import auto_log as send
        send(res, auto_log)
    return res


class Plan(Handle):
    """A benchmark plan: its runs, live status, and results once it finishes. name, status and runs() are read
    fresh each time."""

    _get_op, _id_arg = "plans.get_plan", "pid"

    def __init__(self, plan_id: str, job_id: str | None = None):
        super().__init__(plan_id)
        self._job = job_id

    def _get(self) -> dict:
        return self.refresh()._d

    @covers("GET /api/plans/{pid}")
    def refresh(self) -> "Plan":
        return super().refresh()

    @property
    def name(self) -> str:
        return self._get()["name"]

    @property
    def status(self) -> str:
        """queued, running, paused, done, cancelled or failed."""
        return self._get()["status"]

    @property
    def job(self) -> Job | None:
        """The background job running this plan, if it has one."""
        jid = self._job or (self._get().get("job") or {}).get("id")
        return Job(jid) if jid else None

    def runs(self) -> list:
        """Every run with its status, scores and timing (dicts; run(id) or get_runs() give Run objects)."""
        return self._get().get("runs") or []

    def get_runs(self) -> list:
        """Every run as a Run object (transcript, files, logs, retry, …)."""
        from .runs import Run
        return [Run(r["id"]) for r in self.runs()]

    @covers("POST /api/plans/{pid}/retry")
    def retry(self, statuses=("failed", "cancelled"), wait: bool = True, quiet: bool = False, on_event=None):
        """Run the failed and cancelled runs again (or those with the given statuses) and, with wait=True, wait for
        the plan and return its Results; otherwise return how many runs were queued."""
        r = call("plans.retry_plan", pid=self.id, body={"statuses": list(statuses)})
        self._job = r.get("job_id")
        _say(quiet, f"Retrying {r['requeued']} run(s)")
        return self.wait(quiet=quiet, on_event=on_event) if wait else r["requeued"]

    @covers("PATCH /api/plans/{pid}")
    def rename(self, name: str) -> "Plan":
        self._d = call("plans.rename_plan", pid=self.id, body={"name": name})
        return self

    @covers("DELETE /api/plans/{pid}")
    def delete(self, files: bool = True) -> None:
        """Delete the plan, its runs and reviews; files=True also deletes the run folders (workspaces, logs)."""
        call("plans.delete_plan", pid=self.id, delete_files=files)

    def __repr__(self):
        d = self._get()
        return f"<llmdyno.Plan {d['name']!r} {d['status']} {d.get('counts')}>"

    def wait(self, quiet: bool = False, on_event=None, transcript: bool = False, progress: bool | None = None) -> "Results":
        """Block until the plan stops, printing each run as it finishes, then return its Results. on_event(ev) is
        called for every live Event (see watch(); transcript=True adds agent events). progress shows a tqdm bar
        (default: when tqdm is installed and the output is a terminal or notebook). Ctrl+C cancels the plan."""
        from .live import RUN_FINISHED, watch
        labels = _labels()
        printed: dict[str, str] = {}
        bar = _progress(self, quiet, progress)
        say = (lambda q, msg: bar.write(msg)) if bar is not None else _say
        try:
            for ev in watch(self, transcript=transcript, gpu=on_event is not None):
                if on_event is not None:
                    on_event(ev)
                if ev.kind == "run" and ev.status in RUN_FINISHED and printed.get(ev.run_id) != ev.status:
                    printed[ev.run_id] = ev.status          # a finished run can be updated again (quality scores)
                    say(quiet, "  " + _run_line(ev.data, labels))
                    if bar is not None:
                        bar.update(1)
        except KeyboardInterrupt:
            _say(quiet, "  cancelling the plan (finished runs are kept) …")
            call("plans.cancel_plan", pid=self.id)
            job = (self._get().get("job") or {}).get("id")
            if job:
                Job(job)._drain()
            raise
        finally:
            if bar is not None:
                bar.close()
        d = self._get()
        _say(quiet, f"Plan {d['status']}: {d.get('counts')}")
        return self.results()

    def results(self, **weights) -> "Results":
        from .results import results
        return results(self, **weights)

    @covers("POST /api/plans/{pid}/cancel")
    def cancel(self) -> None:
        call("plans.cancel_plan", pid=self.id)

    @covers("POST /api/plans/{pid}/pause")
    def pause(self) -> None:
        call("plans.pause_plan", pid=self.id)

    @covers("POST /api/plans/{pid}/resume")
    def resume(self, wait: bool = True, quiet: bool = False, on_event=None):
        call("plans.resume_plan", pid=self.id)
        return self.wait(quiet=quiet, on_event=on_event) if wait else self

    @covers("GET /api/plans/{pid}/swebench-predictions")
    def swebench_predictions(self, path: Union[str, Path, None] = None) -> str:
        """The plan's SWE-bench patches in the official predictions JSONL format (written to path if given)."""
        body = call("plans.swebench_predictions", pid=self.id)["content"]
        if path:
            Path(path).write_text(body, encoding="utf-8")
        return body

    def open(self) -> str:
        """Open this plan in the dashboard (starts the web app in the background if it is not running)."""
        from .ui import _open_ui
        return _open_ui(f"/plans/{self.id}")

    def live(self):
        """A Jupyter widget that follows the plan as it runs (progress, finished runs, GPU); needs
        "llmdyno[notebook]". Display it as the last expression of a cell."""
        from ..integrations.notebook import LivePanel
        return LivePanel(self)

    def _repr_html_(self):
        from ..integrations.notebook import plan_html
        return plan_html(self._get())


@covers("GET /api/plans")
def list_plans() -> list:
    """Every plan in the data folder, newest first."""
    return [Plan(p["id"]) for p in call("plans.list_plans")]


def plan(plan_id: str) -> Plan:
    """A plan by id."""
    return Plan(plan_id).refresh()


def _progress(plan, quiet, progress):
    """A tqdm bar over the plan's runs when wanted and available."""
    import sys
    if quiet or progress is False:
        return None
    if progress is None:
        interactive = hasattr(sys.stdout, "isatty") and sys.stdout.isatty() or "ipykernel" in sys.modules
        if not interactive:
            return None
    from ..integrations.notebook import progress_bar
    d = plan._get()
    bar = progress_bar(len(d.get("runs") or []), d.get("name") or plan.id)
    if bar is not None:
        bar.update(sum(1 for r in d.get("runs") or [] if r["status"] in ("done", "failed", "cancelled", "skipped")))
    return bar


def _labels() -> dict:
    """Display names for profiles, harnesses and benchmarks."""
    return {"profiles": {p["id"]: {"name": p["name"]} for p in call("profiles.list_profiles")},
            "harnesses": {h["id"]: h["name"] for h in call("harnesses.list_harnesses")},
            "benchmarks": {b["id"]: {"title": b.get("title", b["id"])} for b in call("benchmarks.list_benchmarks")}}


def _run_line(r, labels):
    prof = (labels["profiles"].get(r["profile_id"]) or {}).get("name", r["profile_id"])
    bench_title = (labels["benchmarks"].get(r["benchmark_id"]) or {}).get("title", r["benchmark_id"])
    h = labels["harnesses"].get(r["harness_id"], r["harness_id"])
    if r["status"] != "done":
        why = f": {r['error'][:140]}" if r.get("error") else ""
        return f"{r['status']:<9} {bench_title} · {prof} · {h}{why}"
    corr = r.get("correctness")
    mins = (r.get("wall_s") or 0) / 60
    cost = f" · ${r['cost_usd']:.4f}" if r.get("cost_usd") else ""
    return f"done      {bench_title} · {prof} · {h}: correctness {corr:.2f} in {mins:.1f} min{cost}"
