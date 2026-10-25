"""The logging proxy: usage normalisation, local-template fixes, and spend ledgers that survive parallel writers."""
import importlib
import json
import multiprocessing as mp

import pytest


def load_proxy(monkeypatch, tmp_path, writer="w1", ledgers=None):
    monkeypatch.setenv("LEDGER_DIR", str(tmp_path))
    monkeypatch.setenv("LEDGER_WRITER", writer)
    monkeypatch.setenv("LEDGERS", json.dumps(ledgers or [{"name": "provider_x", "budget": 1.0}]))
    monkeypatch.setenv("PROXY_LOG", str(tmp_path / "proxy.jsonl"))
    monkeypatch.setenv("TRANSCRIPT", str(tmp_path / "transcript.jsonl"))
    from llmdyno.proxy import llm_proxy
    return importlib.reload(llm_proxy)


def test_usage_normalisation(monkeypatch, tmp_path):
    px = load_proxy(monkeypatch, tmp_path)
    chat = px.normalize_usage({"prompt_tokens": 100, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 60},
                               "completion_tokens_details": {"reasoning_tokens": 5}}, "openai-chat")
    assert chat == {"input": 100, "cached": 60, "cache_write": 0, "output": 20, "reasoning": 5}
    resp = px.normalize_usage({"input_tokens": 50, "output_tokens": 7, "input_tokens_details": {"cached_tokens": 10}}, "openai-responses")
    assert (resp["input"], resp["cached"], resp["output"]) == (50, 10, 7)
    # Anthropic reports cached and cache-write tokens on top of input_tokens
    ant = px.normalize_usage({"input_tokens": 10, "cache_read_input_tokens": 80, "cache_creation_input_tokens": 30,
                              "output_tokens": 9}, "anthropic")
    assert ant == {"input": 120, "cached": 80, "cache_write": 30, "output": 9, "reasoning": 0}


def test_compat_local_moves_system_messages_first(monkeypatch, tmp_path):
    px = load_proxy(monkeypatch, tmp_path)
    req = {"messages": [{"role": "user", "content": "hi"}, {"role": "developer", "content": "be brief"},
                        {"role": "system", "content": "you are a coder"}]}
    assert px.compat_local("openai-chat", req)
    assert req["messages"][0]["role"] == "system" and len(req["messages"]) == 2
    ok = {"messages": [{"role": "system", "content": "x"}, {"role": "user", "content": "y"}]}
    assert not px.compat_local("openai-chat", ok)


def test_ledger_shards_and_budget(monkeypatch, tmp_path):
    px = load_proxy(monkeypatch, tmp_path, writer="run_a")
    px.ledger_add(0.4)
    (tmp_path / "provider_x__run_b.json").write_text(json.dumps({"spent_usd": 0.5}))   # another proxy's shard
    (tmp_path / "provider_x.json").write_text(json.dumps({"spent_usd": 0.05}))          # pre-sharding ledger file
    assert px.ledger_total("provider_x") == pytest.approx(0.95)
    assert px.over_budget() is None
    px.ledger_add(0.06)
    assert px.over_budget()["name"] == "provider_x"


def _writer(args):
    ledger_dir, writer, n = args
    import os
    os.environ.update({"LEDGER_DIR": ledger_dir, "LEDGER_WRITER": writer,
                       "LEDGERS": json.dumps([{"name": "provider_x", "budget": 100}])})
    from llmdyno.proxy import llm_proxy
    for _ in range(n):
        llm_proxy.ledger_add(0.01)


def test_parallel_proxies_never_lose_spend(tmp_path):
    """Four proxies booking 50 requests each at the same time: every cent must be counted."""
    ctx = mp.get_context("spawn")
    with ctx.Pool(4) as pool:
        pool.map(_writer, [(str(tmp_path), f"run_{i}", 50) for i in range(4)])
    total = sum(json.loads(p.read_text())["spent_usd"] for p in tmp_path.glob("provider_x__*.json"))
    assert total == pytest.approx(4 * 50 * 0.01)
