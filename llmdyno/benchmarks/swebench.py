"""SWE-bench: import task instances as LLMDyno benchmarks, grade with the official harness, export predictions.

Each instance becomes a one-stage benchmark whose agent runs inside the official instance image
(swebench/sweb.eval.x86_64.<id>), with the repository at /testbed. After the agent finishes, its changes are
collected as a git diff against the instance's base commit and graded by the official `swebench` package
(run_evaluation), installed into its own virtual environment so its dependencies never touch LLMDyno's.
The score is the official one: an instance counts as resolved only when every FAIL_TO_PASS and PASS_TO_PASS test
passes. Predictions are written in the SWE-bench JSONL format, so a plan can be submitted or re-graded elsewhere.

Datasets: SWE-bench Verified (500, human-validated), Lite (300) and the 50-instance Verified mini subset.
Rows come from the Hugging Face datasets server; the official datasets carry the image name, eval script and log
parser that the harness needs."""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

from .. import config, db
from ..system import specs as sysspecs
from . import envs, registry

ROWS_API = "https://datasets-server.huggingface.co/rows"
DATASETS = {
    "verified": {"hf": "SWE-bench/SWE-bench_Verified", "name": "SWE-bench Verified", "size": 500,
                 "about": "500 tasks from 12 Python repositories, each checked by human annotators."},
    "lite": {"hf": "SWE-bench/SWE-bench_Lite", "name": "SWE-bench Lite", "size": 300,
             "about": "300 self-contained tasks chosen to be cheaper to evaluate."},
    "verified_mini": {"hf": "MariusHobbhahn/swe-bench-verified-mini", "name": "SWE-bench Verified mini", "size": 50,
                      "about": "A 50-task subset of Verified with the same difficulty mix; a good first run.",
                      "rows_from": "verified"},
}
HOMEPAGE = "https://www.swebench.com"
HARNESS_PKG = "swebench"
MODEL_NAME = "llmdyno"
NOWIN = subprocess.CREATE_NO_WINDOW if sysspecs.IS_WIN else 0
DIFFICULTY_MINUTES = {"<15 min fix": 8, "15 min - 1 hour": 15, "1-4 hours": 25, ">4 hours": 35}

PROMPT = """<uploaded_files>
/testbed
</uploaded_files>

I've uploaded a Python code repository in /testbed (also mounted at /workspace, your current directory).
Consider the following issue description:

<issue_description>
{problem}
</issue_description>

Make the minimal changes to non-test files in the repository so that the requirements in the issue are met.
Test files that check this behaviour have already been taken care of: do not modify any tests.

Work like this:
1. Explore the repository to find the code involved.
2. Write a small script that reproduces the problem and run it with `python`.
3. Edit the source code to fix the problem.
4. Rerun your script to confirm the fix, and think about edge cases.
5. Run the existing tests closest to your change.

The Python environment ({repo} {version}) is already set up and active. There is no network access, so do not try
to install packages. When you are done, reply with a short summary of the cause and the fix.
"""


# ------------------------------------------------------------------ dataset rows
def slug(instance_id):
    return "swe_" + re.sub(r"[^a-z0-9_]+", "_", instance_id.lower()).strip("_")[:56]


def _as_list(v):
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            v = [v] if v else []
    return list(v or [])


def fetch_rows(hf_name, offset=0, length=100, client=None):
    c = client or httpx.Client(timeout=60, follow_redirects=True)
    r = c.get(ROWS_API, params={"dataset": hf_name, "config": "default", "split": "test", "offset": offset,
                                "length": length})
    r.raise_for_status()
    d = r.json()
    return [x["row"] for x in d.get("rows", [])], d.get("num_rows_total")


def fetch_all(hf_name, client=None, progress=None):
    rows, offset, total = [], 0, None
    while total is None or offset < total:
        chunk, total = fetch_rows(hf_name, offset, 100, client)
        if not chunk:
            break
        rows += chunk
        offset += len(chunk)
        if progress:
            progress(offset, total)
    return rows


