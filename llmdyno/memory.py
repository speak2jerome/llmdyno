"""Memory projection and risk warnings for a local profile.

estimate()  works from GGUF metadata alone (before download): weights per layer from the tensor table, KV cache per
            layer (sliding-window, hybrid recurrent, shared-KV and MLA layers handled), compute buffers from a
            calibrated model, and CUDA context overhead.
check()     combines the estimate (or an exact llama-fit-params dry run when the file is local) with live free VRAM
            and RAM, and produces a verdict plus actionable warnings."""
import math

MIB = 2**20
CACHE_BYTES = {"f32": 4.0, "f16": 2.0, "bf16": 2.0, "q8_0": 34 / 32, "q5_1": 24 / 32, "q5_0": 22 / 32,
               "q4_1": 20 / 32, "q4_0": 18 / 32, "iq4_nl": 18 / 32}
CUDA_OVERHEAD_MIB = 250          # CUDA context and allocator slack beyond llama.cpp's own buffers (34-276 MiB measured)
LOW_BIT = ("IQ1", "IQ2", "Q2_K", "TQ1", "TQ2")


def kv_layers(meta, params):
    """Per-layer KV cache bytes at the profile's context (index = layer)."""
    ctx = int(params["ctx"])
    ub = int(params.get("ubatch") or 512)
    n_layer = meta["n_layer"]
    bk = CACHE_BYTES.get(params.get("cache_k", "f16"), 2.0)
    bv = CACHE_BYTES.get(params.get("cache_v", "f16"), 2.0)
    swa = meta.get("sliding_window") or 0
    swa_ctx = min(ctx, int(math.ceil((swa + ub) / 256) * 256)) if swa else ctx
    shared = meta.get("shared_kv_layers") or 0
    nextn = meta.get("nextn_layers") or 0
    klen, vlen = meta.get("key_length") or 0, meta.get("value_length") or 0
    klen_swa = meta.get("key_length_swa") or klen
    vlen_swa = meta.get("value_length_swa") or vlen
    out = []
    for i in range(n_layer):
        if meta["recurrent_layers"][i] or i >= n_layer - shared - nextn or not meta["n_head_kv"][i]:
            out.append(0)
            continue
        is_swa = meta["swa_layers"][i] and not params.get("swa_full")
        c = swa_ctx if is_swa else ctx
        if meta.get("kv_lora_rank"):
            per_tok = (meta["kv_lora_rank"] + (meta.get("rope_dim") or 0)) * bk
        else:
            kl, vl = (klen_swa, vlen_swa) if meta["swa_layers"][i] else (klen, vlen)
            per_tok = meta["n_head_kv"][i] * (kl * bk + vl * bv)
        out.append(c * per_tok)
    return out


def recurrent_state_bytes(meta, params):
    n_rec = sum(meta["recurrent_layers"])
    if not n_rec:
        return 0
    inner = meta.get("ssm_inner") or meta["n_embd"] * 2
    state = meta.get("ssm_state") or 128
    conv = max((meta.get("ssm_conv") or 4) - 1, 1)
    per_layer = (inner * state + conv * (inner + 2 * (meta.get("ssm_groups") or 1) * state)) * 4
    return n_rec * per_layer * int(params.get("parallel", 1))


def compute_bytes(meta, params):
    """CUDA compute buffer, fitted on llama-fit-params output for 14 GGUFs x 3 contexts x 2 cache types
    (scripts/calibrate_memory.py): logits for one ubatch, a small constant, ~1 MiB per 1k context per 512-token
    ubatch, and extra conversion space for quantized caches beyond 64k."""
    ctx, ub = int(params["ctx"]), int(params.get("ubatch") or 512)
    logits = meta["n_vocab"] * ub * 4
    per_ctx = ctx / 1024 * MIB * ub / 512
    quant = params.get("cache_k", "f16") not in ("f16", "f32", "bf16") or params.get("cache_v", "f16") not in ("f16", "f32", "bf16")
    extra = max(0, ctx - 65536) / 1024 * 0.7 * MIB if quant else 0
    if params.get("flash_attn", "on") == "off":
        per_ctx += ctx * ub * 4 * max(meta.get("n_head") or 8, 8) / 8
    return logits + 35 * MIB + per_ctx + extra


def placement(meta, params):
    """Which layers / experts live on the GPU."""
    n_layer = meta["n_layer"]
    ngl = params.get("gpu_layers", "all")
    if ngl in ("all", None, -1, 999) or (isinstance(ngl, int) and ngl > n_layer):
        gpu_layers, output_gpu = set(range(n_layer)), True
    else:
        ngl = int(ngl)
        gpu_layers, output_gpu = set(range(max(n_layer - ngl, 0), n_layer)), False
    cpu_moe = int(params.get("n_cpu_moe") or 0)
    return gpu_layers, output_gpu, cpu_moe


