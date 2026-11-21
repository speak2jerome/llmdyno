"""llama.cpp: install prebuilt releases, run llama-server, and dry-run memory fits with llama-fit-params."""
import json
import os
import re
import shutil
import subprocess
import tarfile
import threading
import time
import zipfile
from pathlib import Path

import httpx
import psutil

from .. import config
from ..system import specs as sysspecs

RELEASES_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=12"
IS_WIN = os.name == "nt"
EXE = ".exe" if IS_WIN else ""


# ------------------------------------------------------------------ release assets
# Release assets are named like llama-b12606-bin-win-cuda-13.5-x64.zip, llama-b12606-bin-macos-arm64.tar.gz or
# llama-b12606-bin-ubuntu-vulkan-arm64.tar.gz; CUDA builds come with a separate cudart-llama-... runtime archive.
# The names are parsed rather than hardcoded because the CUDA/ROCm/OpenVINO versions move with every few releases.
ASSET_RE = re.compile(r"^llama-(?P<tag>b\d+)-bin-(?P<os>win|ubuntu|macos|linux)-(?P<spec>.+?)\.(?:zip|tar\.gz)$")
CUDART_RE = re.compile(r"^cudart-llama-(?:b\d+-)?bin-(?P<os>win|ubuntu)-cuda-(?P<ver>[\d.]+)-(?P<arch>x64|arm64)\."
                       r"(?:zip|tar\.gz)$")
ARCHES = ("x64", "arm64", "s390x")
OS_KEYS = {"windows": ("win",), "linux": ("ubuntu", "linux"), "macos": ("macos",)}


def parse_asset(name):
    """-> {os, arch, backend, version, flavor} for a llama.cpp binary archive, or None for anything else."""
    m = ASSET_RE.match(name)
    if not m:
        return None
    toks = m.group("spec").split("-")
    arch = next((t for t in toks if t in ARCHES), None)
    if not arch:
        return None
    ver = next((t for t in toks if re.fullmatch(r"\d+(\.\d+)+", t)), None)
    rest = [t for t in toks if t != arch and t != ver]
    os_ = m.group("os")
    if not rest:                                   # ubuntu-x64 is the CPU build; macos-arm64 includes Metal
        backend = "metal" if os_ == "macos" and arch == "arm64" else "cpu"
    elif rest[0] == "opencl":
        backend = "opencl-" + "-".join(rest[1:]) if rest[1:] else "opencl"
    else:
        backend = rest[0]
    flavor = "-".join(rest[1:]) if backend in ("sycl",) else ""
    return {"tag": m.group("tag"), "os": os_, "arch": arch, "backend": backend, "version": ver, "flavor": flavor}


def _ver_key(v):
    return tuple(int(x) for x in (v or "0").split("."))


def pick_assets(assets, os_family, arch, variant):
    """Main archive (plus the CUDA runtime archive when there is one) for a variant id such as 'cuda-13', 'cuda-12',
    'vulkan', 'metal', 'rocm', 'sycl', 'openvino', 'opencl-adreno' or 'cpu' on this OS/arch. None if absent."""
    want_backend, _, want_major = variant.partition("-") if variant.startswith("cuda-") else (variant, "", "")
    cands = []
    for a in assets:
        p = parse_asset(a["name"])
        if not p or p["os"] not in OS_KEYS[os_family] or p["arch"] != arch or p["backend"] != want_backend:
            continue
        if want_major and not (p["version"] or "").startswith(want_major + "."):
            continue
        if p["backend"] == "sycl" and p["flavor"] not in ("", "fp16"):
            continue                               # fp16 is the faster SYCL build; fp32 is for old iGPUs
        cands.append((p, a))
    if not cands:
        return None
    p, main = max(cands, key=lambda c: _ver_key(c[0]["version"]))
    if p["backend"] != "cuda":
        return [main]
    rt = next((a for a in assets if (m := CUDART_RE.match(a["name"])) and m["os"] == p["os"] and m["arch"] == arch
               and m["ver"] == p["version"]), None)
    return [main, rt] if rt else ([main] if os_family != "windows" else None)   # Windows needs the CUDA DLLs


