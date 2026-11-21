"""SWE-bench, Aider polyglot and Artificial Analysis adapters, plus the portable harness runtimes."""
import json

import pytest

from llmdyno.benchmarks import artificial_analysis as aa
from llmdyno.benchmarks import envs, polyglot, swebench
from llmdyno.harnesses import catalog, runtime

ROW = {
    "instance_id": "django__django-11099", "repo": "django/django", "version": "3.0",
    "base_commit": "d26b2424437dabeeca94d7900b37d2df4410da0c", "environment_setup_commit": "419a78300f7cd27611196e1e464d50fd0385ff27",
    "image": "swebench/sweb.eval.x86_64.django_1776_django-11099:latest",
    "eval_script": "#!/bin/bash\nset -uxo pipefail\ncd /testbed\n./tests/runtests.py auth_tests.test_validators\n",
    "log_parser": "parse_log_django", "eval_type": "pass_and_fail",
    "problem_statement": "UsernameValidator allows trailing newline in usernames\nDescription\n...",
    "patch": "diff --git a/django/contrib/auth/validators.py b/django/contrib/auth/validators.py\n--- a/x\n+++ b/x\n",
    "test_patch": "diff --git a/tests/auth_tests/test_validators.py b/tests/auth_tests/test_validators.py\n--- a/x\n+++ b/x\n",
    "FAIL_TO_PASS": json.dumps(["test_ascii_validator (auth_tests.test_validators.UsernameValidatorsTests)"]),
    "PASS_TO_PASS": json.dumps(["test_help_text (auth_tests.test_validators.MinimumLengthValidatorTest)",
                                "test_validate (auth_tests.test_validators.MinimumLengthValidatorTest)"]),
    "difficulty": "<15 min fix", "created_at": "2019-03-20T03:46:18Z",
}


# ------------------------------------------------------------------ SWE-bench
def test_swebench_row_becomes_a_benchmark():
    bench, files = swebench.row_to_benchmark(ROW, "verified")
    assert bench["id"] == "swe_django__django_11099"
    assert bench["env"]["image"] == ROW["image"] and bench["env"]["platform"] == "linux/amd64"
    assert bench["env"]["workspace"] == "volume" and bench["env"]["repo_dir"] == "/testbed"
    assert bench["grader"]["type"] == "swebench"
    assert bench["swebench"]["fail_to_pass"] == 1 and bench["swebench"]["pass_to_pass"] == 2
    assert bench["swebench"]["test_files"] == ["tests/auth_tests/test_validators.py"]
    inst = json.loads(files["grader/instance.json"])
    assert isinstance(inst["FAIL_TO_PASS"], list) and inst["eval_script"].startswith("#!/bin/bash")
    prompt = files["prompts/stage1.md"]
    assert "UsernameValidator allows trailing newline" in prompt and "/testbed" in prompt
    assert "test_patch" not in prompt and ROW["patch"] not in prompt        # the agent never sees tests or the fix
    assert files["reference/gold.patch"] == ROW["patch"]


def test_swebench_row_without_harness_fields_is_rejected():
    with pytest.raises(ValueError, match="eval_script"):
        swebench.row_to_benchmark({**ROW, "eval_script": None}, "lite")


def report(resolved, f2p_fail=(), p2p_fail=(), applied=True):
    return {ROW["instance_id"]: {"resolved": resolved, "patch_successfully_applied": applied, "tests_status": {
        "FAIL_TO_PASS": {"success": [] if f2p_fail else ["t_f2p"], "failure": list(f2p_fail)},
        "PASS_TO_PASS": {"success": ["t_p1", "t_p2"], "failure": list(p2p_fail)}}}}


def test_harness_report_maps_to_a_grade():
    inst = {**ROW, "FAIL_TO_PASS": ["t_f2p"], "PASS_TO_PASS": ["t_p1", "t_p2"]}
    patch = "diff --git a/django/contrib/auth/validators.py b/django/contrib/auth/validators.py\n"
    g = swebench.report_to_grade(report(True), inst, patch, ROW["instance_id"])
    assert g["correctness"] == 1.0 and g["resolved"] and g["tests_passed"] == g["tests_total"] == 3
    assert g["checks"]["left the task's test files alone"] and g["instruction_following"] == 1.0
    g = swebench.report_to_grade(report(False, f2p_fail=["t_f2p"]), inst, patch, ROW["instance_id"])
    assert g["correctness"] == 0.0 and g["fail_to_pass"] == "0/1" and not g["f2p_all_pass"]


