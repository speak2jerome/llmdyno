"""Library parity: runs (transcript, files, logs, telemetry), plan actions, every Results view and export, judging.
A finished run is written to disk the way the runner leaves it, so no Docker or model is needed."""
import json
import time
import zipfile

import pytest

import llmdyno

T0 = time.time() - 120


def _events():
    tool = {"type": "tool_call", "id": "call_1", "name": "bash", "args": json.dumps({"command": "ls"})}
    return [
        {"t": T0, "seq": 1, "ev": "request", "conv": "c1", "model": "local-model", "n_messages": 1,
         "new": [{"role": "user", "blocks": [{"type": "text", "text": "Write hello.py"}]}]},
        {"t": T0 + 1, "seq": 1, "ev": "block_start", "index": "think", "type": "thinking"},
        {"t": T0 + 1, "seq": 1, "ev": "delta", "index": "think", "text": "Let me look"},
        {"t": T0 + 2, "seq": 1, "ev": "response", "status": 200, "finish": "tool_calls",
         "blocks": [{"type": "thinking", "text": "Let me look"}, tool],
         "usage": {"input": 100, "cached": 0, "output": 20, "reasoning": 0}, "ttft_s": 0.5, "wall_s": 2.0,
         "cost_usd": 0.001},
        {"t": T0 + 3, "seq": 2, "ev": "request", "conv": "c1", "model": "local-model", "n_messages": 3,
         "new": [{"role": "assistant", "blocks": [tool]},
                 {"role": "tool", "blocks": [{"type": "tool_result", "id": "call_1", "name": "bash", "text": "README.md"}]}]},
        {"t": T0 + 5, "seq": 2, "ev": "response", "status": 200, "finish": "stop",
         "blocks": [{"type": "text", "text": "Done: hello.py prints hi."}],
         "usage": {"input": 150, "cached": 100, "output": 30, "reasoning": 0}, "ttft_s": 0.4, "wall_s": 1.5,
         "cost_usd": 0.002},
    ]


@pytest.fixture(scope="module")
def finished(tmp_path_factory):
    from llmdyno import config, db
    pid, rid, prof = "plan_sdk_runs", "run_sdk_runs_1", "prof_sdk_runs"
    plan_dir = config.path("runs_dir") / pid
    run_dir = plan_dir / rid
    (run_dir / "workspace").mkdir(parents=True)
    (run_dir / "workspace" / "hello.py").write_bytes(b"print('hi')\n")
    (run_dir / "workspace" / "data.bin").write_bytes(b"\0\1" * 50)
    (run_dir / "transcript.jsonl").write_text("".join(json.dumps(e) + "\n" for e in _events()))
    (run_dir / "proxy.jsonl").write_text(json.dumps({"seq": 1, "usage_norm": {"input": 100}, "cost_usd": 0.001}) + "\n")
    (run_dir / "stdout_stage1.log").write_bytes(b"agent says hello\n")
    (plan_dir / f"gpu_{prof}.jsonl").write_text(json.dumps({"ts": T0 + 10, "util": 90, "vram_used_mib": 9000}) + "\n")
    with db.Session() as s:
        s.add(db.Plan(id=pid, name="SDK runs plan", profile_ids=[prof], harness_ids=["pi"], benchmark_ids=["t0_smoke_cli"],
                      iterations=1, options={}, status="done", created_at=T0, started_at=T0, ended_at=T0 + 60))
        s.add(db.Run(id=rid, plan_id=pid, profile_id=prof, harness_id="pi", benchmark_id="t0_smoke_cli", iteration=1,
                     status="done", dir=str(run_dir), started_at=T0, ended_at=T0 + 60, correctness=1.0,
                     instruction_following=1.0, wall_s=60, cost_usd=0.003, metrics={"tests_passed": 3, "tests_total": 3}))
        s.commit()
    yield llmdyno.run(rid)
    try:
        llmdyno.plan(pid).delete()
    except llmdyno.NotFoundError:
        pass


def test_run_details_and_transcript(finished):
    assert finished.correctness == 1.0 and finished.status == "done" and finished.plan().id == "plan_sdk_runs"
    t = finished.transcript()
    assert isinstance(t, llmdyno.Transcript) and len(t) == 6
    assert [x["finish"] for x in t.turns()] == ["tool_calls", "stop"]
    calls = t.tool_calls()
    assert calls == [{"seq": 1, "id": "call_1", "name": "bash", "args": {"command": "ls"}, "result": "README.md"}]
    assert t.thinking() == ["Let me look"] and t.final_text() == "Done: hello.py prints hi."
    u = t.usage()
    assert u["calls"] == 2 and u["input"] == 250 and u["output"] == 50 and u["cost_usd"] == pytest.approx(0.003)
    assert "2 model calls" in repr(t)
    assert finished.transcript(start=3, limit=1)[0]["ev"] == "response"


