import importlib
import sqlite3
import sys
import time

import pytest


def fresh(name):
    for m in [m for m in sys.modules if m == name or m.startswith(name + ".")]:
        sys.modules.pop(m)
    return importlib.import_module(name)


@pytest.fixture()
def db(tmp_path, monkeypatch):
    path = tmp_path / "jobs.db"
    monkeypatch.setenv("JOBS_DB", str(path))
    return str(path)


@pytest.fixture()
def client(db):
    from fastapi.testclient import TestClient
    main = fresh("backend.main")
    with TestClient(main.app) as c:
        yield c


@pytest.fixture()
def worker(db):
    return fresh("worker.worker")


def create(client, text="Hello world. Second sentence.", op="wordcount"):
    return client.post("/api/jobs", json={"text": text, "operation": op})


def test_create_job_201_queued(client):
    r = create(client)
    assert r.status_code == 201
    j = r.json()
    for key in ("id", "text", "operation", "status", "result", "error", "created_at", "finished_at"):
        assert key in j
    assert j["status"] == "queued" and j["result"] is None and j["finished_at"] is None


@pytest.mark.parametrize("payload", [
    {"text": "", "operation": "wordcount"},
    {"text": "x" * 10001, "operation": "wordcount"},
    {"text": "hi", "operation": "explode"},
    {"operation": "uppercase"},
])
def test_invalid_input_422(client, payload):
    assert client.post("/api/jobs", json=payload).status_code == 422


def test_get_job_and_404(client):
    jid = create(client).json()["id"]
    assert client.get(f"/api/jobs/{jid}").json()["id"] == jid
    assert client.get("/api/jobs/999999").status_code == 404


def test_list_newest_first_and_filter(client, worker, db):
    a = create(client, op="uppercase").json()["id"]
    b = create(client, op="uppercase").json()["id"]
    ids = [j["id"] for j in client.get("/api/jobs").json()]
    assert ids.index(b) < ids.index(a)
    worker.process_next_job(db)
    done = client.get("/api/jobs", params={"status": "done"}).json()
    queued = client.get("/api/jobs", params={"status": "queued"}).json()
    assert [j["id"] for j in done] == [a]
    assert [j["id"] for j in queued] == [b]


def test_api_does_not_process(client):
    jid = create(client).json()["id"]
    time.sleep(1.0)
    assert client.get(f"/api/jobs/{jid}").json()["status"] == "queued"


def test_cancel(client, worker, db):
    jid = create(client).json()["id"]
    r = client.post(f"/api/jobs/{jid}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert worker.process_next_job(db) is False
    assert client.get(f"/api/jobs/{jid}").json()["status"] == "cancelled"
    assert client.post("/api/jobs/999999/cancel").status_code == 404


def test_cancel_done_conflict(client, worker, db):
    jid = create(client).json()["id"]
    worker.process_next_job(db)
    assert client.post(f"/api/jobs/{jid}/cancel").status_code == 409


def test_worker_empty_returns_false(client, worker, db):
    assert worker.process_next_job(db) is False


def test_worker_oldest_first(client, worker, db):
    first = create(client, op="uppercase", text="first").json()["id"]
    second = create(client, op="uppercase", text="second").json()["id"]
    assert worker.process_next_job(db) is True
    assert client.get(f"/api/jobs/{first}").json()["status"] == "done"
    assert client.get(f"/api/jobs/{second}").json()["status"] == "queued"


@pytest.mark.parametrize("op,text,expected", [
    ("wordcount", "one two  three\nfour", {"words": 4, "chars": 19}),
    ("uppercase", "Hello, World", "HELLO, WORLD"),
    ("reverse_words", "  alpha beta\tgamma  ", "gamma beta alpha"),
    ("summary", "  First sentence here! Then more. ", "First sentence here!"),
    ("summary", "no punctuation at all", "no punctuation at all"),
    ("summary", "a" * 150 + ". tail", "a" * 100),
])
def test_operation_results(client, worker, db, op, text, expected):
    jid = create(client, op=op, text=text).json()["id"]
    assert worker.process_next_job(db) is True
    j = client.get(f"/api/jobs/{jid}").json()
    assert j["status"] == "done"
    assert j["result"] == expected
    assert j["finished_at"]


def test_jobs_persist_in_sqlite_file(client, db):
    create(client)
    con = sqlite3.connect(db)
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    finally:
        con.close()
    assert tables


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "<form" in r.text.lower() or "<textarea" in r.text.lower()
