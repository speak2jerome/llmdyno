"""Dependencies the setup wizard checks and, where it safely can, installs."""
import os
import shutil
import subprocess
from pathlib import Path

from .. import config, secrets
from ..harnesses import catalog, images
from ..inference import llamacpp
from . import specs as sysspecs

IS_WIN = os.name == "nt"
DOCKER_DESKTOP = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "Docker Desktop.exe"


def _dep(id_, name, level, ok, detail, actions=None, why="", group="core"):
    return {"id": id_, "name": name, "level": level, "status": "ok" if ok else ("missing" if ok is False else "unknown"),
            "ok": bool(ok), "detail": detail, "actions": actions or [], "why": why, "group": group}


def check(force=False):
    s = sysspecs.detect(force=force)
    d = s["docker"]
    out = []
    if d.get("installed"):
        acts = []
        if not d.get("running") and IS_WIN and DOCKER_DESKTOP.exists():
            acts.append({"id": "start_docker", "label": "Start Docker Desktop", "kind": "run"})
        out.append(_dep("docker", "Docker", "required", d.get("running"),
                        f"Docker {d.get('server_version') or d.get('client_version')} · {d.get('engine_os', '')}".strip(" ·")
                        if d.get("running") else f"Installed but not running: {d.get('error') or 'daemon unreachable'}",
                        acts, "Agents and graders run in offline Docker sandboxes."))
    else:
        acts = ([{"id": "install_docker", "label": "Install Docker Desktop (winget)", "kind": "job",
                  "note": "Runs: winget install -e --id Docker.DockerDesktop. Windows asks for administrator approval, "
                          "and you accept Docker's subscription terms by installing it."}] if IS_WIN else
                [{"id": "copy", "label": "Copy install command", "kind": "copy",
                  "text": "curl -fsSL https://get.docker.com | sudo sh && sudo usermod -aG docker $USER"}])
        acts.append({"id": "link", "label": "Docker download page", "kind": "link", "url": "https://docs.docker.com/get-docker/"})
        out.append(_dep("docker", "Docker", "required", False, "Not installed", acts,
                        "Agents and graders run in offline Docker sandboxes."))
    if d.get("running") and d.get("mem_total_bytes"):
        gb = d["mem_total_bytes"] / 2**30
        out.append(_dep("docker_memory", "Docker memory", "recommended", gb >= 8, f"{gb:.0f} GB available to containers",
                        [{"id": "link", "label": "How to raise the WSL 2 limit", "kind": "link",
                          "url": "https://learn.microsoft.com/windows/wsl/wsl-config#wslconfig"}] if IS_WIN and gb < 8 else [],
                        "Agent sandboxes get up to 12 GB and graders 8 GB; below 8 GB large tasks can be killed."))
    g = sysspecs.primary_gpu(s)
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
    has_hf = secrets.has("hf_token")
    out.append(_dep("hf_token", "Hugging Face token", "optional", has_hf,
                    "Set" if has_hf else "Not set (only needed for gated models)",
                    [{"id": "open_settings", "label": "Change token" if has_hf else "Add token", "kind": "nav", "to": "/settings"}],
                    "Gated repositories (for example some Llama and Gemma releases) need a token.", group="local"))
    return out


def start_docker_desktop():
    if not (IS_WIN and DOCKER_DESKTOP.exists()):
        raise RuntimeError("Docker Desktop was not found")
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