def test_editing_the_tests_is_flagged():
    inst = {**ROW, "FAIL_TO_PASS": ["t_f2p"], "PASS_TO_PASS": []}
    patch = "diff --git a/tests/auth_tests/test_validators.py b/tests/auth_tests/test_validators.py\n"
    g = swebench.report_to_grade(report(True), inst, patch, ROW["instance_id"])
    assert not g["checks"]["left the task's test files alone"]


def test_predictions_use_the_swebench_format(tmp_path):
    (tmp_path / "workspace").mkdir()
    (tmp_path / "workspace" / "model.patch").write_text("diff --git a/a b/a\n")
    run = {"dir": str(tmp_path), "benchmark_id": "swe_x", "label": "qwen__pi",
           "snapshot": {"benchmark": {"instance_id": "django__django-11099"}}}
    assert swebench.predictions([run]) == [{"instance_id": "django__django-11099", "model_name_or_path": "qwen__pi",
                                           "model_patch": "diff --git a/a b/a\n"}]


def test_env_spec_and_platform_detection():
    assert envs.image_platform("swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest") == "linux/amd64"
    assert envs.image_platform("swebench/sweb.eval.arm64.x:latest") == "linux/arm64"
    bench, _ = swebench.row_to_benchmark(ROW, "verified")
    e = envs.spec(bench)
    assert e["type"] == "swebench" and e["base_commit"] == ROW["base_commit"]
    assert envs.spec({"id": "plain"}) is None
    mounts = envs.workspace_mounts(e, "run_abc", "/host/ws")
    assert mounts == ["-v", f"{envs.ws_volume('run_abc')}:/testbed", "-v", f"{envs.ws_volume('run_abc')}:/workspace"]
    assert envs.patched_files("diff --git a/x.py b/x.py\n+1\ndiff --git a/y/z.py b/y/z.py\n") == ["x.py", "y/z.py"]


# ------------------------------------------------------------------ Aider polyglot
def make_exercise(root, lang, slug, cfg_files, files, docs="# Thing\n\nDo the thing."):
    d = root / lang / "exercises" / "practice" / slug
    (d / ".meta").mkdir(parents=True)
    (d / ".docs").mkdir()
    (d / ".docs" / "instructions.md").write_text(docs)
    (d / ".meta" / "config.json").write_text(json.dumps({"files": cfg_files, "blurb": "A blurb."}))
    for rel, text in files.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text)
    return d


def test_polyglot_python_exercise(tmp_path):
    d = make_exercise(tmp_path, "python", "zebra-puzzle",
                      {"solution": ["zebra_puzzle.py"], "test": ["zebra_puzzle_test.py"], "example": [".meta/example.py"]},
                      {"zebra_puzzle.py": "def drinks_water():\n    pass\n", "zebra_puzzle_test.py": "def test_x(): pass\n",
                       ".meta/example.py": "def drinks_water():\n    return 'Norwegian'\n"})
    bench, files = polyglot.exercise_to_benchmark("python", d)
    assert bench["id"] == "pg_python_zebra_puzzle" and bench["grader"]["type"] == "polyglot"
    assert bench["env"]["image"] == polyglot.IMAGE and bench["env"]["grader_in_env"]
    assert "workspace/zebra_puzzle.py" in files and "workspace/zebra_puzzle_test.py" in files
    assert "grader/tests/zebra_puzzle_test.py" in files
    assert files["reference/zebra_puzzle.py"].startswith(b"def drinks_water")
    assert not any(k.startswith("workspace/.meta") or k.startswith("workspace/.docs") for k in files)
    spec = json.loads(files["grader/spec.json"])
    assert spec == {"language": "python", "test_files": ["zebra_puzzle_test.py"], "solution_files": ["zebra_puzzle.py"],
                    "timeout_s": 480}
    assert "polyglot-test" in files["prompts/stage1.md"].decode()


