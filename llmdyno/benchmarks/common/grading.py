"""Shared helpers for hidden graders. Graders run in a fresh offline container with the
agent's workspace copied to /work and print one JSON object as their last stdout line."""
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

WORK = Path(os.environ.get("WORK", "/work"))


def run(cmd, cwd=WORK, timeout=300, env=None):
    e = dict(os.environ, PYTHONPATH=str(WORK), **(env or {}))
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=e,
                           shell=isinstance(cmd, str))
        return p.returncode, p.stdout[-4000:], p.stderr[-4000:]
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"


def pytest_results(test_paths, timeout=600, per_test_timeout=60, tag="hidden"):
    """Run pytest on hidden test files against /work; return {test_id: passed_bool}."""
    xml = Path(f"/tmp/junit-{tag}.xml")
    if xml.exists():
        xml.unlink()
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--timeout={per_test_timeout}",
            f"--junitxml={xml}", "--rootdir", str(WORK), *map(str, test_paths)]
    code, out, err = run(args, timeout=timeout)
    results = {}
    if xml.exists():
        for tc in ET.parse(xml).getroot().iter("testcase"):
            tid = f"{tc.get('classname', '')}::{tc.get('name')}"
            failed = any(child.tag in ("failure", "error", "skipped") for child in tc)
            results[tid] = not failed
    return results, out, err


def count_test_functions(folder):
    n = 0
    for f in Path(folder).rglob("test_*.py"):
        n += len(re.findall(r"^\s*(?:async\s+)?def test_", f.read_text(errors="ignore"), flags=re.M))
    return n


def emit(tests: dict, checks: dict, extra=None):
    """tests: {id: bool} hidden-test outcomes. checks: {name: bool} instruction-following checks."""
    t_total, t_pass = len(tests), sum(tests.values())
    c_total, c_pass = len(checks), sum(bool(v) for v in checks.values())
    out = {
        "tests_total": t_total, "tests_passed": t_pass,
        "correctness": round(t_pass / t_total, 4) if t_total else 0.0,
        "checks_total": c_total, "checks_passed": c_pass,
        "instruction_following": round(c_pass / c_total, 4) if c_total else 0.0,
        "tests": tests, "checks": {k: bool(v) for k, v in checks.items()},
    }
    if extra:
        out.update(extra)
    print(json.dumps(out))
