"""Model backends beyond the built-in vendors: servers on this machine (Ollama, LM Studio, vLLM, …), a LiteLLM proxy,
and the Hugging Face Hub. Servers are faked locally; nothing reaches the internet."""
import http.server
import json
import threading

import pytest

import llmdyno
from llmdyno.providers import registry


@pytest.fixture()
def fake_server(monkeypatch):
    """An OpenAI-compatible /v1/models on a free port, registered as if it were Ollama."""
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({"object": "list", "data": [{"id": "qwen3-coder:30b"}, {"id": "gemma4:12b"}]}).encode()
            self.send_response(200 if self.path == "/v1/models" else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setattr(registry, "LOCAL_SERVERS", [("ollama", "Ollama", srv.server_port), ("vllm", "vLLM", 1)])
    yield srv.server_port
    srv.shutdown()


def test_local_servers_and_ollama(fake_server):
    found = llmdyno.local_servers()
    assert [s["id"] for s in found] == ["ollama"]                       # nothing answers on port 1
    assert found[0]["models"] == ["gemma4:12b", "qwen3-coder:30b"]
    assert found[0]["docker_url"] == f"http://host.docker.internal:{fake_server}/v1"
    p = llmdyno.ollama_model("qwen3-coder:30b", ctx=32768)
    try:
        assert p.name == "qwen3-coder:30b · Ollama" and p.params["ctx"] == 32768
        prov = llmdyno.provider(p["provider_id"])
        assert prov.vendor == "custom" and prov["base_url"] == found[0]["docker_url"]
        with pytest.raises(llmdyno.NotFoundError, match="ollama pull"):
            llmdyno.ollama_model("nope:1b")
        q = llmdyno.openai_compatible(f"http://localhost:{fake_server}/v1", "gemma4:12b")
        assert q["provider_id"] == p["provider_id"]                     # same endpoint, same provider
        with pytest.raises(llmdyno.LLMDynoError, match="pass model="):
            llmdyno.openai_compatible(f"http://localhost:{fake_server}/v1")   # it serves two
        q.delete()
    finally:
        p.delete()
        llmdyno.provider(prov.id).delete()


def test_ollama_not_running(monkeypatch):
    monkeypatch.setattr(registry, "LOCAL_SERVERS", [("ollama", "Ollama", 1)])
    with pytest.raises(llmdyno.LLMDynoError, match="not running"):
        llmdyno.ollama_model("qwen3-coder:30b")


def test_litellm_vendor_without_a_key():
    v = next(x for x in llmdyno.vendors() if x["id"] == "litellm")
    assert v["key_optional"] and v["base_url"] == "http://host.docker.internal:4000/v1"
    p = llmdyno.litellm_model("bedrock/anthropic.claude-test", base_url="http://localhost:4100", pricing=None)
    try:
        prov = llmdyno.provider(p["provider_id"])
        assert prov.vendor == "litellm" and prov["base_url"] == "http://host.docker.internal:4100"
        assert p.name == "bedrock/anthropic.claude-test · LiteLLM"
        pf = llmdyno.preflight(p, "t0_smoke_cli")
        assert not any("no API key" in b["text"] for b in pf["blocking"])
        assert prov.budget_usd == 5.0                                   # spend is still capped
    finally:
        p.delete()
        llmdyno.provider(prov.id).delete()


def test_litellm_prices(monkeypatch):
    pytest.importorskip("litellm")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    hit = llmdyno.lookup_price("litellm", "gpt-4o-mini")
    assert hit["source"] == "litellm" and hit["input"] > 0 and hit["output"] > hit["input"]


def test_hub_token_reuse(monkeypatch):
    hub = pytest.importorskip("huggingface_hub")
    from llmdyno.hub import hf
    monkeypatch.setattr(hub, "get_token", lambda: "hf_from_login")
    llmdyno.remove_hf_token()
    assert hf._headers() == {"Authorization": "Bearer hf_from_login"}
    llmdyno.set_hf_token("hf_saved")
    try:
        assert hf._headers() == {"Authorization": "Bearer hf_saved"}     # a token saved in LLMDyno wins
    finally:
        llmdyno.remove_hf_token()


def test_push_and_load_results(monkeypatch, tmp_path):
    hub = pytest.importorskip("huggingface_hub")
    pytest.importorskip("pyarrow")
    repo = tmp_path / "hub"
    calls = []

    class FakeApi:
        def __init__(self, token=None):
            calls.append(("token", token))

        def create_repo(self, repo_id, **kw):
            calls.append(("create", repo_id, kw["repo_type"], kw["private"]))

        def upload_folder(self, repo_id, folder_path, **kw):
            import shutil
            shutil.copytree(folder_path, repo / repo_id, dirs_exist_ok=True)
            calls.append(("upload", repo_id))

    monkeypatch.setattr(hub, "HfApi", FakeApi)
    monkeypatch.setattr(hub, "hf_hub_download", lambda repo_id, filename, **kw: str(repo / repo_id / filename))
    was = llmdyno.sample_status()["loaded"]
    sample = llmdyno.load_sample()
    try:
        r = llmdyno.results(sample)
        url = r.push_to_hub("someone/llmdyno-results")
        assert url == "https://huggingface.co/datasets/someone/llmdyno-results"
        assert ("create", "someone/llmdyno-results", "dataset", True) in calls
        files = sorted(p.name for p in (repo / "someone/llmdyno-results").iterdir())
        assert files == ["README.md", "cells.parquet", "configs.parquet", "results.json", "runs.parquet"]
        assert "config_name: runs" in (repo / "someone/llmdyno-results/README.md").read_text()
        back = llmdyno.load_results_from_hub("someone/llmdyno-results")
        assert back.leaderboard() == r.leaderboard() and back.plan_ids == [sample]
    finally:
        if not was:
            llmdyno.unload_sample()


def test_preflight_counts_what_the_provider_already_spent():
    """The "exceeds what is left in the budget" warning subtracts the spend ledger, not a database column."""
    from llmdyno import llm
    p = llmdyno.cloud_model("groq", "budget-test-model", api_key="gsk-test", budget_usd=1.0,
                            pricing={"input": 3.0, "output": 15.0, "cached": 0.3})
    prov = llmdyno.provider(p["provider_id"])
    try:
        def left_warning():
            pf = llmdyno.preflight(p, "t1_flask_site")
            return [w["text"] for w in pf["warnings"] if "left in the" in w["text"]]
        assert not left_warning()                                  # the estimate fits in $1
        llm.ledger_add(prov.id, 0.999)
        assert any("$0.00 left" in t for t in left_warning())
    finally:
        llm.ledger_reset(f"provider_{prov.id}")
        p.delete()
        prov.delete()