def row_to_benchmark(row, dataset_key):
    """(benchmark.json dict, {relative path: text}) for one SWE-bench instance. Pure, so it is unit tested."""
    ds = DATASETS[dataset_key]
    iid = row["instance_id"]
    for need in ("image", "eval_script", "log_parser", "base_commit", "problem_statement"):
        if not row.get(need):
            raise ValueError(f"{iid}: the dataset row has no {need!r} (use the official SWE-bench datasets)")
    image = row["image"]
    f2p, p2p = _as_list(row.get("FAIL_TO_PASS")), _as_list(row.get("PASS_TO_PASS"))
    test_files = envs.patched_files(row.get("test_patch") or "")
    problem = row["problem_statement"].strip()
    title_line = next((ln.strip("# ").strip() for ln in problem.splitlines() if ln.strip()), iid)[:110]
    minutes = DIFFICULTY_MINUTES.get(row.get("difficulty") or "", 15)
    bench = {
        "id": slug(iid), "version": 1, "title": f"{iid}: {title_line}",
        "summary": f"{row['repo']} issue from {ds['name']}" + (f" ({row['difficulty']})" if row.get("difficulty") else ""),
        "description": (f"A real issue from {row['repo']}, taken from {ds['name']}. The agent fixes it inside the task's "
                        f"official Docker image without seeing the tests; the official SWE-bench harness then runs "
                        f"{len(f2p)} FAIL_TO_PASS and {len(p2p)} PASS_TO_PASS tests, and the task is resolved only if "
                        "all of them pass. The full issue is on the Task tab."), "category": "SWE-bench", "difficulty": row.get("difficulty") or "unknown",
        "languages": ["Python"], "tags": ["swe-bench", dataset_key, row["repo"].split("/")[0]],
        "stages": [{"prompt": "prompts/stage1.md", "timeout_s": 2400}], "grade_each_stage": False,
        "grader": {"type": "swebench", "timeout_s": 1800}, "min_context": 64000,
        "expected_minutes": {"local": minutes * 2, "cloud": minutes},
        "workspace": None, "decompress": [], "reference": None, "probes": None, "quality": None,
        "env": {"type": "swebench", "image": image, "platform": envs.image_platform(image), "workspace": "volume",
                "repo_dir": "/testbed", "base_commit": row["base_commit"]},
        "origin": ds["name"], "source": {"name": ds["name"], "url": HOMEPAGE, "dataset": DATASETS[ds.get("rows_from")
                                                                                                   or dataset_key]["hf"],
                                         "license": "MIT", "instance_id": iid},
        "swebench": {"instance_id": iid, "dataset": dataset_key, "repo": row["repo"], "version": row.get("version"),
                     "fail_to_pass": len(f2p), "pass_to_pass": len(p2p), "test_files": test_files,
                     "created_at": row.get("created_at")},
        "reference_tokens": {"prompt": 600000, "output": 15000, "cache_hit": 0.9},
    }
    instance = {k: row.get(k) for k in ("instance_id", "repo", "version", "base_commit", "environment_setup_commit",
                                         "image", "eval_script", "log_parser", "eval_type", "image_assets",
                                         "test_patch", "patch", "problem_statement", "hints_text", "created_at",
                                         "difficulty") if row.get(k) is not None}
    instance["FAIL_TO_PASS"], instance["PASS_TO_PASS"] = f2p, p2p
    files = {"benchmark.json": json.dumps(bench, indent=2),
             "prompts/stage1.md": PROMPT.format(problem=problem, repo=row["repo"], version=row.get("version") or ""),
             "grader/instance.json": json.dumps(instance, indent=2),
             "reference/gold.patch": row.get("patch") or ""}
    return bench, files


def import_job(ctx):
    """Job: import a SWE-bench dataset (or chosen instances) as benchmarks plus a suite."""
    key = ctx.params.get("dataset", "verified_mini")
    if key not in DATASETS:
        raise ValueError(f"unknown dataset {key}")
    ds = DATASETS[key]
    wanted = set(ctx.params.get("instance_ids") or [])
    limit = int(ctx.params.get("limit") or 0)
    with httpx.Client(timeout=60, follow_redirects=True, headers={"User-Agent": "LLMDyno"}) as c:
        ctx.log(f"listing {ds['hf']}")
        if limit and not wanted and not ds.get("rows_from"):
            rows = []
            while len(rows) < limit:                 # only the rows asked for, not the whole dataset
                chunk, _ = fetch_rows(ds["hf"], len(rows), min(100, limit - len(rows)), c)
                if not chunk:
                    break
                rows += chunk
        else:
            rows = fetch_all(ds["hf"], c, lambda n, t: ctx.progress(0.4 * n / max(t or 1, 1), f"{n}/{t} rows"))
        if ds.get("rows_from"):
            ids = {r["instance_id"] for r in rows}
            src = DATASETS[ds["rows_from"]]
            ctx.log(f"{len(ids)} instance ids; reading their full rows from {src['hf']}")
            rows = [r for r in fetch_all(src["hf"], c, lambda n, t: ctx.progress(0.4 + 0.4 * n / max(t or 1, 1),
                                                                                    f"{n}/{t} rows"))
                    if r["instance_id"] in ids]
    if wanted:
        rows = [r for r in rows if r["instance_id"] in wanted]
    if limit:
        rows = rows[:limit]
    root = registry.user_dir()
    made, errors = [], []
    for i, row in enumerate(rows):
        ctx.check()
        try:
            bench, files = row_to_benchmark(row, key)
        except (ValueError, KeyError) as e:
            errors.append(str(e))
            continue
        d = root / bench["id"]
        shutil.rmtree(d, ignore_errors=True)
        for rel, text in files.items():
            (d / rel).parent.mkdir(parents=True, exist_ok=True)
            (d / rel).write_text(text, encoding="utf-8")
        made.append(bench["id"])
        ctx.progress(0.8 + 0.2 * (i + 1) / len(rows), f"{i + 1}/{len(rows)} imported")
    suite_id = None
    if made and not wanted:
        suite_id = f"suite_swebench_{key}" + (f"_{limit}" if limit else "")
        with db.Session() as s:
            sx = s.get(db.Suite, suite_id) or db.Suite(id=suite_id, created_at=time.time())
            sx.name = f"{ds['name']}" + (f" (first {limit})" if limit else f" ({len(made)})")
            sx.description = f"{ds['about']} Imported from {ds['hf']}; graded by the official SWE-bench harness."
            sx.benchmark_ids = made
            s.merge(sx)
            s.commit()
    ctx.result = {"imported": len(made), "benchmark_ids": made, "suite_id": suite_id, "errors": errors[:20]}
    ctx.log(f"imported {len(made)} instance(s)" + (f", {len(errors)} skipped" if errors else ""))


