import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, "/grader_common")
from grading import WORK, count_test_functions, emit, pytest_results, run  # noqa: E402

HERE = Path(__file__).parent

tests, _, _ = pytest_results([HERE / "tests"])

fe = WORK / "frontend"
# Compile into a scratch dir so stale dist/ output from the agent can't hide errors.
tsc_ok = False
if (fe / "tsconfig.json").exists():
    shutil.rmtree("/tmp/tsc-out", ignore_errors=True)
    code, out, err = run(["tsc", "-p", str(fe), "--outDir", "/tmp/tsc-out"], timeout=180)
    tsc_ok = code == 0
tests["frontend::tsc_compiles_clean"] = tsc_ok

strict = False
try:
    raw = (fe / "tsconfig.json").read_text()
    raw = re.sub(r"//.*", "", raw)
    raw = re.sub(r",\s*([}\]])", r"\1", raw)
    strict = bool(json.loads(raw).get("compilerOptions", {}).get("strict"))
except Exception:
    pass

api_ts = (fe / "src" / "api.ts").read_text(errors="ignore") if (fe / "src" / "api.ts").exists() else ""
exports_ok = all(re.search(p, api_ts) for p in (
    r"export\s+(interface|type)\s+Job\b", r"export\s+type\s+Operation\b", r"export\s+type\s+JobStatus\b",
    r"export\s+(async\s+)?function\s+createJob\b|export\s+const\s+createJob\b",
    r"export\s+(async\s+)?function\s+getJob\b|export\s+const\s+getJob\b",
    r"export\s+(async\s+)?function\s+listJobs\b|export\s+const\s+listJobs\b"))
tests["frontend::api_ts_exports"] = exports_ok

own_dir = WORK / "backend" / "tests"
own_code = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--timeout=60", "backend/tests"],
               timeout=300)[0] if own_dir.exists() else 1
worker_src = (WORK / "worker" / "worker.py").read_text(errors="ignore") if (WORK / "worker" / "worker.py").exists() else ""
main_src = (WORK / "backend" / "main.py").read_text(errors="ignore") if (WORK / "backend" / "main.py").exists() else ""
readme = (WORK / "README.md").read_text(errors="ignore").lower() if (WORK / "README.md").exists() else ""
checks = {
    "tsconfig_strict": strict,
    "package_layout": all((WORK / p).exists() for p in ("backend/__init__.py", "worker/__init__.py", "frontend/index.html", "frontend/src/main.ts")),
    "worker_has_main_and_module_entry": "def main" in worker_src and "__main__" in worker_src,
    "api_does_not_import_worker_processing": "process_next_job" not in main_src,
    "requirements_txt": (WORK / "requirements.txt").exists(),
    "readme_covers_api_worker_frontend": all(k in readme for k in ("uvicorn", "worker", "tsc")),
    "own_tests_exist": own_dir.exists() and count_test_functions(own_dir) >= 3,
    "own_tests_pass": own_code == 0,
}
emit(tests, checks)
