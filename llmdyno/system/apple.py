"""macOS and Apple Silicon detection: CPU, unified memory, the Metal GPU and its live memory use.

The parsing functions take command output as text so they are testable on any OS; the thin wrappers at the bottom
run the commands. Nothing here needs sudo: GPU statistics come from the IOAccelerator registry entry (ioreg), which
is world-readable, not from powermetrics."""
import json
import re
import shutil

# Peak unified-memory bandwidth (GB/s) by chip, used for the rough decode-speed estimate. Variants with fewer GPU
# cores have less bandwidth (M3 Max 30-core: 300, 40-core: 400; M4 Max 32-core: 410, 40-core: 546).
APPLE_BANDWIDTH = {
    "m1 ultra": 800, "m1 max": 400, "m1 pro": 200, "m1": 68,
    "m2 ultra": 800, "m2 max": 400, "m2 pro": 200, "m2": 100,
    "m3 ultra": 819, "m3 max": 400, "m3 pro": 150, "m3": 100,
    "m4 max": 546, "m4 pro": 273, "m4": 120,
    "m5 max": 614, "m5 pro": 307, "m5": 153,
}
REDUCED_BANDWIDTH = {("m3 max", 30): 300, ("m4 max", 32): 410}


def parse_sysctl(text):
    """`sysctl a b c` or `sysctl -a` output -> {name: value}; numbers become int."""
    out = {}
    for line in text.splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        out[k.strip()] = int(v) if re.fullmatch(r"-?\d+", v) else v
    return out


def cpu_from_sysctl(sc):
    """CPU name, core layout and SIMD features from sysctl values (Apple Silicon or Intel Mac)."""
    name = sc.get("machdep.cpu.brand_string") or "Apple CPU"
    arm = sc.get("hw.optional.arm64") == 1 or "Apple" in str(name)
    flags = set()
    if arm:
        flags.add("neon")
        for key, flag in (("hw.optional.arm.FEAT_DotProd", "dotprod"), ("hw.optional.arm.FEAT_I8MM", "i8mm"),
                          ("hw.optional.arm.FEAT_BF16", "bf16"), ("hw.optional.arm.FEAT_FP16", "fp16"),
                          ("hw.optional.arm.FEAT_SME", "sme")):
            if sc.get(key) == 1:
                flags.add(flag)
    else:
        for key, flag in (("hw.optional.avx1_0", "avx"), ("hw.optional.avx2_0", "avx2"), ("hw.optional.avx512f", "avx512f"),
                          ("hw.optional.fma", "fma")):
            if sc.get(key) == 1:
                flags.add(flag)
    return {"name": name, "arm": arm, "flags": flags, "performance_cores": sc.get("hw.perflevel0.physicalcpu"),
            "efficiency_cores": sc.get("hw.perflevel1.physicalcpu")}


def working_set_limit_mib(ram_bytes, wired_limit_mb=0):
    """How much unified memory Metal lets the GPU use.

    `iogpu.wired_limit_mb` overrides it when set (sudo sysctl iogpu.wired_limit_mb=N, reset at reboot). Otherwise macOS
    uses roughly two thirds of RAM on machines up to 36 GB and three quarters above that; llama.cpp's own log
    (recommendedMaxWorkingSetSize) is authoritative and replaces this guess once a model has been loaded."""
    if wired_limit_mb and wired_limit_mb > 0:
        return int(wired_limit_mb)
    ram_mib = ram_bytes / 2**20
    return int(ram_mib * (2 / 3 if ram_mib <= 36 * 1024 else 3 / 4))


def gpu_from_profiler(text):
    """`system_profiler SPDisplaysDataType -json` -> (chip name, GPU core count) of the first Apple GPU."""
    try:
        items = json.loads(text).get("SPDisplaysDataType") or []
    except ValueError:
        return None, None
    for it in items:
        model = it.get("sppci_model") or it.get("_name") or ""
        if "apple" in model.lower() or it.get("sppci_vendor", "").lower().endswith("apple"):
            cores = it.get("sppci_cores")
            return model, int(cores) if str(cores or "").isdigit() else None
    return None, None


