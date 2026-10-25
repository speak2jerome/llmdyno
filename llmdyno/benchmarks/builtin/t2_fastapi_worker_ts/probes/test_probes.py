"""Beyond-spec robustness probes for the FastAPI + worker task."""
import importlib
import sys
import threading

import pytest


def fresh(name):
    for m in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
        sys.modules.pop(m)
    return importlib.import_module(name)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    db = str(tmp_path / "jobs.db")
    monkeypatch.setenv("JOBS_DB", db)
    from fastapi.testclient import TestClient
    main = fresh("backend.main")
    worker = fresh("worker.worker")
    with TestClient(main.app) as c:
        yield c, worker, db


def test_concurrent_workers_never_double_process(env):
    client, worker, db = env
    ids = [client.post("/api/jobs", json={"text": f"job {i}", "operation": "uppercase"}).json()["id"] for i in range(20)]
    claimed = []
    errors = []

    def run():
        while True:
            try:
                if not worker.process_next_job(db):
                    return
                claimed.append(1)
            except Exception as e:  # e.g. "database is locked"
                errors.append(repr(e))
                return

    threads = [threading.Thread(target=run) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not errors, errors[:3]
    assert len(claimed) == 20
    assert all(client.get(f"/api/jobs/{i}").json()["status"] == "done" for i in ids)


def test_text_preserved_exactly(env):
    client, _, _ = env
    text = "line one\n\tline two — ünïcode ✓ 😀"
    j = client.post("/api/jobs", json={"text": text, "operation": "wordcount"}).json()
    assert client.get(f"/api/jobs/{j['id']}").json()["text"] == text


def test_whitespace_only_text_handled(env):
    client, worker, db = env
    r = client.post("/api/jobs", json={"text": "   ", "operation": "reverse_words"})
    if r.status_code == 422:
        return  # rejecting blank input is also reasonable
    worker.process_next_job(db)
    j = client.get(f"/api/jobs/{r.json()['id']}").json()
    assert j["status"] == "done" and j["result"] == ""


def test_invalid_status_filter_is_not_500(env):
    client, _, _ = env
    assert client.get("/api/jobs", params={"status": "bogus"}).status_code < 500


def test_cancel_twice_conflicts(env):
    client, _, _ = env
    jid = client.post("/api/jobs", json={"text": "x", "operation": "uppercase"}).json()["id"]
    assert client.post(f"/api/jobs/{jid}/cancel").status_code == 200
    assert client.post(f"/api/jobs/{jid}/cancel").status_code == 409


def test_malformed_json_is_422(env):
    client, _, _ = env
    r = client.post("/api/jobs", content=b"{not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422


def test_non_integer_job_id_is_not_500(env):
    client, _, _ = env
    assert client.get("/api/jobs/abc").status_code in (404, 422)
