"""Public reference numbers from Artificial Analysis (artificialanalysis.ai), shown beside LLMDyno's own results.

Uses the free API (GET /api/v2/language/models/free, 100 requests a day, key from artificialanalysis.ai/account).
The free tier's terms require visible attribution, so every place the numbers appear links back to the source.
Responses are cached on disk and refreshed at most every 12 hours; one refresh costs a few requests (one per page).

Matching a profile to an AA model is fuzzy (model name tokens plus creator) and can be overridden per profile.
AA-style metrics computed from LLMDyno's own runs, so the two can be compared directly:
  output speed   generated tokens per second while decoding (AA: median output tokens/s)
  TTFT           median time to the first token over a run's requests
  blended price  (3 x input + 1 x output) / 4 per million tokens, AA's 3:1 blend"""
import json
import re
import time

import httpx

from .. import config, secrets

API = "https://artificialanalysis.ai/api/v2/language/models/free"
SITE = "https://artificialanalysis.ai"
ATTRIBUTION = {"text": "Reference data: Artificial Analysis", "url": SITE}
SECRET = "aa_api_key"
REFRESH_S = 12 * 3600
DAILY_LIMIT = 100


def cache_path():
    return config.DATA / "references" / "artificial_analysis.json"


def load_cache():
    try:
        return json.loads(cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"fetched_at": 0, "models": [], "requests": []}


def _num(v):
    return round(float(v), 4) if isinstance(v, (int, float)) else None


def blended(price_in, price_out):
    if price_in is None or price_out is None:
        return None
    return round((3 * price_in + price_out) / 4, 4)


def normalize(item):
    """One API item to a flat dict. Pure, so it is unit tested."""
    ev = item.get("evaluations") or {}
    pr = item.get("pricing") or {}
    perf = item.get("performance_v3") or item.get("performance") or {}
    pin, pout = _num(pr.get("price_1m_input_tokens")), _num(pr.get("price_1m_output_tokens"))
    return {"id": item.get("id"), "name": item.get("name"), "slug": item.get("slug"),
            "creator": (item.get("model_creator") or {}).get("name"), "release_date": item.get("release_date"),
            "intelligence_index": _num(ev.get("artificial_analysis_intelligence_index")),
            "coding_index": _num(ev.get("artificial_analysis_coding_index")),
            "agentic_index": _num(ev.get("artificial_analysis_agentic_index")),
            "evaluations": {k: _num(v) for k, v in ev.items() if _num(v) is not None},
            "price_input": pin, "price_output": pout, "price_cached": _num(pr.get("price_1m_cache_hit_tokens")),
            "price_blended": blended(pin, pout),
            "output_tps": _num(perf.get("mean_output_tokens_per_second") or perf.get("median_output_tokens_per_second")),
            "ttft_s": _num(perf.get("mean_time_to_first_token_seconds") or perf.get("median_time_to_first_token_seconds")),
            "ttfat_s": _num(perf.get("mean_time_to_first_answer_token_seconds")),
            "url": f"{SITE}/models/{item['slug']}" if item.get("slug") else SITE}


def requests_today(cache):
    day = time.time() - 86400
    return len([t for t in cache.get("requests", []) if t > day])


def refresh(force=False, client=None):
    key = secrets.get(SECRET)
    if not key:
        raise PermissionError("add an Artificial Analysis API key in Settings first")
    cache = load_cache()
    if not force and time.time() - cache.get("fetched_at", 0) < REFRESH_S and cache.get("models"):
        return cache
    used = requests_today(cache)
    c = client or httpx.Client(timeout=30)
    models, page, meta = [], 1, {}
    stamps = [t for t in cache.get("requests", []) if t > time.time() - 86400]
    while True:
        if used >= DAILY_LIMIT - 2:
            raise RuntimeError(f"{used} Artificial Analysis requests in the last 24 hours: the free limit is "
                               f"{DAILY_LIMIT}, try again later")
        r = c.get(API, params={"page": page}, headers={"x-api-key": key, "User-Agent": "LLMDyno"})
        used += 1
        stamps.append(time.time())
        if r.status_code in (401, 403):
            raise PermissionError("Artificial Analysis rejected the API key")
        r.raise_for_status()
        d = r.json()
        models += [normalize(x) for x in d.get("data") or []]
        meta = {"tier": d.get("tier"), "intelligence_index_version": d.get("intelligence_index_version")}
        pg = d.get("pagination") or {}
        if not pg.get("has_more") or page >= 20:
            break
        page += 1
    out = {"fetched_at": time.time(), "models": models, "requests": stamps, **meta}
    cache_path().parent.mkdir(parents=True, exist_ok=True)
    cache_path().write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


