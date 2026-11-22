"""Charts of Results, the same ones the dashboard draws, with matplotlib (default) or plotly ("llmdyno[plot]").

    results.plot.leaderboard()                      # stacked score points per configuration
    results.plot.heatmap("correctness")             # configuration × benchmark
    results.plot.pareto(x="cost_usd_total")         # score against cost (or wall_s_total, decode_tps, peak_vram_mib)
    results.plot.radar()                            # judge rubric per configuration
    results.plot.tokens()                           # generated tokens per configuration
    results.plot.leaderboard(backend="plotly")

Every method returns the figure (matplotlib Figure or plotly Figure) so you can save or restyle it."""
from __future__ import annotations

import math

from . import require

__all__ = ["ResultsPlot", "PALETTE", "COMPONENT_COLORS"]

# the dashboard's chart palette (frontend/src/styles.css --c1 … --c10, light theme)
PALETTE = ["#5b5bd6", "#12a594", "#e5940e", "#e5484d", "#3e8ef7", "#8e4ec6", "#68a73d", "#d6409f", "#0894b3", "#a17a4c"]
# scores stored from 0 to 1 and shown from 0 to 100
SCORES = ("final", "correctness", "instruction_following", "quality", "efficiency", "pass_at_k",
          "consistency")
COMPONENTS = [("correctness", "Correctness"), ("instruction_following", "Instruction following"),
              ("quality", "Code quality"), ("efficiency", "Efficiency")]
COMPONENT_COLORS = dict(zip((k for k, _ in COMPONENTS), PALETTE))
AXIS_LABELS = {"cost_usd_total": "Cost (USD)", "wall_s_total": "Wall time (s)", "decode_tps": "Decode speed (tok/s)",
               "peak_vram_mib": "Peak VRAM (MiB)", "final": "Final score", "correctness": "Correctness"}