def estimate(meta, params):
    """Projected memory in MiB on the GPU and in host RAM."""
    gpu_layers, output_gpu, cpu_moe = placement(meta, params)
    kv = kv_layers(meta, params)
    w_gpu = w_cpu = 0
    nextn = meta.get("nextn_layers") or 0
    for i in range(meta["n_layer"]):
        if i >= meta["n_layer"] - nextn:
            continue                                   # multi-token-prediction layers are not loaded for decoding
        lb, eb = meta["layer_bytes"][i], meta["expert_bytes"][i]
        if i in gpu_layers:
            moved = eb if i < cpu_moe else 0
            w_gpu += lb - moved
            w_cpu += moved
        else:
            w_cpu += lb
    out_b = meta.get("output_bytes") or 0
    if meta.get("tied_embeddings"):
        out_b = meta.get("embd_bytes") or 0          # tied output reuses token_embd; llama.cpp keeps a GPU copy
    if output_gpu:
        w_gpu += out_b
    else:
        w_cpu += out_b
    w_cpu += meta.get("embd_bytes") or 0               # token embeddings stay in host memory
    kv_gpu = sum(b for i, b in enumerate(kv) if i in gpu_layers)
    kv_cpu = sum(kv) - kv_gpu
    rs = recurrent_state_bytes(meta, params)
    comp = compute_bytes(meta, params) if gpu_layers else 0
    gpu = {"weights": w_gpu / MIB, "kv": (kv_gpu + rs) / MIB, "compute": comp / MIB,
           "overhead": CUDA_OVERHEAD_MIB if gpu_layers else 0}
    cpu = {"weights": w_cpu / MIB, "kv": kv_cpu / MIB, "compute": (meta["n_vocab"] * 4 * 512 + 96 * MIB) / MIB}
    return {"gpu": {k: round(v) for k, v in gpu.items()}, "gpu_total": round(sum(gpu.values())),
            "cpu": {k: round(v) for k, v in cpu.items()}, "cpu_total": round(sum(cpu.values())),
            "gpu_layers": len(gpu_layers), "n_layer": meta["n_layer"], "kv_per_1k_tokens_mib": round(
                sum(kv) / max(params["ctx"], 1) * 1000 / MIB, 2),
            "source": "estimate"}


def from_fit(fit):
    """Turn a llama-fit-params breakdown into the same shape as estimate()."""
    d = fit["devices"][0] if fit.get("devices") else None
    h = fit.get("host") or {}
    if not d:
        return None
    gpu = {"weights": d["model"], "kv": d["ctx"], "compute": d["compute"], "overhead": CUDA_OVERHEAD_MIB}
    cpu = {"weights": h.get("model", 0), "kv": h.get("ctx", 0), "compute": h.get("compute", 0)}
    return {"gpu": gpu, "gpu_total": sum(gpu.values()), "cpu": cpu, "cpu_total": sum(cpu.values()),
            "device": d["dev"], "source": "llama-fit-params", "fitted_ngl": fit.get("fitted_ngl")}


def decode_tps_estimate(meta, params, mem, gpu):
    """Bandwidth roofline: bytes touched per token / effective bandwidth. Rough, shown with a tilde."""
    if not gpu or not gpu.get("bandwidth_gbs"):
        return None
    active = meta["total_bytes"]
    if meta.get("expert_count") and meta.get("expert_used"):
        exp = sum(meta["expert_bytes"])
        active = active - exp + exp * meta["expert_used"] / meta["expert_count"]
    embd = meta.get("embd_bytes") or 0
    active -= embd
    # token embeddings live in host memory but only one row is read per token, so they do not slow decoding
    cpu_share = max(mem["cpu"]["weights"] * MIB - embd, 0) / max(meta["total_bytes"], 1)
    gpu_time = active * (1 - cpu_share) / (gpu["bandwidth_gbs"] * 1e9 * 0.62)
    cpu_time = active * cpu_share / (60e9 * 0.6)                 # dual-channel DDR5 class
    t = gpu_time + cpu_time
    return round(1 / t, 1) if t > 0 else None


def warning(level, code, text, fix=None):
    return {"level": level, "code": code, "text": text, "fix": fix}


