"""Library parity: harnesses, custom manifests, Dockerfiles, previews and runtimes (no Docker builds)."""
import pytest

import llmdyno

MANIFEST = {"id": "sdk-echo", "name": "SDK echo agent", "install": ["RUN echo installed"],
            "command": 'echo "$PROMPT" > answer.txt', "apis": ["openai-chat"], "multi_stage": "fresh",
            "files": {".config/echo.json": "{}"}}


def test_builtin_harnesses_and_details():
    pi = llmdyno.harness("pi")
    assert pi in llmdyno.list_harnesses() and pi.builtin and "openai-chat" in pi.apis
    assert llmdyno.harness("Pi") == pi
    assert "FROM" in pi.dockerfile()
    prev = pi.preview("anthropic")
    assert prev["command"] and prev["api_style"] in pi.apis
    schema = llmdyno.harness_schema()
    assert isinstance(schema, dict) and schema
    with pytest.raises(llmdyno.LLMDynoError, match="built in"):
        pi.delete()
    with pytest.raises(llmdyno.NotFoundError):
        llmdyno.harness("no-such-harness")


def test_custom_harness_lifecycle(tmp_path):
    import json
    (tmp_path / "echo.json").write_text(json.dumps(MANIFEST))
    h = llmdyno.add_harness(tmp_path / "echo.json")
    try:
        assert h.id == "sdk-echo" and not h.builtin and h.status in ("missing", "ready")
        assert "RUN echo installed" in h.dockerfile()
        h.update({**MANIFEST, "name": "SDK echo agent v2"})
        assert h.name == "SDK echo agent v2"
        with pytest.raises(llmdyno.InvalidError, match="PROMPT"):
            h.update({**MANIFEST, "command": "echo hi"})
        with pytest.raises(llmdyno.InvalidError, match="exists"):
            llmdyno.add_harness(MANIFEST)
    finally:
        h.delete()
    assert h.id not in {x.id for x in llmdyno.list_harnesses()}


def test_builds_and_runtimes_go_through_jobs(recorder):
    recorder.replies.update({
        "harnesses.list_harnesses": [{"id": "pi", "name": "Pi", "status": "ready", "builtin": True}],
        "harnesses.build_harness": {"job_id": "job_b"},
        "harnesses.build_harness_runtime": lambda hid, body: {"job_id": "job_rt"},
        "harnesses.harness_runtime": lambda hid, platform: {"platform": platform or "linux/amd64", "built": False},
        "harnesses.remove_harness_image": {"ok": True},
        "system.get_job": lambda jid: {"id": jid, "status": "done", "title": "Build", "result": {"platform": "linux/arm64"}},
    })
    pi = llmdyno.harness("pi")
    assert pi.build(quiet=True).status == "ready"
    assert isinstance(pi.build(wait=False), llmdyno.Job)
    assert pi.runtime("linux/arm64") == {"platform": "linux/arm64", "built": False}
    assert pi.build_runtime("linux/arm64", quiet=True) == {"platform": "linux/arm64"}
    pi.remove_image()
    assert ("harnesses.build_harness_runtime", {"hid": "pi", "body": {"platform": "linux/arm64"}}) in recorder.calls
