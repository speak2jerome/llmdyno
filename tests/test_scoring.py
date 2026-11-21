"""Scoring: the leaderboard's stacked bar must add up to the final score, with or without a code-quality score."""
from llmdyno import scoring

WEIGHTS = {"correctness": 50, "instruction_following": 15, "quality": 25, "efficiency": 10}
QWEIGHTS = {"static": 35, "probes": 30, "review": 35}


def run(rid, bench, correctness, wall=100.0, quality=None):
    return {"id": rid, "plan_id": "p", "profile_id": "prof", "harness_id": "pi", "benchmark_id": bench, "iteration": 1,
            "kind": "local", "correctness": correctness, "instruction_following": 1.0, "wall_s": wall, "cost_usd": 0.01,
            "quality_raw": quality or {}, "started_at": 0, "family": None}


def test_bar_matches_final_without_code_quality():
    # tasks that run in their own image (SWE-bench, polyglot) have no static analysis, so quality is None
    out = scoring.compute([run("r1", "swe_x", 1.0), run("r2", "pg_y", 0.0)], [], WEIGHTS, QWEIGHTS)
    c = out["configs"][0]
    assert c["quality"] is None
    assert abs(sum(c["points"].values()) - c["final"] * 100) < 0.05
    assert c["points"]["quality"] == 0
