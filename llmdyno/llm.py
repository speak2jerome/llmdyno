"""Direct model calls from the host (judging and profile tests): one function for every API style.

Spend is written to the same ledger files the sandbox proxies use, so provider budgets cover everything."""
import glob
import json
import os
import re
import threading
import time

import httpx

from . import config, db, secrets
from .providers import registry as providers

_lock = threading.Lock()


def ledger_dir():
    d = config.DATA / "ledgers"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ledger_files(name):
    """<name>.json (single-file ledgers from older versions) plus one <name>__<writer>.json shard per writer."""
    d = ledger_dir()
    return [p for p in [d / f"{name}.json", *sorted(d.glob(f"{glob.escape(name)}__*.json"))] if p.exists()]


_last = {}


def _read(p):
    """A shard being replaced by a proxy can be briefly unreadable on Windows: retry, then use the last value seen."""
    for attempt in range(20):
        try:
            v = float(json.loads(p.read_text()).get("spent_usd", 0))
            _last[p] = v
            return v
        except FileNotFoundError:
            return _last.get(p, 0.0)
        except (OSError, ValueError):
            time.sleep(0.01 * (attempt + 1))
    return _last.get(p, 0.0)


def ledger_total(name):
    return sum(_read(p) for p in ledger_files(name))


def ledger_spent(provider_id):
    return ledger_total(f"provider_{provider_id}")


def ledger_reset(name):
    for p in ledger_files(name):
        p.unlink(missing_ok=True)


def ledger_add(provider_id, cost, budget=None):
    """Host-side spend (judging, quick tests) goes to the host's own shard; proxies write theirs."""
    with _lock:
        p = ledger_dir() / f"provider_{provider_id}__host.json"
        mine = _read(p) + cost
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps({"spent_usd": round(mine, 6), "budget_usd": budget, "updated": time.time()}))
        for attempt in range(50):
            try:
                os.replace(tmp, p)
                break
            except PermissionError:
                time.sleep(0.01 * (attempt + 1))
        else:
            os.replace(tmp, p)
    return ledger_spent(provider_id)


def cost_of(usage, pricing):
    if not usage or not pricing:
        return 0.0
    inp, cached, out = usage.get("input") or 0, usage.get("cached") or 0, usage.get("output") or 0
    cw = usage.get("cache_write") or 0
    return (max(inp - cached - cw, 0) * (pricing.get("input") or 0) + cached * (pricing.get("cached") or pricing.get("input") or 0)
            + cw * (pricing.get("input") or 0) * 1.25 + out * (pricing.get("output") or 0)) / 1e6


def _norm_usage(u, style):
    if not u:
        return None
    if style == "anthropic":
        cr, cw = u.get("cache_read_input_tokens") or 0, u.get("cache_creation_input_tokens") or 0
        return {"input": (u.get("input_tokens") or 0) + cr + cw, "cached": cr, "cache_write": cw,
                "output": u.get("output_tokens") or 0}
    di = u.get("prompt_tokens_details") or u.get("input_tokens_details") or {}
    return {"input": u.get("prompt_tokens", u.get("input_tokens")) or 0, "cached": di.get("cached_tokens") or 0,
            "cache_write": 0, "output": u.get("completion_tokens", u.get("output_tokens")) or 0}


def target(profile, provider):
    """(base url, api style, model, headers) for a profile; local profiles use the running llama-server."""
    if profile["kind"] == "local":
        return f"http://127.0.0.1:{config.get('llama_port')}/v1", "openai-chat", "local-model", {}
    vendor = providers.BY_ID.get(provider["vendor"], providers.BY_ID["custom"])
    style = profile["params"].get("api_style") or provider["api_style"]
    base = (vendor.get("styles") or {}).get(style) or provider["base_url"]
    if provider["vendor"] == "custom":
        base = provider["base_url"]
    key = secrets.get(providers.secret_name(provider["id"]))
    return providers.host_url(base), style, profile["remote_model"], providers.auth_headers(style, key)


