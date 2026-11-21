"""Scored results: the leaderboard, per-run rows, public-benchmark rates and exports."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Sequence, Union

from ..errors import LLMDynoError
from ._core import _as_list, _id, call, covers

__all__ = ["Results", "results"]

# Web API routes this module does not cover yet (see sdk/parity.py); remove each one as it gets a library call.
PENDING_ROUTES = (
    "GET /api/results/export",
    "POST /api/results/weights",
    "DELETE /api/sample",
    "GET /api/sample",
    "POST /api/sample",
)


@covers("GET /api/results")
def results(plans=None, *, include_sample: bool = False, correctness: float | None = None,
            instruction_following: float | None = None, quality: float | None = None,
            efficiency: float | None = None) -> "Results":
    """Scored results for some plans (default: every plan except the bundled sample). The four weights reshape
    the final score the way the Results page does (defaults 50/15/25/10)."""
    ids = [_id(p) for p in _as_list(plans)]
    w = dict(call("settings.get_settings")["weights"])
    for k, v in (("correctness", correctness), ("instruction_following", instruction_following),
                 ("quality", quality), ("efficiency", efficiency)):
        if v is not None:
            w[k] = v
    data = call("results.results", plan_ids=",".join(ids), weights=json.dumps(w), quality_weights="",
                include_sample=include_sample or bool(ids), benchmark_ids="")
    return Results(data, ids)


class Results:
    """Scored results. print(results) shows the leaderboard; leaderboard() and runs() return rows; to_pandas(),
    to_csv() and to_json() export them; open() shows the dashboard."""

    def __init__(self, data: dict, plan_ids: Sequence[str] = ()):
        self.data, self.plan_ids = data, list(plan_ids)
        self._labels = data.get("labels") or {}

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