def test_polyglot_enables_every_test():
    java = 'class T {\n  @Test\n  void a() {}\n\n  @Disabled("Remove to run test")\n  @Test\n  void b() {}\n}\n'
    assert "@Disabled" not in polyglot.enable_all_tests("java", java)
    js = "test('a', () => {});\nxtest('b', () => {});\n"
    assert polyglot.enable_all_tests("javascript", js) == "test('a', () => {});\ntest('b', () => {});\n"


def test_polyglot_java_reference_maps_by_file_name(tmp_path):
    d = make_exercise(tmp_path, "java", "bowling",
                      {"solution": ["src/main/java/BowlingGame.java"], "test": ["src/test/java/BowlingGameTest.java"],
                       "example": [".meta/src/reference/java/BowlingGame.java"]},
                      {"src/main/java/BowlingGame.java": "class BowlingGame {}", "build.gradle": "plugins {}",
                       "src/test/java/BowlingGameTest.java": '@Disabled("Remove to run test")\n@Test\nvoid x() {}\n',
                       ".meta/src/reference/java/BowlingGame.java": "class BowlingGame { int score() { return 0; } }"})
    bench, files = polyglot.exercise_to_benchmark("java", d)
    assert b"score()" in files["reference/src/main/java/BowlingGame.java"]
    assert b"@Disabled" not in files["workspace/src/test/java/BowlingGameTest.java"]
    ctx = tmp_path / "ctx"
    warm = polyglot.write_warm_context(tmp_path, ctx)
    assert warm["gradle_setups"] == 1 and (ctx / "polyglot-test.sh").exists()
    assert (ctx / "warm" / "java" / "g0" / "src" / "main" / "java" / "BowlingGame.java").read_text().count("score") == 1


def test_polyglot_cpp_builds_in_any_folder_and_hints_stay_out(tmp_path):
    cmake = ("cmake_minimum_required(VERSION 3.5.1)\n"
             "get_filename_component(exercise ${CMAKE_CURRENT_SOURCE_DIR} NAME)\n"
             'string(REPLACE "-" "_" file ${exercise})\n')
    d = make_exercise(tmp_path, "cpp", "all-your-base",
                      {"solution": ["all_your_base.cpp", "all_your_base.h"], "test": ["all_your_base_test.cpp"],
                       "example": [".meta/example.cpp", ".meta/example.h"]},
                      {"CMakeLists.txt": cmake, "all_your_base.cpp": "", "all_your_base.h": "",
                       "all_your_base_test.cpp": "TEST", ".meta/example.cpp": "int x;", ".meta/example.h": "#pragma once",
                       ".approaches/introduction.md": "Here is how to solve it", ".articles/perf/content.md": "fast way"})
    _, files = polyglot.exercise_to_benchmark("cpp", d)
    text = files["workspace/CMakeLists.txt"].decode()
    assert 'set(exercise "all-your-base")' in text and "get_filename_component(exercise" not in text
    assert not any(".approaches" in k or ".articles" in k for k in files)
    # two solution files, two examples: matched by extension
    assert files["reference/all_your_base.cpp"] == b"int x;" and files["reference/all_your_base.h"] == b"#pragma once"


def test_polyglot_rust_reference_uses_its_own_manifest(tmp_path):
    d = make_exercise(tmp_path, "rust", "grep",
                      {"solution": ["src/lib.rs", "Cargo.toml"], "test": ["tests/grep.rs"], "example": [".meta/example.rs"]},
                      {"src/lib.rs": "", "Cargo.toml": '[dependencies]\nanyhow = "1.0"\n', "tests/grep.rs": "",
                       ".meta/example.rs": "use thiserror::Error;", ".meta/Cargo-example.toml":
                       '[dependencies]\nanyhow = "1.0"\nthiserror = "1.0"\n'})
    _, files = polyglot.exercise_to_benchmark("rust", d)
    assert files["reference/src/lib.rs"] == b"use thiserror::Error;"
    assert b"thiserror" in files["reference/Cargo.toml"]
    warm = polyglot.write_warm_context(tmp_path, tmp_path / "ctx")
    assert warm["cargo_setups"] == 2          # the stub's manifest and the example's both get pre-fetched


