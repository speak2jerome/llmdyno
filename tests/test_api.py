"""HTTP API through FastAPI's TestClient against the temporary data folder (no Docker, GPU or network needed)."""
import pytest
from fastapi.testclient import TestClient

from llmdyno import __version__, safety
from llmdyno.runner import sandbox
from llmdyno.server import app


@pytest.fixture(scope="module")
def client():
    # never touch real containers: a developer may have a live benchmark running on this machine
    mp = pytest.MonkeyPatch()
    mp.setattr(sandbox, "cleanup_stale", lambda: 0)
    mp.setattr(safety, "_docker", lambda *a, **k: None)
    mp.setattr(safety, "kill_stray_llama_servers", lambda: 0)
    with TestClient(app) as c:
        yield c
    mp.undo()


def test_health_reports_version(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["version"] == __version__ and h["schema_version"] >= 1


def test_settings_round_trip(client):
    client.patch("/api/settings", json={"electricity_usd_per_kwh": 0.31})
    assert client.get("/api/settings").json()["electricity_usd_per_kwh"] == 0.31


def test_benchmarks_and_harnesses_listed(client):
    ids = {b["id"] for b in client.get("/api/benchmarks").json()}
    assert "t0_smoke_cli" in ids
    harnesses = {h["id"] for h in client.get("/api/harnesses").json()}
    assert {"pi", "opencode", "codex", "aider"} <= harnesses


def test_unknown_things_are_404(client):
    assert client.get("/api/plans/plan_missing").status_code == 404
    assert client.get("/api/runs/run_missing").status_code == 404


def test_cloud_profile_lifecycle(client):
    prov = client.post("/api/providers", json={"vendor": "custom", "name": "Local test endpoint",
                                               "base_url": "http://127.0.0.1:9/v1", "api_style": "openai-chat",
                                               "budget_usd": 0.5}).json()
    prof = client.post("/api/profiles", json={"kind": "cloud", "name": "Test cloud", "provider_id": prov["id"],
                                              "remote_model": "test-model"}).json()
    exported = client.get(f"/api/profiles/{prof['id']}/export").json()
    assert exported["llmdyno_profile"] == 1 and exported["llmdyno_version"] == __version__
    assert client.post("/api/profiles/import", json={"name": "not a profile"}).status_code == 400
    assert client.delete(f"/api/profiles/{prof['id']}").status_code == 200


def test_sample_results_reproduce_the_published_numbers(client):
    """The bundled round-1 study must score exactly as published: GPT-6 Luna 94.3, best local 90.9, judges r = 0.879."""
    assert client.post("/api/sample").status_code == 200
    res = client.get("/api/results", params={"plan_ids": "plan_sample_round1", "include_sample": True}).json()
    finals = [round(c["final"] * 100, 1) for c in res["configs"]]
    assert finals[:4] == [94.3, 90.9, 90.7, 90.1]
    assert len(res["configs"]) == 15 and len(res["runs"]) == 75
    pair = res["agreement"]["pairs"][0]
    assert pair["pearson"] == 0.879 and pair["n"] == 75
    luna = next(s for s in res["agreement"]["self_preference"] if s["judge_id"] == "judge_sample_luna")
    assert luna["self_preference"] == -0.5
    exported = client.get("/api/results/export", params={"plan_ids": "plan_sample_round1", "level": "configs", "fmt": "json"})
    doc = exported.json()
    assert doc["llmdyno_version"] == __version__ and len(doc["rows"]) == 15
    assert f"llmdyno-{__version__}-configs" in exported.headers["content-disposition"]


def test_panic_stop_with_nothing_running(client):
    active = client.get("/api/system/active").json()
    assert active["idle"] is True
    report = client.post("/api/system/panic").json()
    assert report["runs_cancelled"] == 0 and report["containers_killed"] == 0
    assert report["llama_server_stopped"] is False