def test_run_files_logs_telemetry_and_download(finished, tmp_path):
    assert {f["path"] for f in finished.files()} == {"hello.py", "data.bin"}
    assert finished.read_file("hello.py") == "print('hi')\n"
    assert finished.read_file("data.bin") == "(binary file)"
    with pytest.raises(llmdyno.NotFoundError):
        finished.read_file("../../settings.json")
    assert finished.log() == "agent says hello\n" and finished.log(2, "stderr") == ""
    with pytest.raises(llmdyno.InvalidError):
        finished.log(stream="secrets")
    assert finished.requests()[0]["cost_usd"] == 0.001
    assert finished.gpu()[0]["util"] == 90
    z = finished.download(tmp_path / "ws.zip")
    assert z == tmp_path / "ws.zip" and "workspace/hello.py" in zipfile.ZipFile(z).namelist()


def test_run_actions_go_to_the_services(recorder):
    recorder.replies.update({
        "runs.get_run": lambda rid: {"id": rid, "plan_id": "plan_x", "status": "done"},
        "runs.cancel_run": {"ok": True}, "runs.retry_run": {"ok": True, "job_id": "job_plan"},
        "runs.regrade_run": {"job_id": "job_rg"},
        "system.get_job": lambda jid: {"id": jid, "status": "done", "title": "Re-grade", "result": {}},
        "plans.retry_plan": {"requeued": 2, "job_id": "job_retry"},
    })
    r = llmdyno.run("run_x")
    r.cancel()
    assert r.retry() == llmdyno.Job("job_plan")
    assert r.regrade(quiet=True) == r
    assert llmdyno.Plan("plan_x").retry(wait=False, quiet=True) == 2
    assert ("plans.retry_plan", {"pid": "plan_x", "body": {"statuses": ["failed", "cancelled"]}}) in recorder.calls


def test_plan_rename_runs_and_delete(finished):
    p = llmdyno.plan("plan_sdk_runs")
    assert p.rename("Renamed plan").name == "Renamed plan"
    assert [r.id for r in p.get_runs()] == ["run_sdk_runs_1"]
    with pytest.raises(llmdyno.ConflictError, match="nothing to retry"):
        p.retry(quiet=True)


@pytest.fixture()
def sample():
    was = llmdyno.sample_status()["loaded"]
    pid = llmdyno.load_sample()
    yield pid
    if not was:
        llmdyno.unload_sample()


def test_every_results_view_and_option(sample, tmp_path):
    r = llmdyno.results(sample)
    cells = r.cells()
    assert len(cells) == 75 and {"profile", "harness", "benchmark_id", "pass_rate"} <= set(cells[0])
    assert r.rubric() and "readability" in r.rubric()[0]
    assert len(r.agreement()["judges"]) == 2 and len(r.reviews()) == 150
    assert {"profile", "aa_score"} <= set(r.reference()[0])
    only = llmdyno.results(sample, benchmarks=["t5_bugfix_semver"])
    assert {c["benchmark_id"] for c in only.cells()} == {"t5_bugfix_semver"}
    strict = llmdyno.results(sample, pass_threshold=1.0, quality_weights={"review": 100, "static": 0, "probes": 0})
    assert strict.data["pass_threshold"] == 1.0 and strict.data["quality_weights"]["review"] == 100
    csv_text = r.export(tmp_path / "configs.csv", level="configs")
    assert csv_text.splitlines()[0].startswith("profile") and (tmp_path / "configs.csv").exists()
    doc = json.loads(only.export(level="cells", fmt="json"))
    assert doc["level"] == "cells" and doc["weights"] == r.data["weights"]
    assert {row["benchmark_id"] for row in doc["rows"]} == {"t5_bugfix_semver"}


def test_judging_defaults_list_and_delete(sample):
    d = llmdyno.judge_defaults()
    assert d["rubric"] and d["guidance"] and d["blind"] is True
    try:
        assert len(llmdyno.reviews(plan=sample)) == 150
        one = llmdyno.reviews(run="run_sample_cloud_gpt_6_luna_t1_")
        assert len(one) == 2 and {x["run_id"] for x in one} == {"run_sample_cloud_gpt_6_luna_t1_"}
        assert llmdyno.delete_reviews("judge_sample_luna", plan=sample) == 75
        assert len(llmdyno.reviews(plan=sample)) == 75
    finally:                                              # put the sample back as it was
        llmdyno.unload_sample()
        llmdyno.load_sample()


def test_review_options_reach_the_judge(recorder):
    recorder.replies.update({
        "profiles.list_profiles": [{"id": "prof_judge", "name": "Judge", "kind": "cloud"}],
        "judging.start_judge": {"job_id": "job_j"},
        "system.get_job": {"id": "job_j", "status": "done", "title": "Judge", "result": {}},
        "runs.get_run": {"id": "run_a", "plan_id": "plan_a"},
        "settings.get_settings": {"weights": {"correctness": 50}, "quality_weights": {"review": 35}},
        "results.results": lambda **kw: {"configs": [], "runs": [], "labels": {}, "asked": kw},
    })
    res = llmdyno.review(judges="Judge", runs=["run_a"], rubric=[{"key": "tests"}], guidance="Be strict", quiet=True)
    body = dict(recorder.calls)["judging.start_judge"]["body"]
    assert body["run_ids"] == ["run_a"] and body["rubric"] == [{"key": "tests"}] and body["guidance"] == "Be strict"
    assert res.data["asked"]["plan_ids"] == "plan_a"
    assert isinstance(llmdyno.review("plan_a", "Judge", wait=False), llmdyno.Job)
