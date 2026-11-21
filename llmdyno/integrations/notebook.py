"""Jupyter: rich tables for Results, Plan and Run (no extra needed), a live panel for a running plan and progress bars
("llmdyno[notebook]": ipywidgets, tqdm).

    plan = llmdyno.bench(qwen, "suite_quick", wait=False)
    plan.live()                    # progress, the current run, finished runs with scores, GPU, updating live
"""
from __future__ import annotations

import html
import threading

from . import require
from .plot import COMPONENT_COLORS, PALETTE

__all__ = ["results_html", "plan_html", "run_html", "LivePanel", "progress_bar"]

_STYLE = ("<style>.llmdyno-t{border-collapse:collapse;font:12px system-ui,sans-serif}"
          ".llmdyno-t th{text-align:left;padding:4px 8px;border-bottom:1px solid #ccc;font-weight:600}"
          ".llmdyno-t td{padding:3px 8px;border-bottom:1px solid #eee;white-space:nowrap}"
          ".llmdyno-bar{display:inline-block;height:9px;border-radius:2px;vertical-align:middle}</style>")
STATUS_COLORS = {"done": "#12a594", "failed": "#e5484d", "cancelled": "#a17a4c", "skipped": "#a17a4c",
                 "running": "#3e8ef7", "grading": "#8e4ec6", "queued": "#888"}


def _esc(v) -> str:
    return html.escape("" if v is None else str(v))


def _bar(value, color: str, width: int = 90) -> str:
    """A score (0-100) as a small coloured bar with its number."""
    if value is None:
        return "–"
    w = max(1, int(width * min(max(value, 0), 100) / 100))
    return f'<span class="llmdyno-bar" style="width:{w}px;background:{color}"></span> {value:.1f}'


def _table(rows: list, cols: list) -> str:
    """cols: (key, title, kind) with kind "text", "score" (0-100 bar), "status", "money", "minutes"."""
    head = "".join(f"<th>{_esc(t)}</th>" for _, t, _ in cols)
    body = []
    for r in rows:
        cells = []
        for k, _, kind in cols:
            v = r.get(k)
            if kind == "score":
                cells.append(_bar(v, COMPONENT_COLORS.get(k, PALETTE[0])))
            elif kind == "status":
                cells.append(f'<span style="color:{STATUS_COLORS.get(v, "#444")}">●</span> {_esc(v)}')
            elif kind == "money":
                cells.append("–" if v is None else f"${v:.4f}")
            elif kind == "minutes":
                cells.append("–" if v is None else f"{v / 60:.1f} min")
            else:
                cells.append(_esc(v))
        body.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    return f'{_STYLE}<table class="llmdyno-t"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'


def results_html(results) -> str:
    lb = results.leaderboard()
    if not lb:
        return "<p>No finished runs yet.</p>"
    return _table(lb, [("rank", "#", "text"), ("profile", "Profile", "text"), ("harness", "Harness", "text"),
                       ("final", "Final", "score"), ("correctness", "Correctness", "score"),
                       ("instruction_following", "Instructions", "score"), ("quality", "Quality", "score"),
                       ("efficiency", "Efficiency", "score"), ("runs", "Runs", "text"),
                       ("wall_s_total", "Time", "minutes"), ("cost_usd_total", "Cost", "money")])


def plan_html(d: dict) -> str:
    counts = ", ".join(f"{k} {v}" for k, v in (d.get("counts") or {}).items())
    runs = [{**r, "correctness": None if r.get("correctness") is None else r["correctness"] * 100}
            for r in d.get("runs") or []]
    head = (f"<p><b>{_esc(d.get('name'))}</b> &nbsp; <span style='color:{STATUS_COLORS.get(d.get('status'), '#444')}'>"
            f"{_esc(d.get('status'))}</span> &nbsp; {_esc(counts)}</p>")
    return head + _table(runs[:200], [("benchmark_id", "Benchmark", "text"), ("profile_id", "Profile", "text"),
                                      ("harness_id", "Harness", "text"), ("iteration", "#", "text"),
                                      ("status", "Status", "status"), ("correctness", "Correctness", "score"),
                                      ("wall_s", "Time", "minutes"), ("cost_usd", "Cost", "money")])


