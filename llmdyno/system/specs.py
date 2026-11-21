"""Hardware and software detection for Windows, Linux and macOS on x86-64 and ARM64 (including Apple Silicon).

Everything here is best effort: a missing tool yields None plus a note instead of an exception."""
import ctypes
import json
import os
import platform
import re
import shutil
import subprocess
import time
from pathlib import Path

import psutil

from .. import config
from . import apple

ARCH_ALIASES = {"amd64": "x64", "x86_64": "x64", "x64": "x64", "arm64": "arm64", "aarch64": "arm64", "armv8": "arm64",
                "armv8l": "arm64", "arm64e": "arm64"}
IS_WIN = os.name == "nt"
IS_MAC = platform.system() == "Darwin"
IS_LINUX = platform.system() == "Linux"


def norm_arch(machine=None):
    """'x64' or 'arm64' (the two LLMDyno supports), or the raw machine string for anything else."""
    m = (machine or platform.machine()).lower()
    return ARCH_ALIASES.get(m, m)


def os_family():
    return "windows" if IS_WIN else "macos" if IS_MAC else "linux"

# Peak memory bandwidth (GB/s) for common GPUs, used only for a rough decode-speed estimate.
GPU_BANDWIDTH = {
    "rtx 5090": 1792, "rtx 5080": 960, "rtx 5070 ti": 896, "rtx 5070": 672, "rtx 5060 ti": 448, "rtx 5060": 448,
    "rtx 4090": 1008, "rtx 4080 super": 736, "rtx 4080": 717, "rtx 4070 ti super": 672, "rtx 4070 ti": 504,
    "rtx 4070 super": 504, "rtx 4070": 504, "rtx 4060 ti": 288, "rtx 4060": 272,
    "rtx 3090 ti": 1008, "rtx 3090": 936, "rtx 3080 ti": 912, "rtx 3080": 760, "rtx 3070 ti": 608, "rtx 3070": 448,
    "rtx 3060 ti": 448, "rtx 3060": 360, "rtx 2080 ti": 616, "rtx 2080": 448, "rtx 2070": 448, "rtx 2060": 336,
    "rtx pro 6000": 1792, "rtx 6000 ada": 960, "rtx a6000": 768, "a100": 1935, "h100": 3350, "l40s": 864,
    "rx 9070 xt": 640, "rx 9070": 640, "rx 7900 xtx": 960, "rx 7900 xt": 800, "rx 7800 xt": 624, "rx 7600": 288,
    "arc b580": 456, "arc a770": 560,
}
CPU_FEATURES = {"avx": 39, "avx2": 40, "avx512f": 41}   # Windows IsProcessorFeaturePresent ids (x64)
ARM_FEATURES = {"dotprod": 43, "sve": 46, "sve2": 47}      # PF_ARM_V82_DP, PF_ARM_SVE, PF_ARM_SVE2 (Windows on ARM)
# Linux /proc/cpuinfo "Features" names -> the flags llama.cpp cares about on ARM
LINUX_ARM_FLAGS = {"asimd": "neon", "asimddp": "dotprod", "i8mm": "i8mm", "sve": "sve", "sve2": "sve2", "bf16": "bf16",
                   "fphp": "fp16", "asimdhp": "fp16", "sme": "sme"}


def run(args, timeout=15):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           creationflags=subprocess.CREATE_NO_WINDOW if IS_WIN else 0)
        return p.returncode, p.stdout, p.stderr
    except (OSError, subprocess.TimeoutExpired) as e:
        return -1, "", str(e)


def os_info():
    arch = norm_arch()
    info = {"system": platform.system(), "family": os_family(), "release": platform.release(),
            "version": platform.version(), "arch": arch, "machine": platform.machine(),
            "arch_supported": arch in ("x64", "arm64"), "python": platform.python_version(), "hostname": platform.node()}
    if IS_WIN:
        info["pretty"] = f"Windows {platform.release()} (build {platform.version().split('.')[-1]})"
    elif IS_MAC:
        info["pretty"] = f"macOS {platform.mac_ver()[0] or platform.release()}"
    else:
        try:
            rel = dict(line.split("=", 1) for line in Path("/etc/os-release").read_text().splitlines() if "=" in line)
            info["pretty"] = rel.get("PRETTY_NAME", "Linux").strip('"')
        except OSError:
            info["pretty"] = f"Linux {platform.release()}"
    return info