def bandwidth(chip, cores=None):
    n = (chip or "").lower().replace("apple ", "")
    for key in sorted(APPLE_BANDWIDTH, key=len, reverse=True):
        if re.search(rf"\b{re.escape(key)}\b", n):
            return REDUCED_BANDWIDTH.get((key, cores), APPLE_BANDWIDTH[key])
    return None


def parse_ioreg_stats(text):
    """PerformanceStatistics of the IOAccelerator entry: GPU memory in use (bytes) and utilisation (%).

    Key names vary a little between GPU generations, so several spellings are accepted and a missing key yields None
    rather than a misleading zero."""
    m = re.search(r'"PerformanceStatistics"\s*=\s*\{(.*?)\}', text, re.S)
    if not m:
        return {}
    body = m.group(1)

    def val(*keys):
        for k in keys:
            mm = re.search(rf'"{re.escape(k)}"\s*=\s*(\d+)', body)
            if mm:
                return int(mm.group(1))
        return None
    used = val("In use system memory", "inUseSystemMemory", "In use system memory (driver)")
    alloc = val("Alloc system memory", "allocSystemMemory")
    util = val("Device Utilization %", "GPU Activity(%)", "Renderer Utilization %")
    return {"in_use_bytes": used, "alloc_bytes": alloc, "util_pct": util}


# ------------------------------------------------------------------ command wrappers (macOS only)
SYSCTL_KEYS = ["machdep.cpu.brand_string", "hw.optional.arm64", "hw.memsize", "hw.perflevel0.physicalcpu",
               "hw.perflevel1.physicalcpu", "iogpu.wired_limit_mb", "hw.optional.arm.FEAT_DotProd",
               "hw.optional.arm.FEAT_I8MM", "hw.optional.arm.FEAT_BF16", "hw.optional.arm.FEAT_FP16",
               "hw.optional.arm.FEAT_SME", "hw.optional.avx1_0", "hw.optional.avx2_0", "hw.optional.avx512f",
               "hw.optional.fma"]


def sysctl(run):
    # unknown keys make sysctl exit non-zero but it still prints the known ones
    _, out, _ = run(["sysctl", *SYSCTL_KEYS])
    return parse_sysctl(out)


def gpu_stats(run):
    if not shutil.which("ioreg"):
        return {}
    code, out, _ = run(["ioreg", "-r", "-d", "1", "-w", "0", "-c", "IOAccelerator"], 10)
    return parse_ioreg_stats(out) if code == 0 else {}


def apple_gpu(run, ram_bytes, sc=None):
    """The Apple GPU as a GPU entry, with the Metal working-set limit standing in for VRAM."""
    sc = sc or sysctl(run)
    if sc.get("hw.optional.arm64") != 1:
        return None
    code, out, _ = run(["system_profiler", "SPDisplaysDataType", "-json"], 30)
    chip, cores = gpu_from_profiler(out) if code == 0 else (None, None)
    chip = chip or str(sc.get("machdep.cpu.brand_string") or "Apple GPU")
    limit = working_set_limit_mib(ram_bytes, sc.get("iogpu.wired_limit_mb") or 0)
    st = gpu_stats(run)
    used = round(st["in_use_bytes"] / 2**20) if st.get("in_use_bytes") is not None else None
    return {"vendor": "Apple", "name": f"{chip} GPU" + (f" ({cores} cores)" if cores else ""), "chip": chip,
            "gpu_cores": cores, "vram_total_mib": limit, "vram_used_mib": used,
            "vram_free_mib": (limit - used) if used is not None else None, "driver": "Metal", "integrated": False,
            "unified": True, "ram_total_mib": round(ram_bytes / 2**20), "wired_limit_set": bool(sc.get("iogpu.wired_limit_mb")),
            "bandwidth_gbs": bandwidth(chip, cores), "backend": "metal"}