def available_backends(assets, os_family, arch):
    """Every variant id this release offers for the OS/arch (used to show what can be installed)."""
    out = set()
    for a in assets:
        p = parse_asset(a["name"])
        if p and p["os"] in OS_KEYS[os_family] and p["arch"] == arch:
            out.add(f"cuda-{p['version'].split('.')[0]}" if p["backend"] == "cuda" and p["version"] else p["backend"])
    return out


VARIANT_LABEL = {"cuda-13": "CUDA 13", "cuda-12": "CUDA 12", "vulkan": "Vulkan", "metal": "Metal", "rocm": "ROCm",
                 "sycl": "SYCL", "openvino": "OpenVINO", "opencl-adreno": "OpenCL (Adreno)", "cpu": "CPU only"}


def variants(s=None):
    """Backend builds that make sense on this machine, best first."""
    s = s or sysspecs.detect()
    g = sysspecs.primary_gpu(s)
    fam, arch = s["os"].get("family") or sysspecs.os_family(), s["os"]["arch"]
    out = []
    if fam == "macos":
        if arch == "arm64":
            out.append({"id": "metal", "ok": True, "why": "Apple GPU through Metal, using unified memory"})
        out.append({"id": "cpu", "ok": True, "why": "Intel Mac: CPU build" if arch == "x64" else "no GPU acceleration"})
    else:
        if g and g["vendor"] == "NVIDIA":
            try:
                major = int(str(g.get("driver", "0")).split(".")[0])
            except ValueError:
                major = 0
            new_cuda = major >= 580
            out += [{"id": "cuda-13", "ok": new_cuda,
                     "why": "best for this GPU" if new_cuda else "needs NVIDIA driver 580 or newer"},
                    {"id": "cuda-12", "ok": True, "why": "for older drivers"}]
            out.sort(key=lambda v: not v["ok"])
        elif g and g["vendor"] == "AMD":
            out += [{"id": "vulkan", "ok": True, "why": "works on most Radeon GPUs"},
                    {"id": "rocm", "ok": True, "why": "faster on supported Radeon GPUs"}]
        elif g and g["vendor"] == "Intel":
            out += [{"id": "vulkan", "ok": True, "why": "works on Arc GPUs"},
                    {"id": "sycl", "ok": True, "why": "Intel oneAPI build"},
                    {"id": "openvino", "ok": True, "why": "Intel OpenVINO build"}]
        elif g and g.get("backend") == "opencl-adreno":
            out.append({"id": "opencl-adreno", "ok": True, "why": "Snapdragon Adreno GPU"})
        out += [{"id": "vulkan", "ok": True, "why": "generic GPU build"},
                {"id": "cpu", "ok": True, "why": "no GPU acceleration"}]
    seen, uniq = set(), []
    for v in out:
        if v["id"] not in seen:
            seen.add(v["id"])
            uniq.append({**v, "label": VARIANT_LABEL.get(v["id"], v["id"])})
    return uniq


def find_release(variant, os_family=None, arch=None):
    """Newest release whose assets for `variant` on this OS/arch are fully uploaded (fresh builds upload over a few
    minutes, so the very newest tag can be incomplete)."""
    os_family = os_family or sysspecs.os_family()
    arch = arch or sysspecs.norm_arch()
    r = httpx.get(RELEASES_API, timeout=30, headers={"Accept": "application/vnd.github+json"})
    r.raise_for_status()
    for rel in r.json():
        if not re.fullmatch(r"b\d+", rel["tag_name"]):
            continue
        assets = [a for a in rel.get("assets", []) if a.get("state", "uploaded") == "uploaded"]
        chosen = pick_assets(assets, os_family, arch, variant)
        if chosen:
            return {"tag": rel["tag_name"], "published_at": rel["published_at"], "assets": chosen}
    raise RuntimeError(f"no recent llama.cpp release has a {VARIANT_LABEL.get(variant, variant)} build for "
                       f"{os_family}/{arch}")


def installed():
    s = config.get("llama_cpp")
    p = Path(s.get("path") or "")
    server = p / f"llama-server{EXE}" if p.is_dir() else p
    ok = server.is_file()
    return {"installed": ok, "path": str(server) if ok else "", "dir": str(server.parent) if ok else "",
            "version": s.get("version", ""), "backend": s.get("backend", "")}


