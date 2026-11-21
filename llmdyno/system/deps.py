"""Dependencies the setup wizard checks and, where it safely can, installs."""
import os
import shutil
import subprocess
import time
from pathlib import Path

from .. import config, secrets
from ..harnesses import catalog, images
from ..inference import llamacpp
from . import specs as sysspecs

IS_WIN = os.name == "nt"
IS_MAC = sysspecs.IS_MAC
DOCKER_DESKTOP = (Path("/Applications/Docker.app") if IS_MAC else
                  Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "Docker Desktop.exe")
# folders where Docker Desktop keeps only runtime sockets (recreated on every start)
DOCKER_SOCKET_DIRS = [Path(os.environ.get("LOCALAPPDATA", "")) / "Docker" / "run",
                      Path(os.environ.get("LOCALAPPDATA", "")) / "docker-secrets-engine"]
DOCKER_MEMORY_HELP = ("https://docs.docker.com/desktop/settings-and-maintenance/settings/#resources" if IS_MAC else
                      "https://learn.microsoft.com/windows/wsl/wsl-config#wslconfig")


def _dep(id_, name, level, ok, detail, actions=None, why="", group="core"):
    return {"id": id_, "name": name, "level": level, "status": "ok" if ok else ("missing" if ok is False else "unknown"),
            "ok": bool(ok), "detail": detail, "actions": actions or [], "why": why, "group": group}


