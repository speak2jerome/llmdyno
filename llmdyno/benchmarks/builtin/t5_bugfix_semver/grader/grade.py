import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, "/grader_common")
from grading import WORK, count_test_functions, emit, pytest_results, run  # noqa: E402

HERE = Path(__file__).parent
ORIGINAL = Path("/task/workspace")

tests, _, _ = pytest_results([HERE / "tests"])

own_code = run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--timeout=60", "tests"], timeout=300)[0]
basic_same = (WORK / "tests" / "test_basic.py").exists() and hashlib.sha256(
    (WORK / "tests" / "test_basic.py").read_bytes()).digest() == hashlib.sha256(
    (ORIGINAL / "tests" / "test_basic.py").read_bytes()).digest()
issues_file = WORK / "tests" / "test_issues.py"
issues_src = issues_file.read_text(errors="ignore") if issues_file.exists() else ""
changelog = (WORK / "CHANGELOG.md").read_text(errors="ignore") if (WORK / "CHANGELOG.md").exists() else ""
unreleased = changelog.split("## Unreleased", 1)[1].split("\n## ", 1)[0] if "## Unreleased" in changelog else ""
checks = {
    "repo_tests_pass": own_code == 0,
    "test_basic_unchanged": basic_same,
    "regression_test_file_added": issues_file.exists() and count_test_functions(WORK / "tests") > count_test_functions(ORIGINAL / "tests"),
    "regression_tests_cover_all_issues": issues_file.exists() and all(
        re.search(p, issues_src, re.I) for p in (r"rc\.10|beta\.11|\.10\b|prerelease|pre_release", r"\+build|\+[a-z0-9]|build", r"\^0\.")),
    "changelog_entries_reference_issues": all(f"#{n}" in unreleased for n in (12, 15, 17)),
    "issue_md_untouched": (WORK / "ISSUE.md").exists(),
}
emit(tests, checks)