def arm_flags_linux(cpuinfo_text):
    fm = re.search(r"^Features\s*:\s*(.+)$", cpuinfo_text, re.M)
    return {LINUX_ARM_FLAGS[f] for f in (fm.group(1).split() if fm else []) if f in LINUX_ARM_FLAGS}


def cpu_info():
    name, flags = platform.processor(), set()
    arm = norm_arch() == "arm64"
    extra = {}
    if IS_MAC:
        c = apple.cpu_from_sysctl(apple.sysctl(run))
        name, flags = c["name"], c["flags"]
        extra = {"performance_cores": c["performance_cores"], "efficiency_cores": c["efficiency_cores"]}
    elif IS_WIN:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as k:
                name = winreg.QueryValueEx(k, "ProcessorNameString")[0].strip()
        except OSError:
            pass
        try:
            k32 = ctypes.windll.kernel32
            table = ARM_FEATURES if arm else CPU_FEATURES
            flags = {f for f, pid in table.items() if k32.IsProcessorFeaturePresent(pid)}
            if arm:
                flags.add("neon")           # Advanced SIMD is mandatory on ARMv8
        except (AttributeError, OSError):
            pass
    else:
        try:
            text = Path("/proc/cpuinfo").read_text()
            m = re.search(r"model name\s*:\s*(.+)", text)
            name = m.group(1).strip() if m else name
            if arm:
                flags = arm_flags_linux(text)
                name = _linux_arm_name() or name
            else:
                fm = re.search(r"^flags\s*:\s*(.+)$", text, re.M)
                flags = set(fm.group(1).split()) & {"avx", "avx2", "avx512f", "avx512_bf16", "avx_vnni", "fma"} if fm else set()
        except OSError:
            pass
    try:
        freq = psutil.cpu_freq()
    except (OSError, RuntimeError, NotImplementedError):  # Apple Silicon: "'pmgr' entry was not found" (VMs,
        freq = None                                        # some macOS releases); frequency is cosmetic here
    return {"name": name or "Unknown CPU", "isa": "arm64" if arm else "x64", "cores": psutil.cpu_count(logical=False),
            "threads": psutil.cpu_count(), "max_mhz": round(freq.max) if freq and freq.max else None,
            "avx2": "avx2" in flags, "avx512": "avx512f" in flags, "neon": "neon" in flags,
            "dotprod": "dotprod" in flags, "i8mm": "i8mm" in flags, "sve": "sve" in flags,
            # the SIMD level llama.cpp needs for usable CPU speed: AVX2 on x86-64, NEON with dot product on ARM
            "simd_ok": ("neon" in flags and "dotprod" in flags) if arm else "avx2" in flags,
            "flags": sorted(flags), **extra}


def _linux_arm_name():
    """ARM boards rarely fill "model name"; lscpu or the device tree usually know better."""
    if shutil.which("lscpu"):
        code, out, _ = run(["lscpu"])
        m = re.search(r"Model name:\s*(.+)", out) if code == 0 else None
        if m and m.group(1).strip() not in ("-", ""):
            vendor = re.search(r"Vendor ID:\s*(.+)", out)
            v = vendor.group(1).strip() if vendor else ""
            return (f"{v} " if v and v not in m.group(1) else "") + m.group(1).strip()
    try:
        return Path("/sys/firmware/devicetree/base/model").read_text().strip("\x00\n ")
    except OSError:
        return None


def memory_info():
    vm, sw = psutil.virtual_memory(), psutil.swap_memory()
    return {"total_bytes": vm.total, "available_bytes": vm.available, "swap_total_bytes": sw.total,
            "swap_used_bytes": sw.used}


def _bandwidth(name):
    n = name.lower()
    for key in sorted(GPU_BANDWIDTH, key=len, reverse=True):
        if key in n:
            return GPU_BANDWIDTH[key]
    return None


def nvidia_gpus():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return [], None
    code, out, _ = run([exe, "--query-gpu=index,name,memory.total,memory.used,memory.free,driver_version,"
                             "compute_cap,pcie.link.gen.max,pcie.link.width.max,power.limit,uuid",
                        "--format=csv,noheader,nounits"])
    if code != 0:
        return [], None
    _, head, _ = run([exe])
    cm = re.search(r"CUDA (?:UMD )?Version:\s*([\d.]+)", head)
    gpus = []
    for line in out.strip().splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) < 11:
            continue
        num = lambda v: float(v) if re.fullmatch(r"[\d.]+", v) else None   # noqa: E731
        gpus.append({
            "index": int(f[0]), "vendor": "NVIDIA", "name": f[1], "vram_total_mib": num(f[2]),
            "vram_used_mib": num(f[3]), "vram_free_mib": num(f[4]), "driver": f[5], "compute_cap": f[6],
            "pcie": f"Gen{f[7]} x{f[8]}" if num(f[7]) else None, "power_limit_w": num(f[9]), "uuid": f[10],
            "integrated": False, "bandwidth_gbs": _bandwidth(f[1]), "backend": "cuda",
        })
    return gpus, cm.group(1) if cm else None


