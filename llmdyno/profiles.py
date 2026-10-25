"""LLM profiles: a model plus the parameters it is benchmarked with."""
import copy

LOCAL_DEFAULTS = {
    "ctx": 65536, "gpu_layers": "all", "auto_fit": False, "fit_margin_mib": 1024, "n_cpu_moe": 0,
    "flash_attn": "on", "cache_k": "q8_0", "cache_v": "q8_0", "threads": None, "batch": None, "ubatch": None,
    "parallel": 1, "mlock": False, "no_mmap": False, "swa_full": False,
    "sampling": {"temperature": None, "top_p": None, "top_k": None, "min_p": None, "repeat_penalty": None,
                 "presence_penalty": None},
    "thinking": "auto", "template_kwargs": {}, "reasoning_budget": None, "max_output_tokens": 16384,
    "extra_args": [],
}
CLOUD_DEFAULTS = {
    "ctx": 200000, "max_output_tokens": 16384, "reasoning_effort": "medium", "temperature": None, "top_p": None,
    "api_style": None, "extra_body": {},
}
ENUMS = {
    "flash_attn": ["on", "off", "auto"],
    "cache_k": ["f16", "bf16", "q8_0", "q5_1", "q5_0", "q4_1", "q4_0", "iq4_nl", "f32"],
    "cache_v": ["f16", "bf16", "q8_0", "q5_1", "q5_0", "q4_1", "q4_0", "iq4_nl", "f32"],
    "thinking": ["auto", "on", "off"],
    "reasoning_effort": [None, "minimal", "low", "medium", "high", "max"],
}


def merge(defaults, patch):
    out = copy.deepcopy(defaults)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def validate_local(p):
    errs = []
    if not isinstance(p.get("ctx"), int) or not 1024 <= p["ctx"] <= 4_194_304:
        errs.append("ctx must be an integer between 1,024 and 4,194,304")
    ngl = p.get("gpu_layers")
    if not (ngl == "all" or (isinstance(ngl, int) and 0 <= ngl <= 1000)):
        errs.append("gpu_layers must be 'all' or 0-1000")
    for k in ("flash_attn", "cache_k", "cache_v", "thinking"):
        if p.get(k) not in ENUMS[k]:
            errs.append(f"{k} must be one of {', '.join(ENUMS[k])}")
    for k in ("n_cpu_moe", "threads", "batch", "ubatch", "parallel", "max_output_tokens"):
        v = p.get(k)
        if v is not None and (not isinstance(v, int) or v < 0):
            errs.append(f"{k} must be a non-negative integer")
    if p.get("parallel") is not None and p["parallel"] < 1:
        errs.append("parallel must be at least 1")
    s = p.get("sampling") or {}
    if s.get("temperature") is not None and not 0 <= s["temperature"] <= 2:
        errs.append("temperature must be between 0 and 2")
    if s.get("top_p") is not None and not 0 < s["top_p"] <= 1:
        errs.append("top_p must be in (0, 1]")
    if not isinstance(p.get("extra_args", []), list):
        errs.append("extra_args must be a list of strings")
    bad = {"-m", "--model", "--host", "--port", "-c", "--ctx-size"} & set(map(str, p.get("extra_args", [])))
    if bad:
        errs.append(f"extra_args cannot override {', '.join(sorted(bad))}; use the dedicated fields")
    return errs


def validate_cloud(p):
    errs = []
    if p.get("reasoning_effort") not in ENUMS["reasoning_effort"]:
        errs.append("reasoning_effort must be one of minimal, low, medium, high, max or empty")
    if not isinstance(p.get("ctx"), int) or p["ctx"] < 4096:
        errs.append("ctx must be at least 4,096")
    if p.get("temperature") is not None and not 0 <= p["temperature"] <= 2:
        errs.append("temperature must be between 0 and 2")
    return errs


def effective_template_kwargs(p):
    """Map the thinking toggle onto the chat-template kwargs most GGUF templates understand."""
    kw = dict(p.get("template_kwargs") or {})
    if p.get("thinking") == "on":
        kw.setdefault("enable_thinking", True)
    elif p.get("thinking") == "off":
        kw.setdefault("enable_thinking", False)
    return kw


def launch_params(p):
    """Profile params as handed to llama-server (thinking folded into template kwargs)."""
    q = dict(p)
    q["template_kwargs"] = effective_template_kwargs(p)
    return q


def default_local(meta):
    p = copy.deepcopy(LOCAL_DEFAULTS)
    rec = (meta or {}).get("sampling") or {}
    if rec:
        p["sampling"].update({"temperature": round(rec["temp"], 2) if rec.get("temp") is not None else None,
                              "top_p": round(rec["top_p"], 2) if rec.get("top_p") is not None else None,
                              "top_k": rec.get("top_k"), "min_p": round(rec["min_p"], 3) if rec.get("min_p") is not None else None})
    ctx_train = (meta or {}).get("ctx_train") or 0
    if ctx_train and ctx_train < p["ctx"]:
        p["ctx"] = ctx_train
    return p
