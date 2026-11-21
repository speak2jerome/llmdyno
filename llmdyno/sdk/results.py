"""Scored results: the leaderboard, per-run rows, public-benchmark rates and exports."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Sequence, Union

from ..errors import LLMDynoError
from ._core import _as_list, _id, call, covers

__all__ = ["Results", "results", "save_weights", "sample_status", "load_sample", "unload_sample"]

@covers("GET /api/results")
def results(plans=None, *, include_sample: bool = False, correctness: float | None = None,
            instruction_following: float | None = None, quality: float | None = None,
            efficiency: float | None = None, quality_weights: dict | None = None, benchmarks=None,
            pass_threshold: float = 0.8, efficiency_ref: str = "local") -> "Results":
    """Scored results for some plans (default: every plan except the bundled sample), with every option of the
    Results page: the four weights reshape the final score (defaults 50/15/25/10); quality_weights splits code
    quality between "static", "probes" and "review"; benchmarks limits it to some benchmarks; pass_threshold is the
    correctness that counts as a pass (pass@k); efficiency_ref compares speed and cost among "local" or "all" runs."""
    ids = [_id(p) for p in _as_list(plans)]
    saved = call("settings.get_settings")
    w = dict(saved["weights"])
    for k, v in (("correctness", correctness), ("instruction_following", instruction_following),
                 ("quality", quality), ("efficiency", efficiency)):
        if v is not None:
            w[k] = v
    qw = {**saved["quality_weights"], **(quality_weights or {})}
    options = {"plan_ids": ",".join(ids), "weights": json.dumps(w), "quality_weights": json.dumps(qw),
               "benchmark_ids": ",".join(_id(b) for b in _as_list(benchmarks))}
    data = call("results.results", pass_threshold=pass_threshold, efficiency_ref=efficiency_ref,
                include_sample=include_sample or bool(ids), **options)
    return Results(data, ids, options)


class Results:
    """Scored results. print(results) shows the leaderboard; leaderboard() and runs() return rows; to_pandas(),
    to_csv() and to_json() export them; open() shows the dashboard."""

    def __init__(self, data: dict, plan_ids: Sequence[str] = (), options: dict | None = None):
        self.data, self.plan_ids = data, list(plan_ids)
        self._labels = data.get("labels") or {}
        self._options = dict(options or {"plan_ids": ",".join(self.plan_ids)})

    # -- the Results page's other views
    def cells(self) -> list:
        """One row per profile × harness × benchmark: pass rate, scores with standard deviation and 95% interval over
        iterations, time, tokens and cost (the heatmap)."""
        return [{"profile": self._name(c), "harness": self._harness(c), **c} for c in self.data.get("cells") or []]

    def reviews(self) -> list:
        """Every LLM-judge review behind these results (scores per rubric dimension, summary, issues)."""
        return list(self.data.get("reviews") or [])

    def rubric(self) -> list:
        """Average judge score per rubric dimension for each profile × harness (the rubric chart)."""
        return [{"profile": self._name(r), "harness": self._harness(r), **r} for r in self.data.get("rubric") or []]

    def agreement(self) -> dict:
        """How much the judges agree with each other (correlation per judge pair) and how much each favours its own
        model family: {"judges", "pairs", …}."""
        return dict(self.data.get("agreement") or {})

    @covers("GET /api/references/aa")
    def reference(self) -> list:
        """Each profile's Artificial Analysis coding index next to its score here (needs set_aa_key())."""
        ref = call("references.aa_reference")
        out = []
        for row in self.leaderboard():
            m = (ref.get("matches") or {}).get(row["profile_id"])
            out.append({"profile": row["profile"], "harness": row["harness"], "final": row["final"],
                        "aa_model": (m or {}).get("model"), "aa_score": (m or {}).get("score"),
                        "aa_manual": (m or {}).get("manual")})
        return out

    @covers("GET /api/results/export")
    def export(self, path: Union[str, Path, None] = None, level: str = "runs", fmt: str = "csv") -> str:
        """The Results page's export: level "runs", "cells" or "configs", fmt "csv" or "json" (with the weights and
        LLMDyno version recorded). Written to path if given; returns the text."""
        o = self._options
        d = call("results.export", plan_ids=o.get("plan_ids", ""), level=level, fmt=fmt, weights=o.get("weights", ""),
                 quality_weights=o.get("quality_weights", ""), benchmark_ids=o.get("benchmark_ids", ""))
        if path:
            Path(path).write_text(d["content"], encoding="utf-8")
        return d["content"]

    def _name(self, r):
        p = (self._labels.get("profiles") or {}).get(r["profile_id"]) or {}
        return p.get("name") or r["profile_id"]

    def _harness(self, r):
        return (self._labels.get("harnesses") or {}).get(r["harness_id"], r["harness_id"])

    def leaderboard(self) -> list:
        """One row per profile × harness, best first. Scores are 0-100."""
        rows = []
        for i, c in enumerate(self.data.get("configs") or [], 1):
            pct = lambda v: None if v is None else round(v * 100, 1)   # noqa: E731
            rows.append({"rank": i, "profile": self._name(c), "harness": self._harness(c), "final": pct(c.get("final")),
                         "correctness": pct(c.get("correctness")),
                         "instruction_following": pct(c.get("instruction_following")),
                         "quality": pct(c.get("quality")), "efficiency": pct(c.get("efficiency")),
                         "pass_at_k": pct(c.get("pass_at_k")), "runs": c.get("runs"),
                         "wall_s_total": c.get("wall_s_total"), "cost_usd_total": c.get("cost_usd_total"),
                         "decode_tps": c.get("decode_tps"), "peak_vram_mib": c.get("peak_vram_mib"),
                         "profile_id": c["profile_id"], "harness_id": c["harness_id"]})
        return rows

    def runs(self) -> list:
        """One row per run (benchmark × iteration)."""
        bl = self._labels.get("benchmarks") or {}
        out = []
        for r in self.data.get("runs") or []:
            out.append({"run_id": r["id"], "plan_id": r["plan_id"], "profile": self._name(r), "harness": self._harness(r),
                        "benchmark": (bl.get(r["benchmark_id"]) or {}).get("title", r["benchmark_id"]),
                        "benchmark_id": r["benchmark_id"], "iteration": r["iteration"],
                        "final": r.get("final"), "correctness": r.get("correctness"),
                        "instruction_following": r.get("instruction_following"), "quality": r.get("quality"),
                        "tests_passed": r.get("tests_passed"), "tests_total": r.get("tests_total"),
                        "wall_s": r.get("wall_s"), "cost_usd": r.get("cost_usd"),
                        "generated_tokens": r.get("generated_tokens"), "decode_tps": r.get("decode_tps"),
                        "ttft_s": r.get("ttft_median_s"), "peak_context_tokens": r.get("peak_context_tokens"),
                        "spill": r.get("spill_detected")})
        return out

    def public(self) -> list:
        """SWE-bench resolved rate and Aider polyglot solved rate per profile × harness (only when such runs exist)."""
        groups = {}
        for r in self.data.get("runs") or []:
            kind = "swebench" if r["benchmark_id"].startswith("swe_") else "polyglot" if r["benchmark_id"].startswith("pg_") else None
            if kind:
                g = groups.setdefault((r["profile_id"], r["harness_id"]), {"swebench": [], "polyglot": []})
                g[kind].append((r.get("correctness") or 0) >= 1)
        out = []
        for (pid, hid), g in groups.items():
            rate = lambda v: round(100 * sum(v) / len(v), 1) if v else None   # noqa: E731
            out.append({"profile": self._name({"profile_id": pid}), "harness": self._harness({"harness_id": hid}),
                        "swebench_resolved_pct": rate(g["swebench"]), "swebench_runs": len(g["swebench"]),
                        "polyglot_solved_pct": rate(g["polyglot"]), "polyglot_runs": len(g["polyglot"])})
        return out

    def best(self) -> dict | None:
        lb = self.leaderboard()
        return lb[0] if lb else None

    # -- export
    def to_pandas(self, level: str = "configs"):
        """A pandas DataFrame of the leaderboard (level="configs") or every run (level="runs")."""
        try:
            import pandas as pd
        except ImportError as e:
            raise LLMDynoError("to_pandas() needs pandas: pip install pandas") from e
        return pd.DataFrame(self.leaderboard() if level == "configs" else self.runs())

    def to_csv(self, path: Union[str, Path, None] = None, level: str = "configs") -> str:
        rows = self.leaderboard() if level == "configs" else self.runs()
        buf = io.StringIO()
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        if path:
            Path(path).write_text(buf.getvalue(), encoding="utf-8")
        return buf.getvalue()

    def to_json(self, path: Union[str, Path, None] = None) -> dict:
        from .. import __version__ as v
        out = {"llmdyno_version": v, "plans": self.plan_ids, "leaderboard": self.leaderboard(), "runs": self.runs(),
               "public": self.public(), "weights": self.data.get("weights")}
        if path:
            Path(path).write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        return out

    def open(self) -> str:
        """Open these results in the dashboard (starts the web app in the background if it is not running)."""
        from .ui import _open_ui
        q = f"?plans={','.join(self.plan_ids)}" if self.plan_ids else ""
        return _open_ui(f"/results{q}")

    # -- display
    def __str__(self):
        lb = self.leaderboard()
        if not lb:
            return "No finished runs yet."
        cols = [("rank", "#"), ("profile", "Profile"), ("harness", "Harness"), ("final", "Final"),
                ("correctness", "Correct"), ("quality", "Quality"), ("runs", "Runs"), ("wall_s_total", "Time"),
                ("cost_usd_total", "Cost")]
        fmt = {"wall_s_total": lambda v: "–" if v is None else f"{v / 60:.1f} min",
               "cost_usd_total": lambda v: "–" if v is None else f"${v:.4f}"}
        table = [[fmt.get(k, lambda v: "–" if v is None else str(v))(r.get(k)) for k, _ in cols] for r in lb]
        widths = [max(len(h), *(len(row[i]) for row in table)) for i, (_, h) in enumerate(cols)]
        line = lambda cells: "  ".join(c.ljust(w) for c, w in zip(cells, widths)).rstrip()   # noqa: E731
        out = [line([h for _, h in cols]), line(["-" * w for w in widths])] + [line(r) for r in table]
        pub = [p for p in self.public() if p["swebench_runs"] or p["polyglot_runs"]]
        if pub:
            out.append("")
            for p in pub:
                bits = []
                if p["swebench_runs"]:
                    bits.append(f"SWE-bench resolved {p['swebench_resolved_pct']}% of {p['swebench_runs']}")
                if p["polyglot_runs"]:
                    bits.append(f"polyglot solved {p['polyglot_solved_pct']}% of {p['polyglot_runs']}")
                out.append(f"{p['profile']} · {p['harness']}: " + ", ".join(bits))
        return "\n".join(out)

    def __repr__(self):
        b = self.best()
        return (f"<llmdyno.Results {len(self.leaderboard())} configs, {len(self.runs())} runs"
                + (f", best {b['profile']} · {b['harness']} {b['final']}" if b else "") + ">")

    def _repr_html_(self):
        lb = self.leaderboard()
        if not lb:
            return "<p>No finished runs yet.</p>"
        import html
        keys = ["rank", "profile", "harness", "final", "correctness", "instruction_following", "quality", "efficiency",
                "runs", "cost_usd_total"]
        head = "".join(f"<th>{html.escape(k.replace('_', ' '))}</th>" for k in keys)
        body = "".join("<tr>" + "".join(f"<td>{html.escape('' if r.get(k) is None else str(r.get(k)))}</td>" for k in keys)
                       + "</tr>" for r in lb)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