def gpu_usage():
    """Fast GPU memory reading for live meters (one nvidia-smi or ioreg query, no full system scan)."""
    if IS_MAC:
        st = apple.gpu_stats(run)
        g = next((x for x in detect()["gpus"] if x.get("unified")), None)
        if not g or st.get("in_use_bytes") is None:
            return []
        return [{"index": 0, "name": g["name"], "vram_used_mib": round(st["in_use_bytes"] / 2**20),
                 "vram_total_mib": g["vram_total_mib"], "util_pct": st.get("util_pct"), "power_w": None}]
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    code, out, _ = run([exe, "--query-gpu=index,name,memory.used,memory.total,utilization.gpu,power.draw",
                        "--format=csv,noheader,nounits"])
    if code != 0:
        return []
    res = []
    for line in out.strip().splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) >= 6:
            num = lambda v: float(v) if re.fullmatch(r"[\d.]+", v) else None   # noqa: E731
            res.append({"index": int(f[0]), "name": f[1], "vram_used_mib": num(f[2]), "vram_total_mib": num(f[3]),
                        "util_pct": num(f[4]), "power_w": num(f[5])})
    return res


def other_gpus_windows():
    """AMD / Intel adapters from the display class registry (WMI caps AdapterRAM at 4 GB, the registry does not)."""
    gpus = []
    try:
        import winreg
        base = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as root:
            for i in range(winreg.QueryInfoKey(root)[0]):
                sub = winreg.EnumKey(root, i)
                if not sub.isdigit():
                    continue
                try:
                    with winreg.OpenKey(root, sub) as k:
                        desc = winreg.QueryValueEx(k, "DriverDesc")[0]
                        try:
                            mem = int(winreg.QueryValueEx(k, "HardwareInformation.qwMemorySize")[0])
                        except OSError:
                            mem = 0
                        try:
                            drv = winreg.QueryValueEx(k, "DriverVersion")[0]
                        except OSError:
                            drv = ""
                except OSError:
                    continue
                vendor = ("AMD" if re.search(r"amd|radeon", desc, re.I) else "Intel" if re.search(r"intel|arc", desc, re.I)
                          else "Qualcomm" if re.search(r"qualcomm|adreno", desc, re.I) else None)
                if vendor == "Qualcomm":
                    # Snapdragon X: an integrated Adreno GPU sharing system RAM; llama.cpp ships an OpenCL Adreno build
                    gpus.append({"vendor": vendor, "name": desc, "vram_total_mib": None, "vram_used_mib": None,
                                 "vram_free_mib": None, "driver": drv, "integrated": True, "bandwidth_gbs": 135,
                                 "backend": "opencl-adreno"})
                    continue
                if not vendor or not mem:
                    continue
                integrated = mem <= 4 * 1024**3 and bool(re.search(r"graphics(?!.*(rx|arc))", desc, re.I))
                gpus.append({"vendor": vendor, "name": desc, "vram_total_mib": round(mem / 2**20), "vram_used_mib": None,
                             "vram_free_mib": None, "driver": drv, "integrated": integrated,
                             "bandwidth_gbs": _bandwidth(desc), "backend": "vulkan" if vendor == "Intel" else "rocm"})
    except (ImportError, OSError):
        pass
    return gpus


def other_gpus_linux():
    gpus = []
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]")):
        dev = card / "device"
        try:
            vendor_id = (dev / "vendor").read_text().strip()
        except OSError:
            continue
        if vendor_id not in ("0x1002", "0x8086"):
            continue
        total = None
        for f in ("mem_info_vram_total", "lmem_total_bytes"):
            try:
                total = int((dev / f).read_text()) // 2**20
            except (OSError, ValueError):
                pass
        name = "AMD GPU" if vendor_id == "0x1002" else "Intel GPU"
        code, out, _ = run(["lspci", "-s", dev.resolve().name, "-mm"]) if shutil.which("lspci") else (1, "", "")
        if code == 0 and out:
            parts = re.findall(r'"([^"]*)"', out)
            name = parts[2] if len(parts) > 2 else name
        gpus.append({"vendor": "AMD" if vendor_id == "0x1002" else "Intel", "name": name, "vram_total_mib": total,
                     "vram_used_mib": None, "vram_free_mib": None, "driver": "", "integrated": not total or total <= 4096,
                     "bandwidth_gbs": _bandwidth(name), "backend": "rocm" if vendor_id == "0x1002" else "vulkan"})
    return gpus


