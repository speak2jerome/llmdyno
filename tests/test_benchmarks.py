"""Built-in benchmarks load, custom benchmarks round-trip, and checks that would always pass are rejected."""
import pytest

from llmdyno.benchmarks import registry


def test_builtin_benchmarks_are_complete():
    builtin = [b for b in registry.all_benchmarks() if b["builtin"]]
    assert {b["id"] for b in builtin} >= {"t0_smoke_cli", "t1_flask_site", "t5_bugfix_semver"}
    for b in builtin:
        assert b["title"] and b["stages"], b["id"]
        assert all(s.get("timeout_s") for s in b["stages"]), b["id"]
        assert len(registry.prompt_texts(b)) == len(b["stages"])


def test_builtin_benchmarks_are_read_only():
    with pytest.raises(PermissionError):
        registry.delete_custom("t0_smoke_cli")


@pytest.mark.parametrize("check,ok", [
    ({"type": "file_exists", "path": "app.py"}, True),
    ({"type": "file_exists", "path": ""}, False),
    ({"type": "file_exists", "path": "."}, False),
    ({"type": "file_contains", "path": "app.py"}, False),
    ({"type": "glob", "pattern": "*"}, False),
    ({"type": "command", "cmd": "python -m pytest -q"}, True),
    ({"type": "nonsense"}, False),
])
def test_check_validation(check, ok):
    assert (registry.check_errors([check]) == []) is ok


def spec(bid):
    return {"id": bid, "title": "Tiny task", "summary": "s", "description": "d", "category": "cli", "difficulty": "easy",
            "languages": ["python"], "tags": [], "stages": [{"prompt": "Write hello.py that prints hi.", "timeout_s": 300}],
            "workspace_files": {"README.md": "# task\n"}, "hidden_tests": {},
            "checks": [{"name": "exists", "type": "file_exists", "path": "hello.py"}], "reference_files": {"hello.py": "print('hi')\n"}}


def test_custom_benchmark_round_trip():
    registry.save_custom(spec("tiny_task"))
    b = registry.get("tiny_task")
    assert b["title"] == "Tiny task" and not b["builtin"]
    with pytest.raises(FileExistsError):
        registry.save_custom(spec("tiny_task"))
    registry.delete_custom("tiny_task")
    with pytest.raises(KeyError):
        registry.get("tiny_task")


def test_custom_benchmark_rejects_empty_check():
    bad = spec("bad_task")
    bad["checks"] = [{"type": "file_exists", "path": ""}]
    with pytest.raises(ValueError, match="path is required"):
        registry.save_custom(bad)