def check(force=False):
    s = sysspecs.detect(force=force)
    d = s["docker"]
    out = []
    if d.get("installed"):
        acts = []
        stale = [] if d.get("running") else stale_docker_sockets()
        if stale:
            acts.append({"id": "repair_docker", "label": "Fix Docker Desktop start-up", "kind": "run",
                         "confirm": "Docker Desktop left socket files behind after a crash and now stops at start-up "
                                    "(\"The file cannot be accessed by the system\"). This quits Docker Desktop, moves "
                                    "the folders holding them aside (they only hold sockets, recreated on every start) "
                                    "and starts Docker again. Images, containers and volumes are not touched."})
        if not d.get("running") and (IS_WIN or IS_MAC) and DOCKER_DESKTOP.exists():
            acts.append({"id": "start_docker", "label": "Start Docker Desktop", "kind": "run"})
        detail = (f"Docker {d.get('server_version') or d.get('client_version')} · {d.get('engine_os', '')}".strip(" ·")
                  if d.get("running") else f"Installed but not running: {d.get('error') or 'daemon unreachable'}")
        if stale:
            detail = ("Docker Desktop cannot start: socket files left by a crash block it "
                      f"({', '.join(stale)}). Use Fix Docker Desktop start-up, and avoid 'Reset to factory defaults', "
                      "which deletes your images.")
        out.append(_dep("docker", "Docker", "required", d.get("running"), detail, acts,
                        "Agents and graders run in offline Docker sandboxes."))
    else:
        if IS_WIN:
            acts = [{"id": "install_docker", "label": "Install Docker Desktop (winget)", "kind": "job",
                     "note": "Runs: winget install -e --id Docker.DockerDesktop. Windows asks for administrator approval, "
                             "and you accept Docker's subscription terms by installing it."}]
        elif IS_MAC:
            acts = [{"id": "copy", "label": "Copy Homebrew command", "kind": "copy", "text": "brew install --cask docker"}]
        else:
            acts = [{"id": "copy", "label": "Copy install command", "kind": "copy",
                     "text": "curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER"}]
        acts.append({"id": "link", "label": "Docker download page", "kind": "link", "url": "https://docs.docker.com/get-docker/"})
        out.append(_dep("docker", "Docker", "required", False, "Not installed", acts,
                        "Agents and graders run in offline Docker sandboxes."))
    if d.get("running") and d.get("mem_total_bytes"):
        gb = d["mem_total_bytes"] / 2**30
        out.append(_dep("docker_memory", "Docker memory", "recommended", gb >= 8, f"{gb:.0f} GB available to containers",
                        [{"id": "link", "label": "How to raise the Docker Desktop limit" if IS_MAC else
                          "How to raise the WSL 2 limit", "kind": "link", "url": DOCKER_MEMORY_HELP}]
                        if (IS_WIN or IS_MAC) and gb < 8 else [],
                        "Agent sandboxes get up to 12 GB and graders 8 GB; below 8 GB large tasks can be killed."))
    if d.get("running") and d.get("arch") == "arm64":
        out.append(_dep("docker_arch", "Docker on ARM64", "optional", True,
                        f"Native {d.get('os_arch')} images. SWE-bench task images are x86-64 only and run under emulation.",
                        [{"id": "link", "label": "Rosetta emulation in Docker Desktop", "kind": "link",
                          "url": "https://docs.docker.com/desktop/settings-and-maintenance/settings/#general"}] if IS_MAC else
                        [{"id": "copy", "label": "Copy QEMU setup command", "kind": "copy",
                          "text": "docker run --privileged --rm tonistiigi/binfmt --install amd64"}],
                        "The sandbox and harness images build natively for ARM64. Turn on x86-64 emulation (Rosetta on "
                        "Apple Silicon, QEMU binfmt on Linux) only if you plan to run SWE-bench tasks."))
    g = sysspecs.primary_gpu(s)
    if g and g.get("vendor") == "Apple":
        lim = g.get("vram_total_mib") or 0
        ram = g.get("ram_total_mib") or 0
        suggest = sysspecs.apple.suggested_wired_limit_mib(ram, lim)
        out.append(_dep("gpu_memory_limit", "GPU memory limit", "optional", True,
                        f"Metal can use {lim / 1024:.0f} of {ram / 1024:.0f} GB unified memory"
                        + (" (raised with iogpu.wired_limit_mb)" if g.get("wired_limit_set") else " (macOS default)"),
                        [{"id": "copy", "label": "Copy command to raise it", "kind": "copy",
                          "text": f"sudo sysctl iogpu.wired_limit_mb={suggest}"}] if suggest else [],
                        "macOS reserves part of unified memory for the system. Raising the limit lets larger models stay on "
                        "the GPU; it resets on reboot. Leave at least 8 GB for macOS and Docker.", group="local"))
    if g and g["vendor"] == "NVIDIA":
        try:
            major = int(str(g.get("driver", "0")).split(".")[0])
        except ValueError:
            major = 0
        out.append(_dep("gpu_driver", "NVIDIA driver", "recommended", major >= 580,
                        f"Driver {g.get('driver')} (CUDA {s.get('cuda_version') or '?'})" + ("" if major >= 580 else
                                                                                           ": the CUDA 12.4 build will be used"),
                        [{"id": "link", "label": "NVIDIA drivers", "kind": "link", "url": "https://www.nvidia.com/drivers"}],
                        "Driver 580+ runs the CUDA 13 build of llama.cpp, which is the fastest on RTX 50-series GPUs.",
                        group="local"))
    inst = llamacpp.installed()
    variants = llamacpp.variants(s)
    out.append(_dep("llama_cpp", "llama.cpp", "required for local models", inst["installed"],
                    f"{inst['version']} ({inst['backend']}) at {inst['dir']}" if inst["installed"] else "Not installed",
                    [{"id": "install_llama", "label": "Download and install", "kind": "job", "variants": variants},
                     {"id": "use_existing_llama", "label": "Use an existing folder", "kind": "path"}],
                    "Runs local GGUF models (llama-server) and measures memory with llama-fit-params.", group="local"))
    sb = images.image_exists(images.SANDBOX)
    out.append(_dep("sandbox_image", "Sandbox image", "required", bool(sb),
                    f"{images.SANDBOX} · {sb['size_bytes'] / 2**30:.1f} GB" if sb else "Not built (about 1.6 GB, 3-6 minutes)",
                    [{"id": "build_sandbox", "label": "Build image", "kind": "job"}] if d.get("running") else [],
                    "Python 3.12, Node 24 and every package the built-in benchmarks need, preinstalled for offline use."))
    q = images.image_exists(images.QUALITY)
    out.append(_dep("quality_image", "Code-quality image", "recommended", bool(q),
                    f"{images.QUALITY} · {q['size_bytes'] / 2**30:.1f} GB" if q else "Not built (adds about 0.2 GB)",
                    [{"id": "build_quality", "label": "Build image", "kind": "job"}] if d.get("running") else [],
                    "Static analysis (ruff, radon, bandit, vulture, coverage) for code-quality scores."))
    ready = [h for h in catalog.BUILTIN if images.image_exists(h.image())]
    out.append(_dep("harness_images", "Agent harnesses", "required", bool(ready),
                    f"{len(ready)} of {len(catalog.BUILTIN)} built: {', '.join(h.name for h in ready)}" if ready
                    else "None built yet: Pi is a good first choice",
                    [{"id": "build_harness_pi", "label": "Build Pi", "kind": "job"},
                     {"id": "open_harnesses", "label": "Choose harnesses", "kind": "nav", "to": "/harnesses"}]
                    if d.get("running") else [], "Each harness is its own image built on the sandbox."))
    models_dir = Path(config.get("models_dir"))
    probe = models_dir
    while not probe.exists() and probe.parent != probe:
        probe = probe.parent
    free = shutil.disk_usage(probe).free if probe.exists() else 0
    out.append(_dep("disk", "Disk space for models", "recommended", free >= 30 * 2**30,
                    f"{free / 2**30:.0f} GB free at {models_dir}",
                    [{"id": "open_settings", "label": "Change folders", "kind": "nav", "to": "/settings"}],
                    "Quantized models are 4-30 GB each; keep at least 30 GB free.", group="local"))
    out += external_deps(d)
    has_hf = secrets.has("hf_token")
    out.append(_dep("hf_token", "Hugging Face token", "optional", has_hf,
                    "Set" if has_hf else "Not set (only needed for gated models)",
                    [{"id": "open_settings", "label": "Change token" if has_hf else "Add token", "kind": "nav", "to": "/settings"}],
                    "Gated repositories (for example some Llama and Gemma releases) need a token.", group="local"))
    return out