def shared_gpu_usage_mib():
    """Windows only: shared (system RAM) memory in use per GPU adapter, the signature of a VRAM spill."""
    if not IS_WIN:
        return None
    code, out, _ = run(["powershell", "-NoProfile", "-Command",
                        "(Get-Counter '\\GPU Adapter Memory(*)\\Shared Usage','\\GPU Adapter Memory(*)\\Dedicated Usage')"
                        ".CounterSamples | ForEach-Object { $_.Path + '=' + $_.CookedValue }"], timeout=20)
    if code != 0:
        return None
    adapters = {}
    for line in out.splitlines():
        m = re.search(r"\((luid_[^)]+)\)\\(shared|dedicated) usage=([\d.]+)", line, re.I)
        if m:
            adapters.setdefault(m.group(1), {})[m.group(2).lower()] = round(float(m.group(3)) / 2**20)
    return adapters


def disk_info():
    out = []
    seen = set()
    for label, key in (("Data", None), ("Models", "models_dir"), ("Runs", "runs_dir")):
        p = Path(config.get(key)) if key else config.DATA
        while not p.exists() and p.parent != p:
            p = p.parent
        try:
            u = psutil.disk_usage(str(p))
        except OSError:
            continue
        anchor = p.anchor or str(p)
        if anchor in seen and label != "Data":
            continue
        seen.add(anchor)
        out.append({"label": label, "path": str(p), "total_bytes": u.total, "free_bytes": u.free})
    return out


def docker_info():
    exe = shutil.which("docker")
    if not exe:
        return {"installed": False, "running": False}
    code, out, err = run([exe, "version", "--format", "{{json .}}"], timeout=20)
    try:
        v = json.loads(out) if out.strip() else {}
    except ValueError:
        v = {}
    client = (v.get("Client") or {}).get("Version")
    server = v.get("Server") or {}
    info = {"installed": True, "client_version": client, "running": bool(server),
            "server_version": server.get("Version"), "os_arch": f"{server.get('Os')}/{server.get('Arch')}" if server else None,
            "arch": norm_arch(server.get("Arch")) if server.get("Arch") else None,
            "error": None if server else (err.strip().splitlines() or ["daemon not reachable"])[-1][:300]}
    if server:
        code, out, _ = run([exe, "info", "--format", "{{.MemTotal}} {{.NCPU}} {{.OperatingSystem}}"], timeout=20)
        parts = out.split(maxsplit=2)
        if code == 0 and len(parts) >= 2:
            info.update({"mem_total_bytes": int(parts[0]), "ncpu": int(parts[1]),
                         "engine_os": parts[2].strip() if len(parts) > 2 else ""})
        code, out, _ = run([exe, "info", "--format", "{{json .Runtimes}}"], timeout=20)
        info["nvidia_runtime"] = "nvidia" in out
    return info


_cache = {"t": 0.0, "data": None}


def detect(force=False):
    if not force and _cache["data"] and time.time() - _cache["t"] < 20:
        return _cache["data"]
    mem = memory_info()
    if IS_MAC:
        nv, cuda = [], None
        ag = apple.apple_gpu(run, mem["total_bytes"])
        others = [ag] if ag else []
    else:
        nv, cuda = nvidia_gpus()
        others = other_gpus_windows() if IS_WIN else other_gpus_linux()
    gpus = nv + [g for g in others if g["vendor"] != "NVIDIA"]
    data = {"os": os_info(), "cpu": cpu_info(), "memory": mem, "gpus": gpus, "cuda_version": cuda,
            "disks": disk_info(), "docker": docker_info(), "detected_at": time.time()}
    data["summary"] = summarize(data)
    _cache.update(t=time.time(), data=data)
    return data


