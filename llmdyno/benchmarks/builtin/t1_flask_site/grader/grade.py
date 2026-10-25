import sys
from pathlib import Path

sys.path.insert(0, "/grader_common")
from grading import WORK, count_test_functions, emit, pytest_results, run  # noqa: E402

HERE = Path(__file__).parent

tests, _, _ = pytest_results([HERE / "tests"])

own_tests_dir = WORK / "tests"
own_code, _, _ = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--timeout=60", "tests"],
                     timeout=300) if own_tests_dir.exists() else (1, "", "")
req = WORK / "requirements.txt"
readme = WORK / "README.md"
checks = {
    "app_factory_in_app_py": (WORK / "app.py").exists() and "def create_app" in (WORK / "app.py").read_text(errors="ignore"),
    "templates_dir_used": any((WORK / "templates").glob("*.html")) if (WORK / "templates").exists() else False,
    "requirements_txt_lists_flask": req.exists() and "flask" in req.read_text(errors="ignore").lower(),
    "readme_present": readme.exists() and len(readme.read_text(errors="ignore").strip()) > 40,
    "at_least_3_own_tests": own_tests_dir.exists() and count_test_functions(own_tests_dir) >= 3,
    "own_tests_pass": own_code == 0,
}
emit(tests, checks)