# ------------------------------------------------------------------ official harness
def harness_dir():
    return config.DATA / "tools" / "swebench"


def harness_python():
    v = harness_dir() / "venv"
    return v / ("Scripts/python.exe" if sysspecs.IS_WIN else "bin/python")


def harness_status():
    py = harness_python()
    if not py.exists():
        return {"installed": False, "version": None, "path": str(harness_dir())}
    r = subprocess.run([str(py), "-c", "import importlib.metadata as m; print(m.version('swebench'))"],
                       capture_output=True, text=True, timeout=60, creationflags=NOWIN)
    return {"installed": r.returncode == 0, "version": r.stdout.strip() or None, "path": str(harness_dir())}


def install_harness(ctx):
    """Job: create an isolated venv and pip-install the official harness into it."""
    version = ctx.params.get("version") or (config.get("swebench") or {}).get("harness_version") or "5.0.2"
    if not re.fullmatch(r"[0-9][0-9a-z.]*", version):
        raise ValueError("invalid version")
    venv = harness_dir() / "venv"
    if not harness_python().exists():
        ctx.log(f"$ {sys.executable} -m venv {venv}")
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, creationflags=NOWIN)
    cmd = [str(harness_python()), "-m", "pip", "install", "--disable-pip-version-check", f"{HARNESS_PKG}=={version}"]
    ctx.log("$ " + " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace",
                            creationflags=NOWIN)
    for line in proc.stdout:
        ctx.log(line.rstrip())
        ctx.check()
    if proc.wait() != 0:
        raise RuntimeError(f"pip exited with {proc.returncode}")
    ctx.result = harness_status()


def _instance(bench):
    return json.loads((Path(bench["dir"]) / "grader" / "instance.json").read_text(encoding="utf-8"))


def report_to_grade(report, instance, patch, iid):
    """Map the harness report.json to LLMDyno's grade dict. Pure, so it is unit tested."""
    r = report.get(iid) or {}
    st = r.get("tests_status") or {}
    f2p, p2p = st.get("FAIL_TO_PASS") or {}, st.get("PASS_TO_PASS") or {}
    tests = {}
    for group, d in (("FAIL_TO_PASS", f2p), ("PASS_TO_PASS", p2p)):
        for t in d.get("success") or []:
            tests[f"{group}::{t}"] = True
        for t in d.get("failure") or []:
            tests[f"{group}::{t}"] = False
    touched = set(envs.patched_files(patch))
    test_files = set(envs.patched_files(instance.get("test_patch") or ""))
    checks = {"produced a patch": bool(patch.strip()),
              "patch applies to the base commit": bool(r.get("patch_successfully_applied")),
              "left the task's test files alone": not (touched & test_files)}
    f2p_ok = not (f2p.get("failure") or []) and bool(f2p.get("success"))
    p2p_ok = not (p2p.get("failure") or [])
    resolved = bool(r.get("resolved"))
    return {"correctness": 1.0 if resolved else 0.0, "tests_total": len(tests), "tests_passed": sum(tests.values()),
            "tests": tests, "checks": checks, "checks_total": len(checks), "checks_passed": sum(checks.values()),
            "instruction_following": round(sum(checks.values()) / len(checks), 4),
            "resolved": resolved, "fail_to_pass": f"{len(f2p.get('success') or [])}/{len(instance.get('FAIL_TO_PASS') or [])}",
            "pass_to_pass": f"{len(p2p.get('success') or [])}/{len(instance.get('PASS_TO_PASS') or [])}",
            "f2p_all_pass": f2p_ok, "p2p_all_pass": p2p_ok, "patch_files": sorted(touched)}