def test_polyglot_go_editor_files_are_restored_like_tests(tmp_path):
    d = make_exercise(tmp_path, "go", "alphametics",
                      {"solution": ["alphametics.go"], "test": ["alphametics_test.go"], "editor": ["cases_test.go"],
                       "example": [".meta/example.go"]},
                      {"alphametics.go": "package alphametics", "alphametics_test.go": "package alphametics",
                       "cases_test.go": "var cases = 1", "go.mod": "module alphametics", ".meta/example.go": "package x"})
    _, files = polyglot.exercise_to_benchmark("go", d)
    assert "grader/tests/cases_test.go" in files
    assert json.loads(files["grader/spec.json"])["test_files"] == ["alphametics_test.go", "cases_test.go"]


# ------------------------------------------------------------------ Artificial Analysis
ITEM = {"id": "a1", "name": "Qwen3 Coder 30B A3B Instruct", "slug": "qwen3-coder-30b-a3b-instruct", "release_date": "2025-07-31",
        "model_creator": {"id": "c1", "name": "Alibaba"},
        "evaluations": {"artificial_analysis_intelligence_index": 33.4, "artificial_analysis_coding_index": None,
                        "livecodebench": 0.40},
        "pricing": {"price_1m_input_tokens": 0.45, "price_1m_output_tokens": 2.25},
        "performance_v3": {"mean_output_tokens_per_second": 95.2, "mean_time_to_first_token_seconds": 1.1}}


def test_aa_item_normalisation_and_blend():
    m = aa.normalize(ITEM)
    assert m["intelligence_index"] == 33.4 and m["coding_index"] is None
    assert m["price_blended"] == round((3 * 0.45 + 2.25) / 4, 4)
    assert m["output_tps"] == 95.2 and m["ttft_s"] == 1.1 and m["creator"] == "Alibaba"
    assert m["url"].endswith("/models/qwen3-coder-30b-a3b-instruct")
    assert aa.blended(None, 2.0) is None


def test_aa_matching_by_model_name():
    models = [aa.normalize(ITEM), aa.normalize({**ITEM, "id": "a2", "name": "Qwen3 32B", "slug": "qwen3-32b"}),
              aa.normalize({**ITEM, "id": "a3", "name": "GPT-5 mini", "slug": "gpt-5-mini", "model_creator": {"name": "OpenAI"}})]
    local = {"name": "Qwen3 Coder 30B Q4", "model": "Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf", "vendor": None}
    assert aa.match(local, models)["model"]["slug"] == "qwen3-coder-30b-a3b-instruct"
    cloud = {"name": "GPT-5 mini (low)", "model": "gpt-5-mini", "vendor": "openai"}
    assert aa.match(cloud, models)["model"]["slug"] == "gpt-5-mini"
    assert aa.match({"name": "Llama 3.1 8B", "model": "llama-3.1-8b"}, models) is None
    forced = aa.match(local, models, override="qwen3-32b")
    assert forced["manual"] and forced["model"]["slug"] == "qwen3-32b"


# ------------------------------------------------------------------ portable runtimes
def test_runtime_install_stays_inside_the_prefix():
    for h in catalog.BUILTIN:
        text = "\n".join(h.runtime_install())
        assert "/usr/local/bin" not in text and "/opt/xdg-cache" not in text, h.id
    assert catalog.BY_ID["opencode"].runtime_env()["XDG_CACHE_HOME"] == f"{catalog.RT}/xdg-cache"
    assert "uv venv --python 3.12" in catalog.BY_ID["aider"].runtime_install()[0]
    df = runtime.dockerfile(catalog.BY_ID["pi"])
    assert df.startswith("FROM node:24-bookworm-slim AS node") and "FROM ubuntu:22.04" in df
    assert runtime.tag(catalog.BY_ID["pi"], "linux/amd64").startswith("llmdyno-rt-pi:1.4.0-amd64-")


def test_sandbox_harness_images_are_unchanged():
    # existing users' harness images must stay valid: the sandbox install lines may not move
    assert catalog.BY_ID["aider"].install()[0].startswith("RUN python -m venv /opt/aider")
    assert catalog.BY_ID["mini-swe-agent"].install()[0].endswith("ln -sf /opt/mini/bin/mini /usr/local/bin/mini")
