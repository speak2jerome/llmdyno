"""Runs: details, transcripts, workspace files, logs, GPU telemetry, cancel, retry and re-grade."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Union

from ..errors import LLMDynoError
from ._core import Handle, Job, call, covers

if TYPE_CHECKING:  # pragma: no cover
    from .plans import Plan

__all__ = ["Run", "Transcript", "run"]


class Transcript(list):
    """A run's transcript: every event LLMDyno's proxy recorded between the agent and the model, in order. The list
    holds the raw events ("request", "block_start", "delta", "response"); the methods give the usual views."""

    def _pairs(self):
        reqs = {e.get("seq"): e for e in self if e.get("ev") == "request"}
        return [(reqs.get(e.get("seq")), e) for e in self if e.get("ev") == "response"]

    def turns(self) -> list:
        """One dict per model call: the new messages sent ("messages": tool results, the user prompt), the reply's
        blocks (thinking, text, tool calls), why it stopped, token usage, time to first token, time and cost."""
        out = []
        for req, resp in self._pairs():
            out.append({"seq": resp.get("seq"), "messages": (req or {}).get("new") or [], "blocks": resp.get("blocks") or [],
                        "finish": resp.get("finish"), "usage": resp.get("usage") or {}, "ttft_s": resp.get("ttft_s"),
                        "wall_s": resp.get("wall_s"), "cost_usd": resp.get("cost_usd"), "t": resp.get("t")})
        return out

    def tool_calls(self) -> list:
        """Every tool call the agent made: {"seq", "id", "name", "args" (parsed), "result" (what the tool returned)}."""
        results = {}
        for e in self:
            if e.get("ev") == "request":
                for m in e.get("new") or []:
                    for b in m.get("blocks") or []:
                        if b.get("type") == "tool_result":
                            results[b.get("id")] = b.get("text")
        calls = []
        for _, resp in self._pairs():
            for b in resp.get("blocks") or []:
                if b.get("type") == "tool_call":
                    try:
                        args = json.loads(b.get("args") or "{}")
                    except (TypeError, ValueError):
                        args = b.get("args")
                    calls.append({"seq": resp.get("seq"), "id": b.get("id"), "name": b.get("name"), "args": args,
                                  "result": results.get(b.get("id"))})
        return calls

    def thinking(self) -> list:
        """The model's reasoning text for each call that had any."""
        return ["".join(b.get("text") or "" for b in resp.get("blocks") or [] if b.get("type") == "thinking")
                for _, resp in self._pairs()
                if any(b.get("type") == "thinking" for b in resp.get("blocks") or [])]

    def final_text(self) -> str:
        """What the agent said last (its closing message)."""
        pairs = self._pairs()
        if not pairs:
            return ""
        return "".join(b.get("text") or "" for b in pairs[-1][1].get("blocks") or [] if b.get("type") == "text")

    def usage(self) -> dict:
        """Totals over the run: model calls, input / cached / output / reasoning tokens, cost and model time."""
        tot = {"calls": 0, "input": 0, "cached": 0, "output": 0, "reasoning": 0, "cost_usd": 0.0, "wall_s": 0.0}
        for _, resp in self._pairs():
            tot["calls"] += 1
            u = resp.get("usage") or {}
            for k in ("input", "cached", "output", "reasoning"):
                tot[k] += u.get(k) or 0
            tot["cost_usd"] += resp.get("cost_usd") or 0
            tot["wall_s"] += resp.get("wall_s") or 0
        return tot

    def to_pandas(self):
        """One row per model call (turns()) as a pandas DataFrame, with usage spread into columns."""
        try:
            import pandas as pd
        except ImportError as e:
            raise LLMDynoError("to_pandas() needs pandas: pip install pandas") from e
        rows = []
        for t in self.turns():
            row = {k: t[k] for k in ("seq", "finish", "ttft_s", "wall_s", "cost_usd", "t")}
            row.update({f"tokens_{k}": v for k, v in (t["usage"] or {}).items()})
            row["tool_calls"] = sum(1 for b in t["blocks"] if b.get("type") == "tool_call")
            rows.append(row)
        return pd.DataFrame(rows)

    def __repr__(self):
        u = self.usage()
        return f"<llmdyno.Transcript {len(self)} events, {u['calls']} model calls, {len(self.tool_calls())} tool calls>"