def evaluate(instance, patch, out_dir, timeout_s=1800, run_id="llmdyno"):
    """Run the official harness on one prediction. Returns (report dict or None, log tail)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    iid = instance["instance_id"]
    (out_dir / "dataset.json").write_text(json.dumps([instance]), encoding="utf-8")
    pred = {"instance_id": iid, "model_name_or_path": MODEL_NAME, "model_patch": patch}
    (out_dir / "predictions.jsonl").write_text(json.dumps(pred) + "\n", encoding="utf-8")
    rid = re.sub(r"[^A-Za-z0-9_.-]", "_", run_id)[-40:]
    shim = Path(__file__).with_name("swebench_shim.py")      # Unix line endings on Windows; harness unchanged
    cmd = [str(harness_python()), "-P", str(shim), "-d", str(out_dir / "dataset.json"),
           "-s", "test", "-i", iid, "-p", str(out_dir / "predictions.jsonl"), "--max_workers", "1", "-id", rid,
           "--report_dir", str(out_dir), "-t", str(int(timeout_s))]
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    p = subprocess.run(cmd, cwd=out_dir, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout_s + 900, env=env, creationflags=NOWIN)
    (out_dir / "harness.log").write_text(p.stdout + "\n--- stderr ---\n" + p.stderr, encoding="utf-8")
    rep = out_dir / "logs" / "run_evaluation" / rid / MODEL_NAME / iid / "report.json"
    if rep.exists():
        return json.loads(rep.read_text(encoding="utf-8")), ""
    return None, (p.stderr or p.stdout)[-1500:]


def grade(bench, workspace, timeout_s=1800):
    """Grader entry point (sandbox.grade dispatches here). The patch was written by the executor."""
    run_dir = workspace.parent
    patch_file = workspace / "model.patch"
    patch = patch_file.read_text(encoding="utf-8") if patch_file.exists() else ""
    instance = _instance(bench)
    iid = instance["instance_id"]
    base = {"correctness": 0.0, "instruction_following": 0.0, "tests_total": 0, "tests_passed": 0}
    if not harness_python().exists():
        return {**base, "grader_error": "The SWE-bench harness is not installed: install it on the Setup page."}
    if not patch.strip():
        return {**base, "resolved": False, "checks": {"produced a patch": False}, "checks_total": 1,
                "checks_passed": 0, "grade_note": "The agent changed nothing, so the instance is unresolved."}
    env = envs.spec(bench)
    envs.ensure_image(env["image"], env["platform"])      # the harness would pull for the host arch otherwise
    t0 = time.time()
    try:
        report, err = evaluate(instance, patch, run_dir / "swebench", timeout_s, run_id=run_dir.name)
    except subprocess.TimeoutExpired:
        return {**base, "grader_error": "the SWE-bench harness timed out"}
    if report is None:
        return {**base, "grader_error": "the SWE-bench harness wrote no report: " + err}
    g = report_to_grade(report, instance, patch, iid)
    g["grade_s"] = round(time.time() - t0, 1)
    return g


def validate_gold(bench, out_dir):
    """Grade the instance's gold patch: it must resolve, or the environment is broken."""
    instance = _instance(bench)
    gold = instance.get("patch") or ""
    report, err = evaluate(instance, gold, out_dir, run_id="gold")
    if report is None:
        return {"grader_error": err}
    return report_to_grade(report, instance, gold, instance["instance_id"])


# ------------------------------------------------------------------ predictions export
def predictions(runs, model_name=None):
    """SWE-bench JSONL lines for finished runs on imported instances."""
    out = []
    for r in runs:
        run_dir = Path(r.get("dir") or "")
        patch = run_dir / "workspace" / "model.patch"
        iid = ((r.get("snapshot") or {}).get("benchmark") or {}).get("instance_id")
        if not iid:
            try:
                iid = json.loads((Path(registry.get(r["benchmark_id"])["dir"]) / "grader" / "instance.json")
                                 .read_text(encoding="utf-8"))["instance_id"]
            except (KeyError, OSError, ValueError):
                continue
        if patch.exists():
            out.append({"instance_id": iid, "model_name_or_path": model_name or r.get("label") or MODEL_NAME,
                        "model_patch": patch.read_text(encoding="utf-8")})
    return out