def check(meta, params, specs, fit=None, os_name="nt", benchmarks=None):
    """Verdict + warnings. `fit` is an optional llama-fit-params result (exact, local files only)."""
    from .system.specs import primary_gpu

    est = estimate(meta, params)
    exact = from_fit(fit) if fit else None
    mem = exact or est
    g = primary_gpu(specs)
    free = (g.get("vram_free_mib") or g.get("vram_total_mib") or 0) if g else 0
    total = (g.get("vram_total_mib") or 0) if g else 0
    ram_avail = specs["memory"]["available_bytes"] / MIB
    ram_total = specs["memory"]["total_bytes"] / MIB
    need_gpu = mem["gpu_total"] if g else 0
    need_cpu = mem["cpu_total"] + (0 if g else mem["gpu_total"])
    headroom = free - need_gpu
    w = []
    ctx = int(params["ctx"])
    ngl_all = params.get("gpu_layers", "all") in ("all", None, -1, 999)
    win = os_name == "nt"

    if not g:
        verdict = "cpu"
        w.append(warning("danger", "cpu_only", "No usable GPU: the whole model runs on the CPU. Agentic benchmarks with "
                         "tens of thousands of context tokens can take hours per task."))
        if not specs["cpu"].get("avx2"):
            w.append(warning("danger", "no_avx2", "This CPU has no AVX2, so CPU inference will be extremely slow."))
    elif headroom < 0:
        verdict = "spill" if win else "oom"
        if win:
            w.append(warning("danger", "spill", f"Needs {need_gpu / 1024:.1f} GB on the GPU but only {free / 1024:.1f} GB is free. "
                             "On Windows the driver silently spills the rest into shared system memory: the run works "
                             "but decoding can be 5-20x slower and results will not reflect the model's real speed.",
                             fix=_shrink_fix(meta, params, -headroom)))
        else:
            w.append(warning("danger", "oom", f"Needs {need_gpu / 1024:.1f} GB on the GPU but only {free / 1024:.1f} GB is free: "
                             "llama-server will fail to allocate (out of memory).", fix=_shrink_fix(meta, params, -headroom)))
    elif headroom < 600:
        verdict = "tight"
        w.append(warning("warning", "tight", f"Only {headroom:.0f} MiB of VRAM would remain. Browsers, the desktop and other "
                         "apps also use VRAM, so this can tip into a spill or OOM mid-run.", fix=_shrink_fix(meta, params, 600 - headroom)))
    else:
        verdict = "fits"

    if g and ngl_all and params.get("auto_fit") and headroom < (params.get("fit_margin_mib") or 1024):
        w.append(warning("warning", "autofit", "llama.cpp's auto-fit (on by default) keeps a 1 GiB margin and would move "
                         "layers to the CPU here without telling you. LLMDyno launches with auto-fit off and your "
                         "exact layer count; leave it on only if you accept silent offload."))
    if g and (mem["cpu"]["weights"] > (meta.get("embd_bytes", 0) / MIB) + 64):
        moved_gb = (mem["cpu"]["weights"] - meta.get("embd_bytes", 0) / MIB) / 1024
        what = "MoE expert weights" if params.get("n_cpu_moe") else "layers"
        w.append(warning("warning", "cpu_offload", f"{moved_gb:.1f} GB of {what} run on the CPU. Decode speed is then "
                         "limited by system RAM bandwidth, typically 2-6x slower than fully on the GPU."))
    if need_cpu > ram_avail * 0.9:
        w.append(warning("danger" if need_cpu > ram_total else "warning", "ram",
                         f"Host side needs about {need_cpu / 1024:.1f} GB but only {ram_avail / 1024:.1f} GB RAM is free; "
                         "the OS will page to disk and runs will crawl."))
    if meta.get("ctx_train") and ctx > meta["ctx_train"]:
        w.append(warning("warning", "ctx_train", f"Context {ctx:,} exceeds the model's trained context "
                         f"{meta['ctx_train']:,}; quality degrades without RoPE scaling.",
                         fix={"label": f"Use {meta['ctx_train'] // 1024}k", "params": {"ctx": meta["ctx_train"]}}))
    if ctx < 32768:
        w.append(warning("warning", "ctx_small", f"{ctx // 1024}k context is small for agentic coding: system prompt and "
                         "tool schemas alone take 5-15k tokens, so harnesses will compact or fail on longer tasks.",
                         fix={"label": "Use 64k", "params": {"ctx": 65536}}))
    for b in benchmarks or []:
        need = b.get("min_context") or 0
        if need and ctx < need:
            w.append(warning("warning", "ctx_benchmark", f"'{b['title']}' peaked around {need // 1000}k tokens in reference "
                             f"runs; {ctx // 1024}k may force compaction or truncation."))
    if params.get("cache_v", "f16") not in ("f16", "f32", "bf16") and params.get("flash_attn", "on") == "off":
        w.append(warning("danger", "v_quant_no_fa", "A quantized V cache requires flash attention; llama-server will refuse "
                         "to start.", fix={"label": "Turn flash attention on", "params": {"flash_attn": "on"}}))
    if params.get("cache_k", "f16").startswith("q4") or params.get("cache_v", "f16").startswith("q4"):
        w.append(warning("info", "kv_q4", "A 4-bit KV cache saves memory but measurably hurts long-context recall and "
                         "tool-call accuracy; q8_0 is close to lossless.",
                         fix={"label": "Use q8_0 KV", "params": {"cache_k": "q8_0", "cache_v": "q8_0"}}))
    main_type = next(iter(meta.get("tensor_types") or {}), "")
    if any(main_type.startswith(p) for p in LOW_BIT):
        w.append(warning("info", "low_bit", f"Mostly {main_type} weights: 1-2 bit quants lose noticeable coding accuracy; "
                         "compare against a 3-4 bit quant before drawing conclusions."))
    if not meta.get("chat_template_tools"):
        w.append(warning("danger" if meta.get("has_chat_template") else "warning", "no_tools",
                         "The chat template has no tool-calling section, so agent harnesses cannot call tools with this "
                         "model (they will fail or fall back to text parsing)."))
    if meta.get("chat_template_thinking") and (params.get("max_output_tokens") or 0) and params["max_output_tokens"] < 8192:
        w.append(warning("warning", "max_tokens", "Reasoning models need room to think: an output limit below 8k tokens "
                         "truncates answers mid-thought.", fix={"label": "Use 16k", "params": {"max_output_tokens": 16384}}))
    if int(params.get("parallel", 1)) > 1:
        w.append(warning("info", "parallel", f"{params['parallel']} parallel slots share the context: each agent sees about "
                         f"{ctx // int(params['parallel']) // 1024}k tokens."))
    s = params.get("sampling") or {}
    if s.get("temperature") is not None and s["temperature"] > 1.3:
        w.append(warning("info", "temp", "Temperature above 1.3 makes tool-call JSON error-prone."))
    rec = meta.get("sampling") or {}
    if rec and s and rec.get("temp") is not None and s.get("temperature") is not None and abs(rec["temp"] - s["temperature"]) > 0.4:
        w.append(warning("info", "sampling_rec", f"The model ships recommended sampling (temperature {rec['temp']:.2g}"
                         f", top_k {rec.get('top_k', '-')}, top_p {rec.get('top_p', 0):.2g}).",
                         fix={"label": "Use recommended", "params": {"sampling": {"temperature": round(rec["temp"], 2),
                              "top_k": rec.get("top_k"), "top_p": round(rec.get("top_p", 0.95), 2)}}}))
    return {"verdict": verdict, "memory": mem, "estimate": est, "exact": exact, "gpu": g and {"name": g["name"],
            "total_mib": total, "free_mib": free}, "headroom_mib": round(headroom) if g else None,
            "ram_available_mib": round(ram_avail), "decode_tps_estimate": decode_tps_estimate(meta, params, mem, g),
            "warnings": w}