class Run(Handle):
    """One benchmark run: a profile × harness × benchmark × iteration, with its scores, transcript and workspace."""

    _get_op, _id_arg = "runs.get_run", "rid"

    @property
    def status(self) -> str:
        """queued, running, grading, done, failed, cancelled or skipped (fetched fresh)."""
        return self.refresh()._d["status"]

    @property
    def correctness(self) -> float | None:
        return self._data.get("correctness")

    @property
    def reviews(self) -> list:
        """LLM-judge reviews of this run."""
        return list(self._data.get("reviews") or [])

    @covers("GET /api/runs/{rid}")
    def refresh(self) -> "Run":
        return super().refresh()

    def plan(self) -> "Plan":
        from .plans import Plan
        return Plan(self._data["plan_id"])

    @covers("GET /api/runs/{rid}/transcript")
    def transcript(self, start: int = 0, limit: int = 20000) -> Transcript:
        """Everything the agent and the model said, as a Transcript (turns(), tool_calls(), thinking(), usage())."""
        return Transcript(call("runs.run_transcript", rid=self.id, start=start, limit=limit)["events"])

    @covers("GET /api/runs/{rid}/proxy")
    def requests(self) -> list:
        """Each model request through LLMDyno's proxy: tokens, timings, time to first token, cost, finish reason."""
        return call("runs.run_proxy", rid=self.id)

    @covers("GET /api/runs/{rid}/files")
    def files(self, home: bool = False) -> list:
        """Files the agent left in its workspace (home=True: the agent's home folder, with its config and sessions):
        [{"path", "size", "mtime"}]."""
        return call("runs.run_files", rid=self.id, root="home" if home else "workspace")

    @covers("GET /api/runs/{rid}/file")
    def read_file(self, path: str, home: bool = False) -> str:
        """A workspace file's text (or a note when it is binary or larger than 2 MB)."""
        return call("runs.run_file", rid=self.id, path=path, root="home" if home else "workspace")

    @covers("GET /api/runs/{rid}/log")
    def log(self, stage: int = 1, stream: str = "stdout") -> str:
        """The harness's output for one stage (stream "stdout" or "stderr"); the last 400 kB."""
        return call("runs.run_log", rid=self.id, name=f"{stream}_stage{int(stage)}.log")

    @covers("GET /api/runs/{rid}/log")
    def server_log(self) -> str:
        """The llama-server log of the plan's local model (empty for cloud runs)."""
        return call("runs.run_log", rid=self.id, name="server")

    @covers("GET /api/runs/{rid}/gpu")
    def gpu(self, max_points: int = 600) -> list:
        """GPU telemetry samples taken while the run was going (utilisation, VRAM, power, temperature)."""
        return call("runs.run_gpu", rid=self.id, max_points=max_points)

    @covers("GET /api/runs/{rid}/download")
    def download(self, path: Union[str, Path, None] = None) -> Path:
        """Save the run's workspace as a zip (default: <run id>-workspace.zip in the current folder)."""
        d = call("runs.run_download", rid=self.id)
        dest = Path(path or d["filename"]).expanduser()
        if d.get("path"):
            shutil.move(d["path"], dest)
        else:
            dest.write_bytes(d["content"])
        return dest

    @covers("POST /api/runs/{rid}/cancel")
    def cancel(self) -> None:
        call("runs.cancel_run", rid=self.id)

    @covers("POST /api/runs/{rid}/retry")
    def retry(self) -> Job | None:
        """Queue the run again (its old results are cleared). Restarts the plan if it had stopped and returns that
        plan's Job; follow it with watch() or plan().wait()."""
        jid = call("runs.retry_run", rid=self.id).get("job_id")
        self.refresh()
        return Job(jid) if jid else None

    @covers("POST /api/runs/{rid}/regrade")
    def regrade(self, wait: bool = True, quiet: bool = False) -> Union["Run", Job]:
        """Grade the finished workspace again (after fixing a grader, say) without re-running the agent."""
        job = Job(call("runs.regrade_run", rid=self.id)["job_id"])
        if not wait:
            return job
        job.wait(quiet=quiet)
        return self.refresh()

    def __repr__(self):
        d = self._d or {}
        return (f"<llmdyno.Run {self.id} {d.get('benchmark_id', '')} {d.get('status', '')}"
                + (f" correctness {d['correctness']:.2f}" if d.get("correctness") is not None else "") + ">")


def run(run_id: str) -> Run:
    """A run by id (Results.runs() rows and Plan.runs() carry run ids)."""
    return Run(run_id).refresh()