def binary(name):
    inst = installed()
    if not inst["installed"]:
        raise RuntimeError("llama.cpp is not installed; install it on the Setup page")
    p = Path(inst["dir"]) / f"{name}{EXE}"
    if not p.exists():
        raise RuntimeError(f"{p.name} is missing from the llama.cpp folder {inst['dir']}")
    return str(p)


def version_of(server_path):
    try:
        p = subprocess.run([server_path, "--version"], capture_output=True, text=True, timeout=30,
                           creationflags=subprocess.CREATE_NO_WINDOW if IS_WIN else 0)
        out = p.stdout + p.stderr
        m = re.search(r"build\s+(\d+)", out) or re.search(r"version:\s*(\d+)\s*\(", out)
        return f"b{m.group(1)}" if m else out.strip().splitlines()[0][:60]
    except (OSError, subprocess.TimeoutExpired, IndexError):
        return ""


def use_existing(path):
    """Point LLMDyno at a llama.cpp folder the user already has."""
    p = Path(path)
    server = p / f"llama-server{EXE}" if p.is_dir() else p
    if not server.is_file():
        raise FileNotFoundError(f"llama-server{EXE} not found in {path}")
    ver = version_of(str(server))
    config.save_settings({"llama_cpp": {"path": str(server.parent), "version": ver, "backend": "existing"}})
    return installed()


