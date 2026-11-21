"""LLM judges: blind code review of finished runs."""
from __future__ import annotations

from typing import Sequence, Union

from ._core import Job, _as_list, _id, call, covers
from .profiles import Profile, profile
from .results import Results, results

__all__ = ["review"]

# Web API routes this module does not cover yet (see sdk/parity.py); remove each one as it gets a library call.
PENDING_ROUTES = (
    "GET /api/judge/defaults",
    "DELETE /api/reviews",
    "GET /api/reviews",
)


@covers("POST /api/judge")
def review(plans, judges: Union[Profile, str, Sequence], *, budget_usd: float | None = 1.0, concurrency: int = 4,
           quiet: bool = False) -> Results:
    """Blind LLM code review of finished runs by one or more judge profiles (cloud or local), then fresh Results
    whose code-quality score includes the reviews. budget_usd caps the judges' spend."""
    ids = [_id(p) for p in _as_list(plans)]
    body = {"judge_profile_ids": [profile(j).id for j in _as_list(judges)], "plan_ids": ids,
            "budget_usd": budget_usd, "concurrency": concurrency, "skip_reviewed": True}
    Job(call("judging.start_judge", body=body)["job_id"]).wait(quiet=quiet)
    return results(ids)
