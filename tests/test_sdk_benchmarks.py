"""Library parity: benchmarks you create, edit, duplicate, export and import; suites; the public-benchmark imports."""
import pytest

import llmdyno


def spec(bid, title="SDK tiny task"):
    return {"id": bid, "title": title, "summary": "s", "description": "d", "category": "cli", "difficulty": "easy",
            "languages": ["python"], "tags": ["sdk"], "stages": [{"prompt": "Write hello.py that prints hi.",
                                                                  "timeout_s": 300}],
            "workspace_files": {"README.md": "# task\n"}, "hidden_tests": {},
            "checks": [{"name": "exists", "type": "file_exists", "path": "hello.py"}],
            "reference_files": {"hello.py": "print('hi')\n"}}


def test_builtin_benchmark_details_are_read_only():
    b = llmdyno.benchmark("t0_smoke_cli")
    assert b.builtin and b.title and b.prompts and b["n_stages"] == len(b.prompts)
    with pytest.raises(llmdyno.ForbiddenError, match="read-only"):
        b.spec()
    with pytest.raises(llmdyno.ForbiddenError):
        b.update(spec("t0_smoke_cli"))
    with pytest.raises(llmdyno.NotFoundError):
        llmdyno.benchmark("no_such_benchmark")


def test_custom_benchmark_round_trip(tmp_path):
    b = llmdyno.create_benchmark(spec("sdk_tiny"))
    try:
        assert b.id == "sdk_tiny" and not b.builtin
        assert any(x["id"] == "sdk_tiny" for x in llmdyno.list_benchmarks(search="sdk tiny"))
        assert b.spec()["stages"][0]["prompt"].startswith("Write hello.py")
        assert b.update(spec("sdk_tiny", title="SDK tiny task v2")).title == "SDK tiny task v2"
        with pytest.raises(llmdyno.ConflictError):
            llmdyno.create_benchmark(spec("sdk_tiny"))
        copy = b.duplicate("sdk_tiny_copy")
        assert copy.id == "sdk_tiny_copy" and copy.title == b.title + " (copy)"
        zipped = copy.export(tmp_path / "copy.zip")
        assert zipped[:2] == b"PK" and (tmp_path / "copy.zip").read_bytes() == zipped
        copy.delete()
        back = llmdyno.import_benchmark(tmp_path / "copy.zip")
        assert back.id == "sdk_tiny_copy" and back["origin"] == "imported"
        with pytest.raises(llmdyno.ConflictError, match="already exists"):
            llmdyno.import_benchmark(zipped)
        back.delete()
        with pytest.raises(llmdyno.InvalidError):
            llmdyno.import_benchmark(b"not a zip at all")
    finally:
        b.delete()


def test_suites():
    s = llmdyno.create_suite("SDK suite", [llmdyno.benchmark("t0_smoke_cli"), "t5_bugfix_semver"], "for the tests")
    try:
        assert s.benchmark_ids == ["t0_smoke_cli", "t5_bugfix_semver"] and llmdyno.suite(s.id) == s
        s.update(name="SDK suite 2", benchmarks=["t0_smoke_cli"])
        assert s.name == "SDK suite 2" and s.benchmark_ids == ["t0_smoke_cli"]
        with pytest.raises(llmdyno.InvalidError, match="unknown benchmarks"):
            llmdyno.create_suite("Bad", ["nope"])
        with pytest.raises(llmdyno.ForbiddenError):
            llmdyno.suite("suite_quick").delete()
    finally:
        s.delete()
    with pytest.raises(llmdyno.NotFoundError):
        s.refresh()


def test_imports_catalog_and_jobs(recorder):
    recorder.replies.update({
        "imports.import_catalog": {"swebench": {"imported": 0}, "polyglot": {"imported": 0}},
        "imports.install_swebench_harness": {"job_id": "job_h"},
        "imports.build_polyglot_image": {"job_id": "job_i"},
        "imports.remove_imported": lambda kind: {"removed": 3 if kind == "polyglot" else 0},
        "benchmarks.validate_benchmark": lambda bid: {"job_id": "job_v"},
        "system.get_job": lambda jid: {"id": jid, "status": "done", "title": jid, "result": {"job": jid}},
    })
    assert llmdyno.import_catalog()["swebench"]["imported"] == 0
    assert llmdyno.install_swebench_harness(quiet=True) == {"job": "job_h"}
    assert llmdyno.build_polyglot_image(quiet=True) == {"job": "job_i"}
    assert llmdyno.remove_imported("polyglot") == 3
    assert llmdyno.Benchmark({"id": "t0_smoke_cli", "title": "x"}).validate(quiet=True) == {"job": "job_v"}


def test_import_catalog_shape_without_docker_calls():
    cat = llmdyno.import_catalog()
    assert {"swebench", "polyglot"} <= set(cat) and cat["swebench"]["datasets"]
