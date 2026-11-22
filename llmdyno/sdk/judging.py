# pyright: strict, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false
"""LLM judges: blind code review of finished runs."""
from __future__ import annotations

from typing import Any, Sequence, Union

from ._core import Job, as_list, id_of, call, covers
from .profiles import Profile, profile
from .results import Results, results

__all__ = ["review", "judge_defaults", "reviews", "delete_reviews"]

@covers("POST /api/judge")
def review(plans: Any=None, judges: Union[Profile, str, Sequence[Any]] = (), *, runs: Any=None, budget_usd: float | None = 1.0,
           concurrency: int = 4, rubric: list[Any] | None = None, guidance: str | None = None,
           include_static: bool = False, max_output_tokens: int | None = None, skip_reviewed: bool = True,
           wait: bool = True, quiet: bool = False) -> Union[Results, Job]:
    """Blind LLM code review of finished runs by one or more judge profiles (cloud or local), then fresh Results
    whose code-quality score includes the reviews. judges is required: a profile, its name, or a list (two from
    different vendors let LLMDyno check agreement and self-preference). Review whole plans, or only some runs
    with runs=.
    budget_usd caps the judges' spend. rubric and guidance replace the defaults (see judge_defaults(): a rubric is a
    list of {"key", "label", "description"} dimensions); include_static shows judges the static-analysis findings;
    skip_reviewed=False reviews again runs a judge already reviewed. wait=False returns the Job."""
    ids = [id_of(p) for p in as_list(plans)]
    run_ids = [id_of(r) for r in as_list(runs)]
    body = {"judge_profile_ids": [profile(j).id for j in as_list(judges)], "plan_ids": ids, "run_ids": run_ids,
            "budget_usd": budget_usd, "concurrency": concurrency, "skip_reviewed": skip_reviewed,
            "rubric": rubric, "guidance": guidance, "include_static": include_static,
            "max_output_tokens": max_output_tokens}
    job = Job(call("judging.start_judge", body={k: v for k, v in body.items() if v is not None})["job_id"])
    if not wait:
        return job
    job.wait(quiet=quiet)
    if ids:
        return results(ids)
    plan_ids = sorted({call("runs.get_run", rid=r)["plan_id"] for r in run_ids})
    return results(plan_ids)


@covers("GET /api/judge/defaults")
def judge_defaults() -> dict[str, Any]:
    """LLMDyno's default judging setup: the rubric (dimensions with descriptions), the guidance judges get, and the
    default budget, concurrency and output limit."""
    return call("judging.judge_defaults")


@covers("GET /api/reviews")
def reviews(plan: Any=None, run: Any=None) -> list[Any]:
    """Reviews of a plan's runs or of one run (overall score, per-dimension scores, summary, issues, judge)."""
    return call("judging.list_reviews", plan_id=id_of(plan) if plan is not None else None,
                run_id=id_of(run) if run is not None else None)


@covers("DELETE /api/reviews")
def delete_reviews(judge: Any, plan: Any=None) -> int:
    """Delete one judge's reviews (a judge profile or its id), everywhere or only for one plan; returns how many."""
    return call("judging.delete_reviews", judge_id=id_of(judge), plan_id=id_of(plan) if plan is not None else None)["removed"]