def external_deps(d):
    """SWE-bench and Aider polyglot: only needed once their tasks are imported (Benchmarks > Import)."""
    from ..benchmarks import polyglot, swebench
    out = []
    sw = swebench.harness_status()
    want = (config.get("swebench") or {}).get("harness_version")
    out.append(_dep("swebench_harness", "SWE-bench harness", "for SWE-bench tasks", sw["installed"],
                    f"swebench {sw['version']} in its own venv" + ("" if sw["version"] == want else f" (LLMDyno expects {want})")
                    if sw["installed"] else f"Not installed (swebench {want} from PyPI, about 250 MB, in an isolated venv)",
                    [{"id": "install_swebench", "label": "Reinstall" if sw["installed"] else "Install", "kind": "job"},
                     {"id": "open_import", "label": "Import tasks", "kind": "nav", "to": "/benchmarks?import=swebench"}],
                    "SWE-bench tasks are graded by the official harness, exactly as on the public leaderboard.",
                    group="benchmarks"))
    img = images.image_exists(polyglot.IMAGE)
    ready = polyglot.context_ready()
    out.append(_dep("polyglot_image", "Polyglot toolchains", "for Aider polyglot tasks", bool(img),
                    f"{polyglot.IMAGE} · {img['size_bytes'] / 2**30:.1f} GB" if img else
                    ("Not built (about 4 GB: Go, Rust, JDK 21 + Gradle, CMake, jest)" if ready else
                     "Import the polyglot benchmark first; the image is built from its exercises"),
                    ([{"id": "build_polyglot", "label": "Build image", "kind": "job"}] if ready and d.get("running") else [])
                    + [{"id": "open_import", "label": "Import tasks", "kind": "nav", "to": "/benchmarks?import=polyglot"}],
                    "C++, Go, Java, JavaScript and Rust exercises need their compilers and test runners offline.",
                    group="benchmarks"))
    return out


def _stale_in(folder):
    out = []
    try:
        entries = list(folder.iterdir())
    except OSError:
        return out
    for f in entries:
        try:
            os.stat(f)
        except OSError as e:
            if getattr(e, "winerror", None) == 1920:
                out.append(f.name)
    return out


def stale_docker_sockets():
    """Windows only: AF_UNIX socket files that Docker Desktop left behind after a crash (in %LOCALAPPDATA%\\Docker\\run
    and %LOCALAPPDATA%\\docker-secrets-engine). Windows cannot open or delete them (error 1920), so Docker Desktop
    fails on its next start while trying to remove them. Only meaningful while Docker is not running."""
    if not IS_WIN:
        return []
    return [f"{d.name}\\{n}" for d in DOCKER_SOCKET_DIRS if d.is_dir() for n in _stale_in(d)]


def repair_docker_start():
    """Quit Docker Desktop, move its runtime socket folder aside (it is recreated on start) and start it again."""
    if not IS_WIN:
        raise RuntimeError("this repair is only needed on Windows")
    for exe in ("Docker Desktop.exe", "com.docker.backend.exe", "com.docker.build.exe"):
        subprocess.run(["taskkill", "/F", "/IM", exe], capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    time.sleep(3)
    moved = []
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for d in DOCKER_SOCKET_DIRS:
        if d.is_dir() and _stale_in(d):
            dest = d.with_name(f"{d.name}.stale-{stamp}")
            d.rename(dest)
            moved.append(str(dest))
    start_docker_desktop()
    return moved


def start_docker_desktop():
    if not ((IS_WIN or IS_MAC) and DOCKER_DESKTOP.exists()):
        raise RuntimeError("Docker Desktop was not found")
    if IS_MAC:
        subprocess.Popen(["open", "-a", "Docker"])
    else:
        subprocess.Popen([str(DOCKER_DESKTOP)], creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW)


def install_docker(ctx):
    if not IS_WIN:
        raise RuntimeError("automatic Docker installation is only offered on Windows; use the copied command")
    if not shutil.which("winget"):
        raise RuntimeError("winget is not available; install Docker Desktop from docs.docker.com")
    cmd = ["winget", "install", "-e", "--id", "Docker.DockerDesktop", "--accept-package-agreements",
           "--accept-source-agreements"]
    ctx.log("$ " + " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    for line in proc.stdout:
        ctx.log(line.rstrip())
        ctx.check()
    if proc.wait() != 0:
        raise RuntimeError(f"winget exited with {proc.returncode}")
    ctx.log("Docker Desktop installed. Start it once, finish its first-run setup, then re-check.")
