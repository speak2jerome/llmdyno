"""Scored results: the leaderboard, per-run rows, public-benchmark rates and exports."""
from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Sequence, Union

from ._core import _as_list, _id, call, covers

__all__ = ["Results", "results", "save_weights", "sample_status", "load_sample", "unload_sample",
           "load_results_from_hub"]

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
    LEVELS = ("configs", "runs", "cells", "reviews", "rubric", "public")

    def rows(self, level: str = "configs") -> list:
        """The rows of one table: configs (the leaderboard), runs, cells, reviews, rubric or public."""
        views = {"configs": self.leaderboard, "runs": self.runs, "cells": self.cells, "reviews": self.reviews,
                 "rubric": self.rubric, "public": self.public}
        if level not in views:
            raise ValueError(f"level is one of {', '.join(views)}, not {level!r}")
        return views[level]()

    def to_pandas(self, level: str = "configs"):
        """A pandas DataFrame of one table (see rows()): the leaderboard by default."""
        from ..integrations.data import frame
        return frame(self.rows(level), "pandas")

    def to_polars(self, level: str = "configs"):
        """A polars DataFrame of one table (see rows()); needs "llmdyno[data]"."""
        from ..integrations.data import frame
        return frame(self.rows(level), "polars")

    def to_parquet(self, path: Union[str, Path], level: str = "runs") -> Path:
        """Write one table to a Parquet file; needs "llmdyno[data]"."""
        from ..integrations.data import to_parquet
        return to_parquet(self.rows(level), path)

    # -- tracking and tracing
    def log_to_mlflow(self, experiment: str = "llmdyno", tracking_uri: str | None = None,
                      transcripts: bool = True) -> list:
        """One MLflow run per configuration: settings as params, scores as metrics, results and transcripts as
        artifacts. Returns the MLflow run ids; needs "llmdyno[mlflow]"."""
        from ..integrations.mlflow import log_to_mlflow
        return log_to_mlflow(self, experiment=experiment, tracking_uri=tracking_uri, transcripts=transcripts)

    def log_to_wandb(self, project: str = "llmdyno", entity: str | None = None, name: str | None = None,
                     mode: str | None = None, dir: str | None = None, transcripts: bool = True) -> str:
        """The leaderboard, configurations and runs as W&B tables, transcripts as an artifact (mode="offline"
        works without an account). Returns the W&B run id; needs "llmdyno[wandb]"."""
        from ..integrations.wandb import log_to_wandb
        return log_to_wandb(self, project=project, entity=entity, name=name, mode=mode, dir=dir,
                            transcripts=transcripts)

    def log_to_langfuse(self, client=None, public_key: str | None = None, secret_key: str | None = None,
                        host: str | None = None) -> list:
        """Each run as a Langfuse trace with one generation per model request and the grader scores. Returns the
        trace ids; needs "llmdyno[langfuse]"."""
        from ..integrations.langfuse import log_to_langfuse
        return log_to_langfuse(self, client=client, public_key=public_key, secret_key=secret_key, host=host)

    def to_otel(self, tracer_provider=None, endpoint: str | None = None, headers: dict | None = None,
                service_name: str = "llmdyno") -> int:
        """Each run as an OpenTelemetry trace (GenAI semantic conventions) for any OTLP backend. Returns the number
        of spans; needs "llmdyno[otel]"."""
        from ..integrations.otel import export_otel
        return export_otel(self, tracer_provider=tracer_provider, endpoint=endpoint, headers=headers,
                           service_name=service_name)

    def push_to_hub(self, repo_id: str, private: bool = True, token: str | None = None) -> str:
        """Publish these results as a Hugging Face dataset (Parquet tables, a dataset card, the full results JSON);
        private unless you say otherwise. Returns its URL; needs "llmdyno[hub]"."""
        from ..integrations.hub import push_results
        return push_results(self, repo_id, private=private, token=token)

    def to_inspect_log(self, path: Union[str, Path], task: str = "llmdyno") -> Path:
        """Write these results as an Inspect AI eval log (one sample per run) to open with `inspect view`;
        needs "llmdyno[inspect]"."""
        from ..integrations.inspect_eval import to_eval_log
        return to_eval_log(self, path, task=task)

    @property
    def plot(self):
        """Charts like the dashboard's: results.plot.leaderboard(), .heatmap(), .pareto(), .radar(), .tokens();
        needs "llmdyno[plot]"."""
        from ..integrations.plot import ResultsPlot
        return ResultsPlot(self)

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
        from ..integrations.notebook import results_html
        return results_html(self)


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


def load_results_from_hub(repo_id: str, revision: str | None = None, token: str | None = None) -> "Results":
    """Results someone published with Results.push_to_hub(); needs "llmdyno[hub]"."""
    from ..integrations.hub import load_results
    return load_results(repo_id, revision=revision, token=token)
