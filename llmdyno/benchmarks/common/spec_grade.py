"""Generic grader for spec-based benchmarks (custom benchmarks created in the UI use this).

/task/<grader path> is a JSON spec: {"tests": "<dir of hidden pytest files>", "checks": [...]}. Check types:
file_exists {path}, file_contains {path, text}, glob {pattern, min}, command {cmd, expect_exit, timeout},
test_count {path, min}. Correctness is the hidden-test pass rate; checks give instruction following."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/grader_common")
from grading import WORK, count_test_functions, emit, pytest_results, run  # noqa: E402

TASK = Path(os.environ.get("TASK_DIR", "/task"))
spec = json.loads((TASK / os.environ.get("SPEC", "grader/spec.json")).read_text())

tests = {}
if spec.get("tests") and (TASK / spec["tests"]).exists():
    tests, _, _ = pytest_results([TASK / spec["tests"]], timeout=spec.get("timeout_s", 600))


def check(c):
    t, rel = c.get("type"), (c.get("path") or "").strip()
    if t in ("file_exists", "file_contains", "test_count") and rel in ("", ".", "./"):
        return False                  # an empty path would point at the workspace itself and always pass
    p = WORK / rel
    if t == "file_exists":
        return p.exists()
    if t == "file_contains":
        return p.is_file() and c.get("text", "") in p.read_text(errors="ignore")
    if t == "glob":
        return len(list(WORK.glob(c["pattern"]))) >= c.get("min", 1)
    if t == "command":
        code = run(c["cmd"], timeout=c.get("timeout", 300))[0]
        return code == c.get("expect_exit", 0)
    if t == "test_count":
        return p.exists() and count_test_functions(p) >= c.get("min", 1)
    return False


checks = {c.get("name") or f"check_{i}": check(c) for i, c in enumerate(spec.get("checks", []))}
emit(tests, checks)