class ResultsPlot:
    """The plot accessor of a Results object (results.plot)."""

    def __init__(self, results):
        self.r = results

    # -- data
    def _label(self, c) -> str:
        return f"{self.r._name(c)} · {self.r._harness(c)}"

    def _configs(self) -> list:
        return list(self.r.data.get("configs") or [])

    def _points(self, c) -> dict:
        """Each component's points in the final score, as the leaderboard bar shows them."""
        w = self.r.data.get("weights") or {}
        total = sum(w.get(k, 0) for k, _ in COMPONENTS if c.get(k) is not None) or 1
        return {k: (c.get(k) or 0) * 100 * w.get(k, 0) / total for k, _ in COMPONENTS}

    @staticmethod
    def _mpl():
        require("matplotlib", "plot", "results.plot")
        import matplotlib.pyplot as plt
        return plt

    @staticmethod
    def _go():
        return require("plotly.graph_objects", "plot", "results.plot with backend='plotly'")

    # -- charts
    def leaderboard(self, backend: str = "matplotlib"):
        """Stacked bars: each configuration's final score split into its weighted components, best on top."""
        rows = list(reversed(self._configs()))
        labels = [self._label(c) for c in rows]
        pts = [self._points(c) for c in rows]
        if backend == "plotly":
            go = self._go()
            fig = go.Figure([go.Bar(name=name, y=labels, x=[p[k] for p in pts], orientation="h",
                                    marker_color=COMPONENT_COLORS[k]) for k, name in COMPONENTS])
            fig.update_layout(barmode="stack", title="Leaderboard", xaxis_title="Points (of 100)",
                              height=max(300, 28 * len(rows) + 120))
            return fig
        plt = self._mpl()
        fig, ax = plt.subplots(figsize=(10, max(3, 0.42 * len(rows) + 1)))
        left = [0.0] * len(rows)
        for k, name in COMPONENTS:
            vals = [p[k] for p in pts]
            ax.barh(labels, vals, left=left, color=COMPONENT_COLORS[k], label=name)
            left = [a + b for a, b in zip(left, vals)]
        for i, total in enumerate(left):
            ax.text(total + 0.6, i, f"{total:.1f}", va="center", fontsize=8)
        ax.set_xlim(0, 105)
        ax.set_xlabel("Points (of 100)")
        ax.set_title("Leaderboard")
        ax.legend(loc="lower right", fontsize=8)
        fig.tight_layout()
        return fig

    def heatmap(self, metric: str = "final", backend: str = "matplotlib"):
        """Configuration × benchmark grid of one metric (final, correctness, quality, pass_rate, …), 0-100."""
        cells = self.r.data.get("cells") or []
        configs = self._configs()
        keys = [(c["profile_id"], c["harness_id"]) for c in configs]
        bl = (self.r._labels.get("benchmarks") or {})
        benches = sorted({c["benchmark_id"] for c in cells})
        grid = [[None] * len(benches) for _ in keys]
        for c in cells:
            k = (c["profile_id"], c["harness_id"])
            if k in keys and c.get(metric) is not None:
                grid[keys.index(k)][benches.index(c["benchmark_id"])] = round(c[metric] * 100, 1)
        ylabels = [self._label(c) for c in configs]
        xlabels = [(bl.get(b) or {}).get("title", b) for b in benches]
        if backend == "plotly":
            go = self._go()
            fig = go.Figure(go.Heatmap(z=grid, x=xlabels, y=ylabels, colorscale="Viridis", zmin=0, zmax=100,
                                       text=grid, texttemplate="%{text}"))
            fig.update_layout(title=f"{metric} by benchmark", height=max(300, 28 * len(keys) + 160))
            return fig
        plt = self._mpl()
        fig, ax = plt.subplots(figsize=(max(6, 1.3 * len(benches) + 4), max(3, 0.42 * len(keys) + 1.5)))
        data = [[math.nan if v is None else v for v in row] for row in grid]
        im = ax.imshow(data, cmap="viridis", vmin=0, vmax=100, aspect="auto")
        ax.set_xticks(range(len(xlabels)), xlabels, rotation=30, ha="right", fontsize=8)
        ax.set_yticks(range(len(ylabels)), ylabels, fontsize=8)
        for i, row in enumerate(grid):
            for j, v in enumerate(row):
                if v is not None:
                    ax.text(j, i, f"{v:.0f}", ha="center", va="center", fontsize=7, color="white" if v < 60 else "black")
        fig.colorbar(im, ax=ax)
        ax.set_title(f"{metric} by benchmark")
        fig.tight_layout()
        return fig

    def pareto(self, x: str = "cost_usd_total", y: str = "final", backend: str = "matplotlib"):
        """Score against a cost (cost_usd_total, wall_s_total, peak_vram_mib, …): the best trade-offs are top left."""
        pts = [(c.get(x), (c.get(y) or 0) * 100 if y in SCORES else c.get(y),
                self._label(c)) for c in self._configs() if c.get(x) is not None and c.get(y) is not None]
        if backend == "plotly":
            go = self._go()
            fig = go.Figure(go.Scatter(x=[p[0] for p in pts], y=[p[1] for p in pts], text=[p[2] for p in pts],
                                       mode="markers+text", textposition="top center", marker_color=PALETTE[0]))
            fig.update_layout(title=f"{AXIS_LABELS.get(y, y)} vs {AXIS_LABELS.get(x, x)}",
                              xaxis_title=AXIS_LABELS.get(x, x), yaxis_title=AXIS_LABELS.get(y, y))
            return fig
        plt = self._mpl()
        fig, ax = plt.subplots(figsize=(9, 6))
        ax.scatter([p[0] for p in pts], [p[1] for p in pts], color=PALETTE[0])
        for px, py, label in pts:
            ax.annotate(label, (px, py), fontsize=7, xytext=(4, 4), textcoords="offset points")
        ax.set_xlabel(AXIS_LABELS.get(x, x))
        ax.set_ylabel(AXIS_LABELS.get(y, y))
        ax.set_title(f"{AXIS_LABELS.get(y, y)} vs {AXIS_LABELS.get(x, x)}")
        fig.tight_layout()
        return fig

    def radar(self, top: int = 6, backend: str = "matplotlib"):
        """Average judge score per rubric dimension (0-10) for the best configurations that have reviews."""
        rubric = {(r["profile_id"], r["harness_id"]): r for r in self.r.data.get("rubric") or []}
        rows = [c for c in self._configs() if (c["profile_id"], c["harness_id"]) in rubric][:top]
        if not rows:
            raise ValueError("no judge reviews in these results; run llmdyno.review() first")
        dims = [k for k in rubric[(rows[0]["profile_id"], rows[0]["harness_id"])]
                if k not in ("profile_id", "harness_id", "profile", "harness")]
        series = [(self._label(c), [rubric[(c["profile_id"], c["harness_id"])].get(d) or 0 for d in dims]) for c in rows]
        if backend == "plotly":
            go = self._go()
            fig = go.Figure([go.Scatterpolar(r=vals + vals[:1], theta=dims + dims[:1], name=name, fill="toself",
                                             line_color=PALETTE[i % len(PALETTE)]) for i, (name, vals) in enumerate(series)])
            fig.update_layout(title="Judge rubric", polar={"radialaxis": {"range": [0, 10]}})
            return fig
        plt = self._mpl()
        angles = [2 * math.pi * i / len(dims) for i in range(len(dims))]
        fig, ax = plt.subplots(figsize=(7, 7), subplot_kw={"projection": "polar"})
        for i, (name, vals) in enumerate(series):
            ax.plot(angles + angles[:1], vals + vals[:1], color=PALETTE[i % len(PALETTE)], label=name)
            ax.fill(angles + angles[:1], vals + vals[:1], color=PALETTE[i % len(PALETTE)], alpha=0.08)
        ax.set_xticks(angles, dims, fontsize=8)
        ax.set_ylim(0, 10)
        ax.set_title("Judge rubric")
        ax.legend(loc="upper right", bbox_to_anchor=(1.35, 1.1), fontsize=7)
        fig.tight_layout()
        return fig

    def tokens(self, backend: str = "matplotlib"):
        """Generated tokens per configuration (summed over its runs)."""
        totals = {}
        for r in self.r.data.get("runs") or []:
            k = (r["profile_id"], r["harness_id"])
            totals[k] = totals.get(k, 0) + ((r.get("metrics") or {}).get("generated_tokens") or r.get("generated_tokens")
                                            or 0)
        rows = [c for c in self._configs() if (c["profile_id"], c["harness_id"]) in totals]
        labels = [self._label(c) for c in rows]
        vals = [totals[(c["profile_id"], c["harness_id"])] for c in rows]
        if backend == "plotly":
            go = self._go()
            fig = go.Figure(go.Bar(x=vals, y=labels, orientation="h", marker_color=PALETTE[1]))
            fig.update_layout(title="Generated tokens", yaxis={"autorange": "reversed"})
            return fig
        plt = self._mpl()
        fig, ax = plt.subplots(figsize=(10, max(3, 0.42 * len(rows) + 1)))
        ax.barh(labels, vals, color=PALETTE[1])
        ax.invert_yaxis()
        ax.set_xlabel("Generated tokens")
        ax.set_title("Generated tokens")
        fig.tight_layout()
        return fig
