from fastapi.testclient import TestClient

from backend.main import app
from worker.worker import process_next_job


def test_flow(tmp_path, monkeypatch):
    db = str(tmp_path / "j.db")
    monkeypatch.setenv("JOBS_DB", db)
    c = TestClient(app)
    jid = c.post("/api/jobs", json={"text": "a b", "operation": "wordcount"}).json()["id"]
    assert process_next_job(db)
    assert c.get(f"/api/jobs/{jid}").json()["result"] == {"words": 2, "chars": 3}


def test_422(tmp_path, monkeypatch):
    monkeypatch.setenv("JOBS_DB", str(tmp_path / "j.db"))
    assert TestClient(app).post("/api/jobs", json={"text": "", "operation": "wordcount"}).status_code == 422


def test_empty_worker(tmp_path, monkeypatch):
    db = str(tmp_path / "j.db")
    monkeypatch.setenv("JOBS_DB", db)
    TestClient(app).get("/api/jobs")
    assert process_next_job(db) is False