# ------------------------------------------------------------------ saved weights
@covers("POST /api/results/weights")
def save_weights(*, correctness: float | None = None, instruction_following: float | None = None,
                 quality: float | None = None, efficiency: float | None = None,
                 quality_weights: dict | None = None) -> dict:
    """Save the default score weights (what results() and the Results page start from). The four main weights are
    relative (defaults 50/15/25/10); quality_weights splits code quality between "static", "probes" and "review".
    Returns the saved {"weights", "quality_weights"}."""
    w = {k: v for k, v in (("correctness", correctness), ("instruction_following", instruction_following),
                           ("quality", quality), ("efficiency", efficiency)) if v is not None}
    body = {}
    if w:
        body["weights"] = w
    if quality_weights:
        body["quality_weights"] = dict(quality_weights)
    saved = call("results.save_weights", body=body)
    return {"weights": saved["weights"], "quality_weights": saved["quality_weights"]}


# ------------------------------------------------------------------ the bundled sample
@covers("GET /api/sample")
def sample_status() -> dict:
    """{"available", "loaded", "plan_id"} for the bundled sample results (15 configurations measured on an RTX 5080)."""
    return call("results.sample_status")


@covers("POST /api/sample")
def load_sample() -> str:
    """Load the bundled sample results into this data folder to explore the dashboard and the API without running
    anything; returns its plan id. results() leaves it out unless you pass include_sample=True or its plan id."""
    status = call("results.sample_status")
    if status["loaded"]:
        return status["plan_id"]
    return call("results.load_sample")["plan_id"]


@covers("DELETE /api/sample")
def unload_sample() -> None:
    """Remove the sample plan, its runs, reviews and profiles."""
    call("results.unload_sample")
