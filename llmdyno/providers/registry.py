"""Cloud vendors and OpenAI-compatible endpoints, connection tests and price lookup."""
import json
import re
import time

import httpx

from .. import config

# api_style: openai-chat (Chat Completions), openai-responses (Responses API), anthropic (Messages API)
VENDORS = [
    {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1", "api_style": "openai-responses",
     "styles": {"openai-responses": "https://api.openai.com/v1", "openai-chat": "https://api.openai.com/v1"},
     "keys_url": "https://platform.openai.com/api-keys", "openrouter_prefix": "openai",
     "notes": "Automatic prompt caching; the Responses API keeps reasoning between turns."},
    {"id": "anthropic", "name": "Anthropic (Claude)", "base_url": "https://api.anthropic.com", "api_style": "anthropic",
     "styles": {"anthropic": "https://api.anthropic.com", "openai-chat": "https://api.anthropic.com/v1"},
     "keys_url": "https://console.anthropic.com/settings/keys", "openrouter_prefix": "anthropic",
     "notes": "Use the native Messages API: prompt caching and extended thinking are not available on the OpenAI-compatible endpoint."},
    {"id": "google", "name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
     "api_style": "openai-chat", "styles": {"openai-chat": "https://generativelanguage.googleapis.com/v1beta/openai"},
     "keys_url": "https://aistudio.google.com/apikey", "openrouter_prefix": "google",
     "notes": "OpenAI-compatible endpoint with implicit caching; reasoning_effort maps to thinking budgets."},
    {"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "api_style": "openai-chat",
     "styles": {"openai-chat": "https://api.deepseek.com/v1", "anthropic": "https://api.deepseek.com/anthropic"},
     "keys_url": "https://platform.deepseek.com/api_keys", "openrouter_prefix": "deepseek",
     "notes": "Context caching on disk is automatic and billed at the cache-hit price."},
    {"id": "moonshot", "name": "Moonshot (Kimi)", "base_url": "https://api.moonshot.ai/v1", "api_style": "openai-chat",
     "styles": {"openai-chat": "https://api.moonshot.ai/v1", "anthropic": "https://api.moonshot.ai/anthropic"},
     "keys_url": "https://platform.moonshot.ai/console/api-keys", "openrouter_prefix": "moonshotai",
     "notes": "Some Kimi coding models require thinking to be enabled."},
    {"id": "zai", "name": "Z.ai (GLM)", "base_url": "https://api.z.ai/api/paas/v4", "api_style": "openai-chat",
     "styles": {"openai-chat": "https://api.z.ai/api/paas/v4", "anthropic": "https://api.z.ai/api/anthropic"},
     "keys_url": "https://z.ai/manage-apikey/apikey-list", "openrouter_prefix": "z-ai",
     "notes": "No Responses API, so Codex CLI cannot use GLM directly."},
    {"id": "qwen", "name": "Alibaba Qwen (Model Studio)", "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
     "api_style": "openai-chat", "styles": {"openai-chat": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"},
     "keys_url": "https://modelstudio.console.alibabacloud.com/", "openrouter_prefix": "qwen",
     "notes": "International endpoint; mainland accounts use dashscope.aliyuncs.com."},
    {"id": "minimax", "name": "MiniMax", "base_url": "https://api.minimax.io/v1", "api_style": "openai-chat",
     "styles": {"openai-chat": "https://api.minimax.io/v1", "anthropic": "https://api.minimax.io/anthropic"},
     "keys_url": "https://platform.minimax.io/user-center/basic-information/interface-key", "openrouter_prefix": "minimax"},
    {"id": "xai", "name": "xAI (Grok)", "base_url": "https://api.x.ai/v1", "api_style": "openai-chat",
     "styles": {"openai-chat": "https://api.x.ai/v1", "openai-responses": "https://api.x.ai/v1"},
     "keys_url": "https://console.x.ai/", "openrouter_prefix": "x-ai"},
    {"id": "mistral", "name": "Mistral", "base_url": "https://api.mistral.ai/v1", "api_style": "openai-chat",
     "styles": {"openai-chat": "https://api.mistral.ai/v1"}, "keys_url": "https://console.mistral.ai/api-keys",
     "openrouter_prefix": "mistralai"},
    {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "api_style": "openai-chat",
     "styles": {"openai-chat": "https://openrouter.ai/api/v1"}, "keys_url": "https://openrouter.ai/settings/keys",
     "openrouter_prefix": "", "notes": "One key for hundreds of models; prices come from OpenRouter itself."},
    {"id": "groq", "name": "Groq", "base_url": "https://api.groq.com/openai/v1", "api_style": "openai-chat",
     "styles": {"openai-chat": "https://api.groq.com/openai/v1"}, "keys_url": "https://console.groq.com/keys"},
    {"id": "together", "name": "Together AI", "base_url": "https://api.together.xyz/v1", "api_style": "openai-chat",
     "styles": {"openai-chat": "https://api.together.xyz/v1"}, "keys_url": "https://api.together.ai/settings/api-keys"},
    {"id": "fireworks", "name": "Fireworks AI", "base_url": "https://api.fireworks.ai/inference/v1", "api_style": "openai-chat",
     "styles": {"openai-chat": "https://api.fireworks.ai/inference/v1"}, "keys_url": "https://fireworks.ai/account/api-keys"},
    {"id": "cerebras", "name": "Cerebras", "base_url": "https://api.cerebras.ai/v1", "api_style": "openai-chat",
     "styles": {"openai-chat": "https://api.cerebras.ai/v1"}, "keys_url": "https://cloud.cerebras.ai/"},
    {"id": "custom", "name": "Custom OpenAI-compatible", "base_url": "http://host.docker.internal:11434/v1",
     "api_style": "openai-chat", "styles": {"openai-chat": "", "openai-responses": "", "anthropic": ""},
     "keys_url": "", "notes": "Ollama (:11434/v1), LM Studio (:1234/v1), vLLM or SGLang (:8000/v1), or any gateway. "
                              "Use host.docker.internal to reach a server on this machine from the sandbox proxy."},
]
BY_ID = {v["id"]: v for v in VENDORS}


def secret_name(provider_id):
    return f"provider:{provider_id}"


def auth_headers(api_style, key):
    if not key:
        return {}
    if api_style == "anthropic":
        return {"x-api-key": key, "anthropic-version": "2023-06-01"}
    return {"Authorization": f"Bearer {key}"}


def host_url(url):
    """The sandbox proxy reaches host services via host.docker.internal; this process reaches them via localhost."""
    return re.sub(r"//host\.docker\.internal(?=[:/])", "//127.0.0.1", url)


def list_models(base_url, api_style, key, timeout=20):
    """GET <base>/models. Returns sorted model ids; raises with a readable message on auth or network errors."""
    url = host_url(base_url).rstrip("/")
    url = f"{url}/v1/models" if api_style == "anthropic" and not url.endswith("/v1") else f"{url}/models"
    t0 = time.time()
    try:
        r = httpx.get(url, headers=auth_headers(api_style, key), timeout=timeout, params={"limit": 1000}
                      if api_style == "anthropic" else None)
    except httpx.HTTPError as e:
        raise ConnectionError(f"could not reach {url}: {type(e).__name__}") from e
    if r.status_code in (401, 403):
        raise PermissionError(f"{r.status_code}: the API key was rejected")
    if r.status_code >= 400:
        raise ConnectionError(f"{r.status_code} from {url}: {r.text[:200]}")
    data = r.json()
    items = data.get("data") if isinstance(data, dict) else data
    ids = sorted({(m.get("id") or m.get("name") or "").removeprefix("models/") for m in items or [] if isinstance(m, dict)})
    return {"models": [i for i in ids if i], "latency_ms": round((time.time() - t0) * 1000)}


# ------------------------------------------------------------------ pricing via the OpenRouter public catalog
_OR_URL = "https://openrouter.ai/api/v1/models"


def openrouter_catalog(max_age_s=86400):
    cp = config.DATA / "cache" / "openrouter_models.json"
    if cp.exists() and time.time() - cp.stat().st_mtime < max_age_s:
        return json.loads(cp.read_text(encoding="utf-8"))
    r = httpx.get(_OR_URL, timeout=30)
    r.raise_for_status()
    rows = []
    for m in r.json().get("data", []):
        p = m.get("pricing") or {}
        f = lambda k, p=p: round(float(p[k]) * 1e6, 4) if p.get(k) not in (None, "", "-1") else None   # noqa: E731
        rows.append({"id": m["id"], "name": m.get("name"), "context": m.get("context_length"),
                     "input": f("prompt"), "output": f("completion"), "cached": f("input_cache_read"),
                     "tools": "tools" in (m.get("supported_parameters") or []),
                     "reasoning": "reasoning" in (m.get("supported_parameters") or [])})
    cp.parent.mkdir(parents=True, exist_ok=True)
    cp.write_text(json.dumps(rows), encoding="utf-8")
    return rows


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def lookup_price(vendor_id, model_id):
    """Best match in the OpenRouter catalog: exact '<prefix>/<model>', then normalised equality, then prefix."""
    try:
        cat = openrouter_catalog()
    except (httpx.HTTPError, OSError, ValueError):
        return None
    prefix = (BY_ID.get(vendor_id) or {}).get("openrouter_prefix")
    cands = [m for m in cat if not m["id"].endswith(":batch") and not m["id"].endswith(":free")]
    tag = lambda m, how: {**m, "match": how} if m else None   # noqa: E731
    if vendor_id == "openrouter":
        return tag(next((m for m in cands if m["id"] == model_id), None), "exact")
    if prefix:
        hit = next((m for m in cands if m["id"] == f"{prefix}/{model_id}"), None)
        if hit:
            return tag(hit, "exact")
        same_vendor = [m for m in cands if m["id"].startswith(prefix + "/")]
    else:
        same_vendor = cands
    nm = _norm(model_id.split("/")[-1])
    hit = next((m for m in same_vendor if _norm(m["id"].split("/")[-1]) == nm), None)
    if hit:
        return tag(hit, "exact")
    pref = sorted((m for m in same_vendor if _norm(m["id"].split("/")[-1]).startswith(nm) or nm.startswith(
        _norm(m["id"].split("/")[-1]))), key=lambda m: abs(len(m["id"]) - len(model_id)))
    return tag(pref[0], "approximate") if pref else None
