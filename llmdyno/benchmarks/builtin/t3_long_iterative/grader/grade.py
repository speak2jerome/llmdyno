import hashlib
import os
import sys
from pathlib import Path

sys.path.insert(0, "/grader_common")
from grading import WORK, count_test_functions, emit, pytest_results, run  # noqa: E402

HERE = Path(__file__).parent
TESTS = HERE / "tests"
STAGE = int(os.environ.get("STAGE", "5"))

files = [TESTS / f"test_h{k}.py" for k in range(1, STAGE + 1)]
if STAGE <= 3:  # JSON storage format only applies before the SQLite switch in step 4
    files += [TESTS / "test_h1_jsonformat.py"] + ([TESTS / "test_h2_jsonformat.py"] if STAGE >= 2 else [])
tests, _, _ = pytest_results(files, tag=f"s{STAGE}")

visible = [f"tests/test_step{k}.py" for k in range(1, STAGE + 1)]
vis_code = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--timeout=60", *visible],
               timeout=300)[0]
own_code = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--timeout=60", "tests"],
               timeout=300)[0]

# Visible test files must not be deleted. Steps 1-4 tests may only change in step 5 (Decimal switch).
stage_files = Path(os.environ.get("STAGE_FILES", "/task/stage_files"))
untouched = True
for k in range(1, STAGE + 1):
    for src in (stage_files / f"stage{k}").rglob("*.py"):
        dst = WORK / src.relative_to(stage_files / f"stage{k}")
        if not dst.exists():
            untouched = False
        elif STAGE < 5 and hashlib.sha256(dst.read_bytes()).digest() != hashlib.sha256(src.read_bytes()).digest():
            untouched = False

own_count = count_test_functions(WORK / "tests") - sum(
    count_test_functions(stage_files / f"stage{k}" / "tests") for k in range(1, STAGE + 1))
checks = {
    "visible_tests_pass": vis_code == 0,
    "all_repo_tests_pass": own_code == 0,
    "visible_tests_kept": untouched,
    "added_own_tests": own_count >= STAGE,
    "package_layout": all((WORK / "inventory" / f).exists() for f in ("models.py", "errors.py", "store.py")),
}
emit(tests, checks, {"stage": STAGE})