def _download(url, dest, ctx, frac0, frac1):
    with httpx.stream("GET", url, follow_redirects=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        done = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                ctx.check()
                f.write(chunk)
                done += len(chunk)
                if total:
                    ctx.progress(frac0 + (frac1 - frac0) * done / total,
                                 f"downloading {dest.name}: {done / 2**20:.0f} / {total / 2**20:.0f} MiB")


def _extract(archive, target):
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            z.extractall(target)
    else:
        with tarfile.open(archive) as t:
            t.extractall(target, filter="data")


def install(ctx):
    variant = ctx.params["variant"]
    ctx.log(f"Looking for the newest llama.cpp release with a {variant} build ...")
    rel = find_release(variant)
    target = config.path("bin_dir") / "llama.cpp" / f"{rel['tag']}-{variant}"
    tmp = target.with_name(target.name + ".partial")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    n = len(rel["assets"])
    for i, a in enumerate(rel["assets"]):
        ctx.log(f"Downloading {a['name']} ({a['size'] / 2**20:.0f} MiB)")
        arch = tmp / a["name"]
        _download(a["browser_download_url"], arch, ctx, 0.05 + 0.8 * i / n, 0.05 + 0.8 * (i + 1) / n)
        ctx.progress(None, f"extracting {a['name']}")
        _extract(arch, tmp)
        arch.unlink()
    servers = list(tmp.rglob(f"llama-server{EXE}"))
    if not servers:
        raise RuntimeError("archive did not contain llama-server")
    bindir = servers[0].parent
    if not IS_WIN:
        for f in bindir.iterdir():
            if f.is_file() and not f.suffix:
                f.chmod(0o755)
    if sysspecs.IS_MAC:
        # Gatekeeper refuses to run quarantined binaries; downloads made by some tools carry the flag
        subprocess.run(["xattr", "-cr", str(tmp)], capture_output=True, timeout=60)
    # the CUDA runtime archive extracts next to the binaries on Windows; on Linux keep libs beside the server
    if bindir != tmp:
        for f in tmp.iterdir():
            if f.is_file():
                shutil.move(str(f), bindir / f.name)
    shutil.rmtree(target, ignore_errors=True)
    tmp.rename(target)
    server = next(target.rglob(f"llama-server{EXE}"))
    ver = version_of(str(server)) or rel["tag"]
    config.save_settings({"llama_cpp": {"path": str(server.parent), "version": ver, "backend": variant}})
    ctx.log(f"Installed llama.cpp {ver} ({variant}) at {server.parent}")
    ctx.result = installed()


# ------------------------------------------------------------------ arguments
def server_args(model_path, p, port, host="127.0.0.1"):
    """llama-server command line for a profile's parameters (see profiles.LOCAL_DEFAULTS)."""
    a = [binary("llama-server"), "-m", str(model_path), "--host", host, "--port", str(port), "--jinja", "--metrics",
         "-c", str(p["ctx"]), "--parallel", str(p.get("parallel", 1)), "--no-mmproj"]
    a += ["-ngl", "all" if p.get("gpu_layers", "all") in ("all", 999, -1) else str(p["gpu_layers"])]
    a += ["--fit", "on" if p.get("auto_fit") else "off"]
    if p.get("n_cpu_moe"):
        a += ["--n-cpu-moe", str(p["n_cpu_moe"])]
    a += ["-fa", p.get("flash_attn", "on"), "-ctk", p.get("cache_k", "f16"), "-ctv", p.get("cache_v", "f16")]
    for flag, key in (("-t", "threads"), ("-b", "batch"), ("-ub", "ubatch")):
        if p.get(key):
            a += [flag, str(p[key])]
    if p.get("mlock"):
        a += ["--mlock"]
    if p.get("no_mmap"):
        a += ["--no-mmap"]
    if p.get("swa_full"):
        a += ["--swa-full"]
    s = p.get("sampling") or {}
    for flag, key in (("--temp", "temperature"), ("--top-p", "top_p"), ("--top-k", "top_k"), ("--min-p", "min_p"),
                      ("--repeat-penalty", "repeat_penalty"), ("--presence-penalty", "presence_penalty")):
        if s.get(key) is not None:
            a += [flag, str(s[key])]
    if p.get("template_kwargs"):
        a += ["--chat-template-kwargs", json.dumps(p["template_kwargs"])]
    if p.get("reasoning_budget") is not None:
        a += ["--reasoning-budget", str(p["reasoning_budget"])]
    a += [str(x) for x in p.get("extra_args", [])]
    return a


FIT_ROW = re.compile(r"\|\s+-\s+(?P<dev>[^|]+?)\s+\|\s+(?P<total>\d+)\s+=\s+(?P<free>\d+)\s+\+\s+\(\s*(?P<self>\d+)\s+=\s+"
                     r"(?P<model>\d+)\s+\+\s+(?P<ctx>\d+)\s+\+\s+(?P<compute>\d+)\)")
HOST_ROW = re.compile(r"\|\s+-\s+Host\s+\|\s+(?P<self>\d+)\s+=\s+(?P<model>\d+)\s+\+\s+(?P<ctx>\d+)\s+\+\s+(?P<compute>\d+)")


def fit_params(model_path, p, margin_mib=1024):
    """Dry-run allocation for the profile's exact arguments. Returns the memory breakdown in MiB:
    the first table is the profile as configured, plus what llama.cpp's auto-fit would change."""
    args = server_args(model_path, p, 0)[1:]
    # keep only arguments llama-fit-params understands (it shares llama's common params)
    drop = {"--host", "--port", "--metrics", "--jinja", "--no-mmproj", "--parallel", "--chat-template-kwargs",
            "--reasoning-budget", "--fit"}
    keep, i = [], 0
    while i < len(args):
        if args[i] in drop:
            i += 1 if args[i] in ("--metrics", "--jinja", "--no-mmproj") else 2
            continue
        keep.append(args[i])
        i += 1
    cmd = [binary("llama-fit-params"), *keep, "-fitt", str(margin_mib), "-lv", "4"]
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=240,
                          creationflags=subprocess.CREATE_NO_WINDOW if IS_WIN else 0)
    text = proc.stdout + "\n" + proc.stderr
    devices, host = [], None
    first = True
    for line in text.splitlines():
        m = FIT_ROW.search(line)
        if m and first:
            devices.append({k: (int(v) if v.isdigit() else v.strip()) for k, v in m.groupdict().items()})
        h = HOST_ROW.search(line)
        if h and first:
            host = {k: int(v) for k, v in h.groupdict().items()}
            first = False   # the first device+host table describes the requested configuration
    fitted = proc.stdout.strip().splitlines()[-1] if proc.stdout.strip() else ""
    ngl = re.search(r"-ngl\s+(\d+)", fitted)
    reduce = re.search(r"need to reduce device memory by (\d+) MiB", text)
    failed = "failed to fit" in text.lower() or proc.returncode != 0
    return {"ok": not failed or bool(devices), "devices": devices, "host": host, "fitted_args": fitted,
            "fitted_ngl": int(ngl.group(1)) if ngl else None, "short_by_mib": int(reduce.group(1)) if reduce else 0,
            "seconds": round(time.time() - t0, 1), "returncode": proc.returncode,
            "log_tail": "\n".join(text.strip().splitlines()[-12:])}


