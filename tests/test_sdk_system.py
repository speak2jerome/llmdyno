"""Library parity: system, jobs, settings, weights and the bundled sample."""
import pytest

import llmdyno


def test_specs_and_gpu_readings():
    s = llmdyno.specs()
    assert {"cpu", "memory", "gpus", "docker"} <= set(s)
    assert isinstance(llmdyno.gpu_usage(), (list, dict))
    assert isinstance(llmdyno.active_work(), dict)


def test_machine_wide_actions_call_the_right_services(recorder):
    recorder.replies.update({
        "system.system_panic": {"cancelled_jobs": 0}, "system.cleanup_containers": {"removed": 2},
        "system.dep_action": lambda dep_id, body: {"message": f"{dep_id}:{body['action']}", "job_id": "job_x",
                                                    "llama_cpp": {"path": body.get("path")}},
        "system.get_job": {"id": "job_x", "status": "done", "title": "Install", "result": {"ok": 1}},
    })
    assert llmdyno.panic() == {"cancelled_jobs": 0}
    assert llmdyno.cleanup() == 2
    assert llmdyno.start_docker() == "docker:start_docker"
    assert llmdyno.repair_docker() == "docker:repair_docker"
    assert llmdyno.install_docker(quiet=True) == {"ok": 1}
    assert llmdyno.use_llama_cpp("D:/llama") == {"path": "D:/llama"}
    assert recorder.ops()[:2] == ["system.system_panic", "system.cleanup_containers"]


def test_jobs_list_and_clear():
    from llmdyno import jobs
    jid = jobs.submit("test", "Listed job", lambda ctx: ctx.log("hi"))
    llmdyno.job(jid).wait(quiet=True)
    listed = llmdyno.list_jobs(kind="test")
    assert any(j.id == jid for j in listed) and all(isinstance(j, llmdyno.Job) for j in listed)
    assert all(j["kind"] == "test" for j in listed)
    assert llmdyno.list_jobs(active=True, kind="test") == []
    assert llmdyno.clear_jobs() >= 1
    assert not any(j.id == jid for j in llmdyno.list_jobs())
    with pytest.raises(llmdyno.ConflictError, match="not active"):
        llmdyno.Job("job_from_another_process").cancel()


def test_waiting_on_an_interrupted_job_ends():
    """A server restart marks running jobs "interrupted"; wait() must raise instead of polling forever."""
    from llmdyno import db, jobs
    jid = jobs.submit("test", "Restarted job", lambda ctx: None)
    llmdyno.job(jid).wait(quiet=True)
    with db.Session() as s:
        s.get(db.Job, jid).status = "running"
        s.commit()
    jobs.mark_interrupted()
    with pytest.raises(llmdyno.LLMDynoError, match="interrupted: server restarted"):
        llmdyno.job(jid).wait(quiet=True)


def test_settings_read_update_and_validate():
    s = llmdyno.settings()
    before = s.cloud_concurrency
    assert s["weights"]["correctness"] == s.weights["correctness"] and s.data_dir == str(llmdyno.data_dir())
    try:
        assert s.update(cloud_concurrency=5).cloud_concurrency == 5
        assert llmdyno.settings().cloud_concurrency == 5
        with pytest.raises(llmdyno.InvalidError, match="1-16"):
            s.update(cloud_concurrency=99)
        with pytest.raises(TypeError, match="cannot change"):
            s.update(port=1)
        with pytest.raises(AttributeError):
            s.no_such_setting  # noqa: B018
    finally:
        s.update(cloud_concurrency=before)


def test_hf_token_round_trip():
    llmdyno.set_hf_token("hf_test_not_real")
    assert llmdyno.settings().hf_token_set
    llmdyno.remove_hf_token()
    assert not llmdyno.settings().hf_token_set


def test_saved_weights_feed_results():
    before = llmdyno.settings().weights
    try:
        saved = llmdyno.save_weights(correctness=80, quality=10)
        assert saved["weights"]["correctness"] == 80 and saved["weights"]["efficiency"] == before["efficiency"]
        assert llmdyno.settings().weights["correctness"] == 80
    finally:
        llmdyno.save_weights(**before)


def test_sample_load_status_unload():
    was = llmdyno.sample_status()["loaded"]
    pid = llmdyno.load_sample()
    assert pid == "plan_sample_round1" and llmdyno.load_sample() == pid      # loading twice is fine
    assert llmdyno.sample_status() == {"available": True, "loaded": True, "plan_id": pid}
    if not was:
        llmdyno.unload_sample()
        assert not llmdyno.sample_status()["loaded"]