def complete(profile, provider, prompt, max_tokens=12000, json_mode=True, tools=None, system=None, timeout=900):
    """One request. Returns {text, tool_calls, usage, cost_usd, latency_s, ttft_s?}."""
    base, style, model, headers = target(profile, provider)
    p = profile["params"]
    effort = p.get("reasoning_effort") if profile["kind"] != "local" else None
    t0 = time.time()
    if style == "anthropic":
        body = {"model": model, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
        if system:
            body["system"] = system
        if effort:
            budget = {"minimal": 1024, "low": 2048, "medium": 6000, "high": 12000, "max": 24000}.get(effort, 4000)
            body["thinking"] = {"type": "enabled", "budget_tokens": min(budget, max_tokens - 1024)}
        if tools:
            body["tools"] = [{"name": t["name"], "description": t["description"], "input_schema": t["parameters"]} for t in tools]
        url = base.rstrip("/") + ("/messages" if base.rstrip("/").endswith("/v1") else "/v1/messages")
        r = httpx.post(url, json=body, headers=headers, timeout=timeout)
        _raise(r)
        d = r.json()
        text = "".join(c.get("text", "") for c in d.get("content", []) if c.get("type") == "text")
        calls = [{"name": c["name"], "args": c.get("input")} for c in d.get("content", []) if c.get("type") == "tool_use"]
        usage = _norm_usage(d.get("usage"), style)
    elif style == "openai-responses":
        body = {"model": model, "input": prompt, "max_output_tokens": max_tokens}
        if system:
            body["instructions"] = system
        if effort:
            body["reasoning"] = {"effort": effort}
        if json_mode and not tools:
            body["text"] = {"format": {"type": "json_object"}}
        if tools:
            body["tools"] = [{"type": "function", **t} for t in tools]
        r = httpx.post(base.rstrip("/") + "/responses", json=body, headers=headers, timeout=timeout)
        _raise(r)
        d = r.json()
        text, calls = "", []
        for it in d.get("output", []):
            if it.get("type") == "message":
                text += "".join(c.get("text", "") for c in it.get("content", []) if c.get("type") in ("output_text", "text"))
            elif it.get("type") == "function_call":
                calls.append({"name": it.get("name"), "args": it.get("arguments")})
        usage = _norm_usage(d.get("usage"), style)
    else:
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        body = {"model": model, "messages": msgs, "max_tokens": max_tokens}
        if effort:
            body["reasoning_effort"] = effort
        if json_mode and not tools:
            body["response_format"] = {"type": "json_object"}
        if tools:
            body["tools"] = [{"type": "function", "function": t} for t in tools]
        if profile["kind"] == "local":
            s = p.get("sampling") or {}
            if s.get("temperature") is not None:
                body["temperature"] = s["temperature"]
        r = httpx.post(base.rstrip("/") + "/chat/completions", json=body, headers=headers, timeout=timeout)
        if r.status_code == 400 and "response_format" in body:
            body.pop("response_format")              # some OpenAI-compatible servers reject json mode
            r = httpx.post(base.rstrip("/") + "/chat/completions", json=body, headers=headers, timeout=timeout)
        _raise(r)
        d = r.json()
        msg = (d.get("choices") or [{}])[0].get("message") or {}
        text = msg.get("content") or ""
        calls = [{"name": (c.get("function") or {}).get("name"), "args": (c.get("function") or {}).get("arguments")}
                 for c in msg.get("tool_calls") or []]
        usage = _norm_usage(d.get("usage"), style)
        if d.get("timings"):
            usage = {**(usage or {}), "timings": d["timings"]}
    cost = cost_of(usage, profile.get("pricing")) if profile["kind"] != "local" else 0.0
    if cost and provider:
        ledger_add(provider["id"], cost, provider.get("budget_usd"))
    return {"text": text, "tool_calls": calls, "usage": usage, "cost_usd": round(cost, 6),
            "latency_s": round(time.time() - t0, 2)}


def _raise(r):
    if r.status_code in (401, 403):
        raise PermissionError(f"{r.status_code}: the provider rejected the API key")
    if r.status_code == 429:
        raise RuntimeError(f"429 rate limited or out of credit: {r.text[:300]}")
    if r.status_code >= 400:
        raise RuntimeError(f"{r.status_code}: {r.text[:500]}")


def parse_json(text):
    """JSON from a model reply, tolerating code fences and leading prose."""
    text = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.S)
    if m:
        text = m.group(1)
    try:
        return json.loads(text)
    except ValueError:
        pass
    start, depth = text.find("{"), 0
    for i in range(start, len(text)) if start >= 0 else ():
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        if depth == 0:
            try:
                return json.loads(text[start:i + 1])
            except ValueError:
                break
    raise ValueError("reply was not valid JSON")


def provider_budget_left(provider):
    if not provider or provider["vendor"] == "custom":
        return None
    return (provider.get("budget_usd") or 0) - ledger_spent(provider["id"])


def provider_of(profile):
    if not profile.get("provider_id"):
        return None
    with db.Session() as s:
        p = s.get(db.Provider, profile["provider_id"])
        return db.row(p) if p else None
