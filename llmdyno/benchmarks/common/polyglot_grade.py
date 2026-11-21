"""Grader for Aider polyglot exercises (runs in the llmdyno-polyglot image).

/task/<grader path> is {"language", "test_files", "solution_files"}; /task/grader/tests holds the original test
files. They are restored over the agent's copies first, so editing a test cannot help. An exercise counts as solved
only when every test passes (the Aider benchmark's measure); the pass rate is reported alongside."""
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, "/grader_common")
from grading import WORK, emit, pytest_results  # noqa: E402

TASK = Path(os.environ.get("TASK_DIR", "/task"))
spec = json.loads((TASK / os.environ.get("SPEC", "grader/spec.json")).read_text())
lang = spec["language"]
orig = TASK / "grader" / "tests"
TIMEOUT = int(spec.get("timeout_s", 480))

# build output the agent left behind was made in /workspace; CMake and Gradle refuse caches from another folder
for junk in {"cpp": ["build"], "java": ["build", ".gradle"]}.get(lang, []):
    shutil.rmtree(WORK / junk, ignore_errors=True)

untouched = True
for rel in spec["test_files"]:
    src, dst = orig / rel, WORK / rel
    if dst.exists() and dst.read_bytes() != src.read_bytes():
        untouched = False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)


def parse_go(out):
    return {m.group(2): m.group(1) == "PASS" for m in re.finditer(r"--- (PASS|FAIL): (\S+)", out)}


def parse_rust(out):
    return {m.group(1): m.group(2) == "ok" for m in re.finditer(r"^test (\S+) \.\.\. (ok|FAILED)", out, re.M)}


def parse_junit_dir(folder):
    res = {}
    for f in Path(folder).glob("*.xml"):
        try:
            for tc in ET.parse(f).getroot().iter("testcase"):
                res[f"{tc.get('classname', '')}::{tc.get('name')}"] = not any(
                    ch.tag in ("failure", "error", "skipped") for ch in tc)
        except ET.ParseError:
            pass
    return res


def parse_catch(out, code):
    m = re.search(r"test cases:\s*(\d+)\s*\|\s*(\d+) passed\s*\|\s*(\d+) failed", out)
    if m:
        total, ok = int(m.group(1)), int(m.group(2))
        return {f"test case {i + 1}": i < ok for i in range(total)}
    m = re.search(r"All tests passed \(\d+ assertions? in (\d+) test cases?\)", out)
    if m:
        return {f"test case {i + 1}": True for i in range(int(m.group(1)))}
    return {}


def run_full(cmd):
    """Like grading.run, but keeps the whole output (test listings are longer than its 4000-character tail)."""
    try:
        p = subprocess.run(cmd, cwd=WORK, shell=True, capture_output=True, text=True, errors="replace", timeout=TIMEOUT)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {TIMEOUT}s"


tests, out, err, code = {}, "", "", None
if lang == "python":
    tests, out, err = pytest_results([WORK / t for t in spec["test_files"]], timeout=TIMEOUT, per_test_timeout=60)
elif lang == "javascript":
    code, out, err = run_full("polyglot-test --json --outputFile=/tmp/jest.json")
    try:
        j = json.loads(Path("/tmp/jest.json").read_text())
        for tr in j.get("testResults", []):
            for a in tr.get("assertionResults", []):
                tests[a.get("fullName") or a.get("title")] = a.get("status") == "passed"
    except (OSError, ValueError):
        pass
else:
    code, out, err = run_full("polyglot-test")
    if lang == "go":
        tests = parse_go(out)
    elif lang == "rust":
        tests = parse_rust(out)
    elif lang == "java":
        tests = parse_junit_dir(WORK / "build" / "test-results" / "test")
    elif lang == "cpp":
        tests = parse_catch(out, code)
if not tests:
    tests = {"test suite": code == 0}          # build failure or unparsed output: one pass/fail verdict

solved = bool(tests) and all(tests.values())
checks = {"left the test files alone": untouched,
          "kept the solution files": all((WORK / s).exists() for s in spec["solution_files"])}
emit(tests, checks, {"correctness": 1.0 if solved else 0.0, "solved": solved, "language": lang,
                     "test_pass_rate": round(sum(tests.values()) / len(tests), 4) if tests else 0.0,
                     "test_output": (out + err)[-1500:] if not solved else ""})