# ------------------------------------------------------------------ matching
NOISE = {"instruct", "gguf", "it", "chat", "hf", "latest", "preview", "model", "the", "q4", "q5", "q6", "q8", "k", "m",
         "s", "l", "xl", "xs", "xxs", "nl", "ud", "fp16", "bf16", "moe", "qat", "cpu", "offload", "ctx", "unsloth",
         "bartowski", "lmstudio", "community", "ggml", "org"}
QUANT_RE = re.compile(r"\b(?:i?q\d|f16|bf16|fp8|mxfp4|awq|gptq|exl2)(?:_[a-z0-9]+)*\b")


def tokens(s):
    s = (s or "").lower().split("/")[-1]              # "openai/gpt-5" and "unsloth/Qwen3..." -> the model
    s = QUANT_RE.sub(" ", s).replace("_", " ")       # quant names first, while Q4_0 / IQ3_XXS are still one word
    s = re.sub(r"(\d)\.(\d)", r"\1p\2", s)            # 2.5 -> 2p5 so it stays one token
    toks = re.findall(r"[a-z]+|\d+p\d+|\d+[a-z]?", s)
    return [t for t in toks if t not in NOISE]


def score(profile_name, model_name, creator, cand):
    want = set(tokens(model_name)) or set(tokens(profile_name))
    best = 0.0
    for field in ("name", "slug"):                    # compare with each separately: "3.8" and "3-8" tokenize differently
        have = set(tokens(cand.get(field)))
        if not want or not have:
            continue
        s = len(want & have) / len(want | have)
        nums_w = {t for t in want if re.match(r"\d", t)}
        if nums_w and not nums_w <= have:
            s *= 0.5                                  # 30b vs 32b, gpt-5 vs gpt-4: different models
        best = max(best, s)
    if best and creator and cand.get("creator") and creator.lower() in cand["creator"].lower():
        best += 0.1
    return round(min(best, 1.0), 3)


def match(label, models, override=None):
    """Best AA model for a profile label from results_api._labels(), or None below the confidence threshold."""
    if override:
        m = next((x for x in models if x.get("slug") == override or x.get("id") == override), None)
        return {"model": m, "score": 1.0, "manual": True} if m else None
    creator = {"openai": "OpenAI", "anthropic": "Anthropic", "google": "Google", "xai": "xAI", "mistral": "Mistral",
               "deepseek": "DeepSeek"}.get(label.get("vendor") or "")
    best, best_s = None, 0.0
    for m in models:
        s = score(label.get("name"), label.get("model"), creator, m)
        if s > best_s:
            best, best_s = m, s
    return {"model": best, "score": best_s, "manual": False} if best and best_s >= 0.45 else None


def overrides():
    return (config.get("aa_reference") or {}).get("overrides") or {}


def reference(labels):
    """{profile_id: {model, score, manual}} for every profile label that matches."""
    models = load_cache().get("models") or []
    ov = overrides()
    out = {}
    for pid, lab in labels.items():
        m = match(lab, models, ov.get(pid))
        if m:
            out[pid] = m
    return out


def status():
    c = load_cache()
    return {"has_key": secrets.has(SECRET), "fetched_at": c.get("fetched_at") or None, "models": len(c.get("models") or []),
            "requests_today": requests_today(c), "daily_limit": DAILY_LIMIT, "tier": c.get("tier"),
            "intelligence_index_version": c.get("intelligence_index_version"), "attribution": ATTRIBUTION}