def run_html(d: dict) -> str:
    m = d.get("metrics") or {}
    rows = [{"k": "Status", "v": d.get("status")}, {"k": "Benchmark", "v": d.get("benchmark_id")},
            {"k": "Profile", "v": d.get("profile_id")}, {"k": "Harness", "v": d.get("harness_id")},
            {"k": "Correctness", "v": d.get("correctness")},
            {"k": "Tests", "v": f"{m.get('tests_passed')}/{m.get('tests_total')}" if m.get("tests_total") else None},
            {"k": "Time", "v": None if d.get("wall_s") is None else f"{d['wall_s'] / 60:.1f} min"},
            {"k": "Cost", "v": None if d.get("cost_usd") is None else f"${d['cost_usd']:.4f}"},
            {"k": "Generated tokens", "v": m.get("generated_tokens")}, {"k": "Decode speed", "v": m.get("decode_tps")},
            {"k": "Error", "v": d.get("error") or None}]
    return _table([r for r in rows if r["v"] not in (None, "")], [("k", _esc(d.get("id")), "text"), ("v", "", "text")])


def progress_bar(total: int, desc: str):
    """A tqdm bar (notebook-aware) when tqdm is installed, else None."""
    try:
        from tqdm.auto import tqdm
    except ImportError:
        return None
    return tqdm(total=total, desc=desc, unit="run", leave=True)


class LivePanel:
    """A widget that follows a plan as it runs: progress, the latest events, finished runs with their scores."""

    def __init__(self, plan):
        widgets = require("ipywidgets", "notebook", "Plan.live()")
        self.plan = plan
        d = plan._get()
        total = len(d.get("runs") or [])
        self.bar = widgets.IntProgress(value=0, min=0, max=max(total, 1), description="Runs",
                                       layout=widgets.Layout(width="420px"))
        self.status = widgets.HTML()
        self.gpu = widgets.HTML()
        self.table = widgets.HTML(plan_html(d))
        self.box = widgets.VBox([widgets.HBox([self.bar, self.status]), self.gpu, self.table])
        self._done = {r["id"] for r in d.get("runs") or [] if r["status"] in ("done", "failed", "cancelled", "skipped")}
        self.bar.value = len(self._done)
        self._set_status(d["status"])
        self._thread = threading.Thread(target=self._follow, daemon=True, name=f"llmdyno-live-{plan.id}")
        self._thread.start()

    def _set_status(self, status: str):
        color = STATUS_COLORS.get(status, "#444")
        self.status.value = f"<span style='color:{color}'>● {_esc(status)}</span>"

    def _follow(self):
        from ..sdk.live import RUN_FINISHED, watch
        try:
            for ev in watch(self.plan):
                if ev.kind == "gpu" and isinstance(ev.data, dict):
                    d = ev.data
                    self.gpu.value = (f"<small>GPU {d.get('util', d.get('gpu_util', '–'))}% · "
                                      f"VRAM {d.get('vram_used_mib', '–')} MiB</small>")
                elif ev.kind == "run" and ev.status in RUN_FINISHED and ev.run_id not in self._done:
                    self._done.add(ev.run_id)
                    self.bar.value = len(self._done)
                    self.table.value = plan_html(self.plan._get())
                elif ev.kind == "plan":
                    self._set_status(ev.status or "")
            final = self.plan._get()
            self._set_status(final["status"])
            self.table.value = plan_html(final)
        except Exception as e:  # noqa: BLE001 - the panel reports instead of dying silently
            self.status.value = f"<span style='color:#e5484d'>watch stopped: {_esc(e)}</span>"

    def _repr_mimebundle_(self, **kwargs):
        return self.box._repr_mimebundle_(**kwargs)

    def _ipython_display_(self):
        from IPython.display import display
        display(self.box)