def primary_gpu(specs):
    """The GPU llama.cpp would run on: the biggest discrete (or Apple unified-memory) GPU. Integrated graphics only
    count when nothing else exists and llama.cpp has a backend worth using for them (Snapdragon's Adreno)."""
    discrete = [g for g in specs["gpus"] if not g.get("integrated") and g.get("vram_total_mib")]
    if discrete:
        return max(discrete, key=lambda g: g["vram_total_mib"])
    adreno = next((g for g in specs["gpus"] if g.get("backend") == "opencl-adreno"), None)
    if adreno:
        # shares system RAM; leave room for Windows like macOS does for its GPU
        return {**adreno, "vram_total_mib": round(specs["memory"]["total_bytes"] / 2**20 * 0.6), "unified": True}
    return None


def summarize(s):
    """Headline capability statements for the setup screen."""
    g = primary_gpu(s)
    ram_gb = s["memory"]["total_bytes"] / 2**30
    notes = []
    if not s["os"]["arch_supported"]:
        notes.append({"level": "danger", "text": f"Architecture {s['os']['arch']} is not supported; LLMDyno runs on "
                      "x86-64 and ARM64 (including Apple Silicon)."})
    if g and g.get("vendor") == "Apple":
        lim = g["vram_total_mib"] / 1024
        notes.append({"level": "info", "text": f"{g['chip']} with {ram_gb:.0f} GB unified memory: Metal lets the GPU use "
                      f"about {lim:.0f} GB, so models up to about {max(lim - 3, 0):.0f} GB of weights fit with a 64k context."})
        if not g.get("wired_limit_set"):
            notes.append({"level": "info", "text": "To give the GPU more of the unified memory, run "
                          f"sudo sysctl iogpu.wired_limit_mb={int(ram_gb * 1024 * 0.85)} (it resets at reboot; leave at "
                          "least 8 GB for macOS)."})
        notes.append({"level": "warning", "text": "If a model needs more than the GPU's share, macOS compresses and swaps "
                      "memory instead of failing, and decoding slows to a crawl. LLMDyno refuses such profiles unless "
                      "the plan allows it."})
    elif g and g.get("backend") == "opencl-adreno":
        notes.append({"level": "info", "text": f"{g['name']}: an integrated GPU sharing system RAM. llama.cpp's OpenCL "
                      "Adreno build accelerates quantized models; the Vulkan and CPU builds also work."})
    elif g:
        vram_gb = g["vram_total_mib"] / 1024
        budget = max(vram_gb - 2.5, 0)
        notes.append({"level": "info", "text": f"{g['name']} with {vram_gb:.0f} GB VRAM: models up to about "
                      f"{budget:.0f} GB of weights fit fully on the GPU with a 64k context."})
        if g["vendor"] != "NVIDIA":
            notes.append({"level": "warning", "text": f"{g['vendor']} GPUs use the {g['backend'].upper()} build of llama.cpp; "
                          "speed and memory estimates are less precise than on NVIDIA."})
        if IS_WIN and g["vendor"] == "NVIDIA":
            notes.append({"level": "warning", "text": "On Windows, NVIDIA drivers spill to shared system memory instead of "
                          "failing when VRAM runs out (Sysmem Fallback). It looks like it works but runs 5-20x slower; "
                          "LLMDyno watches shared GPU memory during runs and flags it."})
    else:
        notes.append({"level": "warning", "text": "No discrete GPU found: local models would run on the CPU, which is "
                      "slow for agentic tasks with long contexts. Cloud providers work normally."})
    if not s["cpu"].get("simd_ok", s["cpu"].get("avx2")):
        missing = "NEON dot-product instructions" if s["cpu"].get("isa") == "arm64" else "AVX2"
        notes.append({"level": "warning", "text": f"CPU without {missing}: CPU inference and offloaded layers will be very slow."})
    if not (g and g.get("unified")):
        notes.append({"level": "info", "text": f"{ram_gb:.0f} GB system RAM" + (
            "; enough to offload some MoE experts to the CPU." if ram_gb >= 32 else "; little room for CPU offload.")})
    d = s["docker"]
    if d.get("running") and norm_arch(str(d.get("os_arch") or "").split("/")[-1]) == "arm64":
        notes.append({"level": "info", "text": "Docker runs ARM64 Linux containers here, so the built-in benchmarks run "
                      "natively. SWE-bench task images are x86-64 and run under emulation: in Docker Desktop, turn on "
                      "'Use Rosetta for x86_64/amd64 emulation'."})
    if not s["docker"].get("running"):
        notes.append({"level": "danger", "text": "Docker is not running. Agents and graders run in Docker sandboxes, so "
                      "benchmarks cannot start until it is."})
    return {"primary_gpu": g, "notes": notes}
