"""Grader validation: the starting workspace should fail, the reference solution should pass."""
import shutil
from pathlib import Path

from .. import config
from ..runner import sandbox
from . import registry


def validate(ctx):
    b = registry.get(ctx.params["benchmark_id"])
    root = config.DATA / "validation" / b["id"]
    shutil.rmtree(root, ignore_errors=True)
    if b["grader"]["type"] == "swebench":
        return _validate_swebench(ctx, b, root)
    n = len(b["stages"])
    report = {"benchmark_id": b["id"], "stages": n}
    starter = root / "starter"
    sandbox.prepare_workspace(b, starter)
    for st in b["stages"]:
        if st.get("add_files"):
            shutil.copytree(Path(b["dir"]) / st["add_files"], starter, dirs_exist_ok=True)
    ctx.progress(0.1, "grading the untouched starting workspace")
    g0 = sandbox.grade(b, starter, n)
    report["starter"] = _brief(g0)
    if b.get("has_reference"):
        ref = root / "reference"
        shutil.copytree(starter, ref)
        shutil.copytree(Path(b["dir"]) / b["reference"], ref, dirs_exist_ok=True)
        ctx.progress(0.55, "grading the reference solution")
        g1 = sandbox.grade(b, ref, n)
        report["reference"] = _brief(g1)
    problems = []
    if g0.get("grader_error"):
        problems.append("The grader crashed on the starting workspace: " + g0["grader_error"][-300:])
    elif (g0.get("correctness") or 0) > 0.5:
        problems.append(f"The untouched workspace already passes {g0['tests_passed']}/{g0['tests_total']} hidden tests: "
                        "the tests do not measure the agent's work.")
    if not g0.get("tests_total") and not g0.get("checks_total"):
        problems.append("Nothing is graded: add hidden tests or checks.")
    if "reference" in report:
        r = report["reference"]
        if r.get("grader_error"):
            problems.append("The grader crashed on the reference: " + r["grader_error"][-300:])
        elif (r.get("correctness") or 0) < 1.0 and r.get("tests_total"):
            problems.append(f"The reference solution fails {r['tests_total'] - r['tests_passed']} hidden test(s): "
                            "check the tests or the reference.")
    else:
        report["note"] = "No reference solution, so only the failing side was checked."
    report["problems"] = problems
    report["ok"] = not problems
    ctx.result = report
    for p in problems:
        ctx.log("problem: " + p)


def _validate_swebench(ctx, b, root):
    """The official harness must resolve the instance with its gold patch; otherwise the image or harness is broken."""
    from . import envs, swebench
    report = {"benchmark_id": b["id"], "stages": 1, "note": "SWE-bench: the gold patch is graded by the official "
              "harness. An empty patch is unresolved by definition, so the starting side is not graded."}
    problems = []
    if not swebench.harness_python().exists():
        problems.append("The SWE-bench harness is not installed: install it on the Setup page.")
    else:
        env = envs.spec(b)
        ctx.progress(0.1, f"pulling {env['image']}")
        envs.ensure_image(env["image"], env["platform"], log=ctx.log, cancel=ctx.cancel_event)
        ctx.progress(0.4, "grading the gold patch with the official harness")
        g = swebench.validate_gold(b, root)
        report["reference"] = {**_brief(g), "resolved": g.get("resolved"), "fail_to_pass": g.get("fail_to_pass"),
                               "pass_to_pass": g.get("pass_to_pass")}
        if g.get("grader_error"):
            problems.append("The harness failed on the gold patch: " + g["grader_error"][-300:])
        elif not g.get("resolved"):
            problems.append(f"The gold patch does not resolve the instance (FAIL_TO_PASS {g.get('fail_to_pass')}, "
                            f"PASS_TO_PASS {g.get('pass_to_pass')}): the environment is broken on this machine.")
    report["problems"] = problems
    report["ok"] = not problems
    ctx.result = report
    for p in problems:
        ctx.log("problem: " + p)


def _brief(g):
    return {k: g.get(k) for k in ("correctness", "tests_passed", "tests_total", "instruction_following",
                                  "checks_passed", "checks_total", "checks", "grader_error", "grade_s")}