def _shrink_fix(meta, params, need_mib):
    """Cheapest single change that frees `need_mib`: smaller KV type, smaller context, or MoE offload."""
    need = need_mib * MIB
    kv_now = sum(kv_layers(meta, params))
    if params.get("cache_k") in ("f16", "f32", "bf16", None) or params.get("cache_v") in ("f16", "f32", "bf16", None):
        q8 = {**params, "cache_k": "q8_0", "cache_v": "q8_0"}
        if kv_now - sum(kv_layers(meta, q8)) >= need:
            return {"label": "Use q8_0 KV cache", "params": {"cache_k": "q8_0", "cache_v": "q8_0"}}
    ctx = int(params["ctx"])
    for c in (196608, 131072, 98304, 65536, 49152, 32768):
        if c < ctx and kv_now - sum(kv_layers(meta, {**params, "ctx": c})) - (compute_bytes(meta, params) -
                                                                              compute_bytes(meta, {**params, "ctx": c})) * -1 >= need:
            return {"label": f"Reduce context to {c // 1024}k", "params": {"ctx": c}}
    if meta.get("expert_count"):
        acc = 0
        for i, eb in enumerate(meta["expert_bytes"]):
            acc += eb
            if acc >= need:
                return {"label": f"Offload experts of {i + 1} layers to CPU", "params": {"n_cpu_moe": i + 1}}
    per_layer = max(meta["layer_bytes"]) or 1
    layers = min(meta["n_layer"], math.ceil(need / per_layer) + 1)
    return {"label": f"Offload {layers} layers to CPU", "params": {"gpu_layers": meta["n_layer"] - layers}}