# ------------------------------------------------------------------ server lifecycle
def free_port(port):
    """A llama-server left over from a crash (or a second LLMDyno) still holding our port is killed; anything
    else on the port is an error the user has to resolve, so we never kill a process we did not start."""
    try:
        conns = [c for c in psutil.net_connections("tcp") if c.laddr and c.laddr.port == port and c.status == "LISTEN"]
    except (psutil.AccessDenied, OSError):
        return
    for c in conns:
        try:
            p = psutil.Process(c.pid)
            if "llama-server" in p.name().lower():
                p.kill()
                p.wait(10)
            else:
                raise RuntimeError(f"port {port} is used by {p.name()} (pid {c.pid}); change the llama.cpp port in "
                                   "Settings or close that program")
        except (psutil.NoSuchProcess, psutil.TimeoutExpired):
            continue


class Server:
    """One llama-server process at a time (the GPU is exclusive)."""

    def __init__(self):
        self.proc = None
        self.model_path = None
        self.args = None
        self.log_path = None
        self.port = None
        self._logf = None
        self.lock = threading.Lock()

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self, model_path, params, log_path, host="127.0.0.1", timeout=900, ctx=None):
        self.stop()
        port = int(config.get("llama_port"))
        free_port(port)
        args = server_args(model_path, params, port, host)
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._logf = open(log_path, "a", encoding="utf-8", errors="replace")
        self._logf.write(f"\n==== {time.ctime()} {' '.join(args)}\n")
        self._logf.flush()
        self.proc = subprocess.Popen(args, stdout=self._logf, stderr=subprocess.STDOUT,
                                     creationflags=subprocess.CREATE_NO_WINDOW if IS_WIN else 0)
        self.model_path, self.args, self.log_path, self.port = str(model_path), args, log_path, port
        t0 = time.time()
        while time.time() - t0 < timeout:
            if ctx:
                ctx.check()
            if self.proc.poll() is not None:
                tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]
                raise RuntimeError("llama-server exited during load:\n" + "\n".join(tail))
            try:
                if httpx.get(f"http://127.0.0.1:{port}/health", timeout=3).json().get("status") == "ok":
                    return round(time.time() - t0, 1)
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(1.5)
        self.stop()
        raise TimeoutError(f"llama-server did not become ready within {timeout}s")

    def stop(self, force=False):
        """force=True kills at once (panic stop); otherwise llama-server gets 30 s to exit cleanly."""
        with self.lock:
            proc, self.proc = self.proc, None
            logf, self._logf = self._logf, None
        if proc and proc.poll() is None:
            if force:
                proc.kill()
            else:
                proc.terminate()
            try:
                proc.wait(5 if force else 30)
            except subprocess.TimeoutExpired:
                proc.kill()
        if logf:
            logf.close()

    def props(self):
        return httpx.get(f"http://127.0.0.1:{self.port}/props", timeout=10).json()

    def load_report(self):
        """What llama-server actually did: offloaded layers, buffer sizes, fit adjustments."""
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace")
        except (OSError, AttributeError):
            return {}
        text = text[text.rfind("==== "):]
        rep = {}
        m = re.search(r"offloaded (\d+)/(\d+) layers to GPU", text)
        if m:
            rep["offloaded_layers"], rep["total_layers"] = int(m.group(1)), int(m.group(2))
        for kind, pat in (("model", r"(\w+)\s+model buffer size\s*=\s*([\d.]+) MiB"),
                          ("kv", r"(\w+)\s+KV buffer size\s*=\s*([\d.]+) MiB"),
                          ("compute", r"(\w+)\s+compute buffer size\s*=\s*([\d.]+) MiB")):
            for dev, mib in re.findall(pat, text):
                rep.setdefault("buffers", {}).setdefault(dev, {}).setdefault(kind, 0.0)
                rep["buffers"][dev][kind] += float(mib)
        fit = re.findall(r"common_params_fit_impl: (.+)", text)
        if fit:
            rep["fit_notes"] = fit[-6:]
        m = re.search(r"n_ctx(?:_seq)?\s*=\s*(\d+)", text)
        if m:
            rep["n_ctx"] = int(m.group(1))
        return rep


server = Server()
