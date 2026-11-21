"""LLM judges: rubric defaults, starting reviews, listing and deleting reviews."""
from .. import db, jobs
from ..judge import judge as judge_mod
from .. import errors
from ._common import _get


def judge_defaults():
    return {"rubric": judge_mod.DEFAULT_RUBRIC, "guidance": judge_mod.DEFAULT_GUIDANCE, "max_output_tokens": 12000,
            "concurrency": 4, "budget_usd": 1.0, "blind": True, "include_static": False, "skip_reviewed": True}


def start_judge(body: dict):
    jp = body.get("judge_profile_ids") or []
    if not jp:
        raise errors.http(400, "choose at least one judge profile")
    for p in jp:
        _get(db.Profile, p)
    if not body.get("plan_ids") and not body.get("run_ids"):
        raise errors.http(400, "choose plans or runs to review")
    rubric = body.get("rubric") or judge_mod.DEFAULT_RUBRIC
    if not rubric or any(not r.get("key") for r in rubric):
        raise errors.http(400, "every rubric dimension needs a key")
    cfg = {k: body.get(k) for k in ("judge_profile_ids", "plan_ids", "run_ids", "rubric", "guidance", "include_static",
                                    "budget_usd", "skip_reviewed", "concurrency", "max_output_tokens")}
    cfg["rubric"] = rubric
    return {"job_id": jobs.submit("judge", "Judge: " + ", ".join(_get(db.Profile, p)["name"] for p in jp),
                                  judge_mod.run_judge, cfg, ref=",".join(body.get("plan_ids") or []))}


def list_reviews(plan_id: str | None = None, run_id: str | None = None):
    with db.Session() as s:
        q = s.query(db.Review)
        if run_id:
            q = q.filter(db.Review.run_id == run_id)
        elif plan_id:
            ids = [r.id for r in s.query(db.Run).filter(db.Run.plan_id == plan_id)]
            q = q.filter(db.Review.run_id.in_(ids))
        return [db.row(r) for r in q.all()]


def delete_reviews(judge_id: str, plan_id: str | None = None):
    with db.Session() as s:
        q = s.query(db.Review).filter(db.Review.judge_id == judge_id)
        if plan_id:
            ids = [r.id for r in s.query(db.Run).filter(db.Run.plan_id == plan_id)]
            q = q.filter(db.Review.run_id.in_(ids))
        n = q.delete(synchronize_session=False)
        s.commit()
    return {"removed": n}
