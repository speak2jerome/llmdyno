"""Inspect AI interop ("llmdyno[inspect]").

Run LLMDyno benchmarks as an Inspect task: each sample is one benchmark, the solver runs it with a real harness in
LLMDyno's sandbox, and the scorer reports its hidden-test correctness:

    from inspect_ai import eval
    task = llmdyno.inspect_task(["t0_smoke_cli", "t5_bugfix_semver"], profile="Qwen 27B 32k", harness="pi")
    eval(task, model="none/none")          # the model is the profile's; Inspect's own model is not called

Bring an Inspect dataset into LLMDyno as benchmarks (each sample's answer is checked in answer.txt):

    suite = llmdyno.import_inspect_samples(my_dataset, prefix="gsm8k")

And write LLMDyno results as an Inspect log, to open in `inspect view`:

    results.to_inspect_log("logs/llmdyno.eval")
"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path

from .. import __version__
from ..errors import LLMDynoError
from . import require

__all__ = ["inspect_task", "import_inspect_samples", "to_eval_log"]

_components: dict = {}


def _registered():
    """The solver and scorer, registered with Inspect once (its registry wants module-level definitions)."""
    if _components:
        return _components
    require("inspect_ai", "inspect", "Inspect AI interop")
    from inspect_ai.model import ModelOutput
    from inspect_ai.scorer import Score, mean, scorer, stderr
    from inspect_ai.solver import solver

    from .. import lib

    @solver(name="llmdyno/agent")
    def llmdyno_agent(profile: str, harness: str = "pi", options: dict | None = None):
        async def solve(state, generate):
            bid = state.metadata["benchmark_id"]
            res = await asyncio.to_thread(lib.bench, profile, bid, harness, quiet=True, **(options or {}))
            rows = res.runs()
            run = rows[0] if rows else {}
            state.metadata["llmdyno"] = run
            text = ""
            if run.get("run_id"):
                try:
                    text = lib.run(run["run_id"]).transcript().final_text()
                except LLMDynoError:
                    text = ""
            state.output = ModelOutput.from_content(model="llmdyno", content=text or f"run {run.get('run_id')}")
            state.completed = True
            return state
        return solve

    @scorer(metrics=[mean(), stderr()], name="llmdyno/correctness")
    def llmdyno_correctness():
        async def score(state, target):
            r = state.metadata.get("llmdyno") or {}
            tests = f"{r.get('tests_passed')}/{r.get('tests_total')} hidden tests" if r.get("tests_total") else ""
            return Score(value=float(r.get("correctness") or 0.0), answer=str(r.get("run_id") or ""),
                         explanation=tests or None,
                         metadata={k: r.get(k) for k in ("run_id", "plan_id", "final", "instruction_following",
                                                        "quality", "wall_s", "cost_usd", "generated_tokens")})
        return score

    _components.update(agent=llmdyno_agent, scorer=llmdyno_correctness)
    return _components


def inspect_task(benchmarks, profile, harness: str = "pi", name: str = "llmdyno", **bench_options):
    """An Inspect Task whose samples are LLMDyno benchmarks (or suites, expanded), solved by running them with this
    profile and harness. Extra keywords go to bench() (budget_usd=, timeout_multiplier=, acknowledge_risks=, …)."""
    require("inspect_ai", "inspect", "inspect_task()")
    from inspect_ai import Task
    from inspect_ai.dataset import Sample

    from .. import lib
    from ..sdk._core import _as_list, _id
    suites = {s["id"]: s["benchmark_ids"] for s in lib.list_suites()}
    ids = []
    for b in _as_list(benchmarks):
        ids += suites.get(_id(b), [_id(b)])
    samples = []
    for bid in dict.fromkeys(ids):
        b = lib.benchmark(bid)
        samples.append(Sample(input=(b.prompts[0] if b.prompts else b.title), target="all hidden tests pass", id=bid,
                              metadata={"benchmark_id": bid, "title": b.title, "stages": len(b.prompts)}))
    comps = _registered()
    prof = lib.profile(profile)
    return Task(dataset=samples, solver=comps["agent"](prof.id, str(_id(harness)), bench_options),
                scorer=comps["scorer"](), name=name,
                metadata={"llmdyno_version": __version__, "profile": prof.name, "harness": _id(harness)})


def _text(x) -> str:
    if isinstance(x, str):
        return x
    if isinstance(x, list):
        return "\n\n".join(_text(getattr(m, "content", m)) for m in x)
    return str(getattr(x, "text", x))


def import_inspect_samples(samples, prefix: str = "inspect", suite: str | None = None, answer_file: str = "answer.txt",
                           timeout_s: int = 600, category: str = "Inspect import"):
    """LLMDyno benchmarks from Inspect samples (a Dataset or a list of Sample): the prompt asks the agent to write its
    final answer to answer_file, and the grader checks it contains the sample's target. Sample files become the
    starter workspace. Returns a Suite of them (named after the prefix unless suite= is given)."""
    require("inspect_ai", "inspect", "import_inspect_samples()")
    from .. import lib
    made = []
    for i, s in enumerate(samples):
        target = s.target[0] if isinstance(s.target, list) and s.target else s.target
        if not target:
            raise LLMDynoError(f"sample {s.id or i} has no target to check the answer against")
        sid = re.sub(r"[^a-z0-9_]+", "_", str(s.id if s.id is not None else i + 1).lower()).strip("_")
        bid = re.sub(r"[^a-z0-9_]+", "_", f"{prefix}_{sid}".lower())[:61]
        files = {}
        for path, content in (s.files or {}).items():
            p = Path(str(content))
            files[path] = p.read_text(encoding="utf-8") if len(str(content)) < 400 and p.is_file() else str(content)
        prompt = _text(s.input).strip() + (f"\n\nWhen you are done, write your final answer, and nothing else, to "
                                           f"{answer_file} in the workspace.")
        if s.choices:
            prompt = _text(s.input).strip() + "\n\nChoices:\n" + "\n".join(
                f"{chr(65 + j)}. {c}" for j, c in enumerate(s.choices)) + prompt[len(_text(s.input).strip()):]
        spec = {"id": bid, "title": f"{prefix} {sid}", "summary": _text(s.input).strip()[:140],
                "description": f"Imported from an Inspect AI dataset ({prefix}).", "category": category,
                "difficulty": "medium", "languages": ["text"], "tags": ["inspect", prefix],
                "stages": [{"prompt": prompt, "timeout_s": timeout_s}], "workspace_files": files, "hidden_tests": {},
                "checks": [{"name": "answer", "type": "file_contains", "path": answer_file, "text": str(target)}],
                "reference_files": {answer_file: str(target) + "\n"}}
        existing = {b["id"] for b in lib.list_benchmarks()}
        made.append(lib.benchmark(bid).update(spec) if bid in existing else lib.create_benchmark(spec))
    name = suite or f"Inspect: {prefix}"
    mine = [x for x in lib.list_suites() if x["name"] == name]
    if mine:
        return lib.suite(mine[0]["id"]).update(benchmarks=made)
    return lib.create_suite(name, made, f"{len(made)} samples imported from an Inspect AI dataset")


def to_eval_log(results, path, task: str = "llmdyno"):
    """Write results as an Inspect eval log (one sample per run, scored by correctness, with LLMDyno's other scores in
    the sample metadata); open it with `inspect view`. Returns the path."""
    require("inspect_ai", "inspect", "to_inspect_log()")
    from inspect_ai.log import (EvalConfig, EvalDataset, EvalLog, EvalMetric, EvalResults, EvalSample, EvalScore,
                                EvalSpec, write_eval_log)
    from inspect_ai.model import ChatMessageUser, ModelOutput
    from inspect_ai.scorer import Score
    labels = results._labels
    samples = []
    for r in results.data.get("runs") or []:
        prof = (labels.get("profiles") or {}).get(r["profile_id"]) or {}
        title = ((labels.get("benchmarks") or {}).get(r["benchmark_id"]) or {}).get("title", r["benchmark_id"])
        samples.append(EvalSample(
            id=r["id"], epoch=1, input=[ChatMessageUser(content=title)], target="all hidden tests pass",
            output=ModelOutput.from_content(model=prof.get("name") or r["profile_id"], content=r.get("status") or ""),
            scores={"llmdyno/correctness": Score(value=float(r.get("correctness") or 0.0))},
            metadata={"benchmark_id": r["benchmark_id"], "profile": prof.get("name"), "harness": r["harness_id"],
                      "plan_id": r["plan_id"], "final": r.get("final"), "quality": r.get("quality"),
                      "instruction_following": r.get("instruction_following"), "wall_s": r.get("wall_s"),
                      "cost_usd": r.get("cost_usd")}))
    vals = [s.scores["llmdyno/correctness"].value for s in samples]
    mean = sum(vals) / len(vals) if vals else 0.0
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    log = EvalLog(
        eval=EvalSpec(created=now, task=task, dataset=EvalDataset(name="llmdyno", samples=len(samples)),
                      model="llmdyno/" + ",".join(sorted({s.metadata["profile"] or "" for s in samples}))[:200],
                      config=EvalConfig(), packages={"llmdyno": __version__},
                      metadata={"plans": results.plan_ids, "weights": results.data.get("weights")}),
        status="success", samples=samples,
        results=EvalResults(total_samples=len(samples), completed_samples=len(samples),
                            scores=[EvalScore(name="llmdyno/correctness", scorer="llmdyno/correctness",
                                              metrics={"mean": EvalMetric(name="mean", value=mean)})]))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    write_eval_log(log, str(path))
    return path
