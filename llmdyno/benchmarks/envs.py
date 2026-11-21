"""Benchmarks that run in their own Docker image instead of the LLMDyno sandbox.

A benchmark opts in with an "env" block in benchmark.json:

    "env": {"type": "swebench", "image": "swebench/sweb.eval.x86_64.django_1776_django-11099:latest",
            "platform": "linux/amd64", "workspace": "volume", "repo_dir": "/testbed", "base_commit": "..."}

workspace "volume": the repository inside the image is copied into a per-run Docker volume, mounted at repo_dir and
at /workspace, so the agent edits the real checkout (editable installs and conda paths keep working) and nothing
crosses the slow Windows/macOS file sharing. workspace "bind" (the default): the usual run folder is bind-mounted at
/workspace, as for built-in benchmarks."""
import re
import subprocess

from ..harnesses import catalog, runtime
from ..system import specs as sysspecs

NOWIN = subprocess.CREATE_NO_WINDOW if sysspecs.IS_WIN else 0
PATCH_EXCLUDES = [":(exclude)*.pyc", ":(exclude)**/__pycache__/**", ":(exclude).pytest_cache/**",
                  ":(exclude)*.egg-info/**", ":(exclude).tox/**", ":(exclude)node_modules/**"]


def sh(args, timeout=600, **kw):
    return subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          creationflags=NOWIN, **kw)


def image_platform(image):
    """SWE-bench images name their architecture; everything else follows the host."""
    if ".x86_64." in image or image.endswith("-amd64"):
        return "linux/amd64"
    if ".arm64." in image or image.endswith("-arm64"):
        return "linux/arm64"
    return runtime.host_platform()


def spec(bench):
    e = bench.get("env") or {}
    if not e.get("image"):
        return None
    return {"type": e.get("type", "image"), "image": e["image"], "platform": e.get("platform") or image_platform(e["image"]),
            "workspace": e.get("workspace", "bind"), "repo_dir": e.get("repo_dir") or catalog.WORKSPACE,
            "base_commit": e.get("base_commit"), "emulated": (e.get("platform") or image_platform(e["image"]))
            != runtime.host_platform()}


def image_present(image):
    try:
        return sh(["docker", "image", "inspect", "--format", "{{.Id}}", image], timeout=60).returncode == 0
    except (OSError, subprocess.TimeoutExpired):     # Docker not installed: nothing is present
        return False


def ensure_image(image, platform, log=print, cancel=None):
    """Pull the environment image for the given platform (SWE-bench images are 1-5 GB)."""
    if image_present(image):
        return
    if image.startswith("llmdyno-"):
        raise RuntimeError(f"{image} is not built: build it on the Setup page")
    log(f"pulling {image} ({platform})")
    proc = subprocess.Popen(["docker", "pull", "--platform", platform, image], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", creationflags=NOWIN)
    last = ""
    for line in proc.stdout:
        last = line.strip() or last
        if cancel is not None and cancel.is_set():
            proc.kill()
            raise RuntimeError("cancelled while pulling the environment image")
        if "Pull complete" in line or "Digest:" in line or "Status:" in line:
            log("  " + line.strip())
    if proc.wait() != 0:
        raise RuntimeError(f"docker pull {image} failed: {last[-300:]}")


def ws_volume(run_id):
    return "dyno-ws-" + re.sub(r"[^a-z0-9_-]", "", run_id.lower())[-24:]


def prepare(env, run_id, log=print, cancel=None):
    """Pull the image and, for volume workspaces, copy the repository into a fresh volume. Records the repository's
    HEAD as env["start_commit"]: SWE-bench images add their own commit on top of the task's base commit, and the
    harness applies patches to that state, so the agent's diff must be taken against it."""
    ensure_image(env["image"], env["platform"], log, cancel)
    if env["workspace"] != "volume":
        return
    vol = ws_volume(run_id)
    sh(["docker", "volume", "rm", "-f", vol], timeout=120)
    r = sh(["docker", "volume", "create", "--label", "org.llmdyno.role=workspace", vol], timeout=120)
    if r.returncode != 0:
        raise RuntimeError(f"could not create the workspace volume: {r.stderr.strip()[-300:]}")
    r = sh(["docker", "run", "--rm", "--platform", env["platform"], "--network", "none", "-v", f"{vol}:/dst",
            env["image"], "sh", "-c", f"cp -a {env['repo_dir']}/. /dst/ && "
            f"(git -c safe.directory='*' -C {env['repo_dir']} rev-parse HEAD 2>/dev/null || true)"], timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(f"could not copy {env['repo_dir']} out of {env['image']}: {(r.stderr or r.stdout)[-400:]}")
    head = (r.stdout.strip().splitlines() or [""])[-1].strip()
    if re.fullmatch(r"[0-9a-f]{40}", head):
        env["start_commit"] = head


def workspace_mounts(env, run_id, host_workspace):
    if env["workspace"] == "volume":
        vol = ws_volume(run_id)
        mounts = ["-v", f"{vol}:{env['repo_dir']}"]
        if env["repo_dir"] != catalog.WORKSPACE:
            mounts += ["-v", f"{vol}:{catalog.WORKSPACE}"]
        return mounts
    return ["-v", f"{host_workspace}:{catalog.WORKSPACE}"]


def extract_patch(env, run_id):
    """The agent's changes as a git diff against the repository state it started from (SWE-bench prediction
    format). That is the image's HEAD, recorded by prepare(); the task's base commit is only a fallback."""
    base = env.get("start_commit") or env.get("base_commit") or "HEAD"
    if not re.fullmatch(r"[0-9a-fA-F]{7,40}|HEAD", base):
        raise ValueError("invalid base commit")
    excludes = " ".join(f"'{x}'" for x in PATCH_EXCLUDES)
    script = (f"cd {env['repo_dir']} && git config --global --add safe.directory '*' && "
              f"git -c core.fileMode=false add -A -- . {excludes} >/dev/null 2>&1; "
              f"git -c core.fileMode=false diff --cached --binary --no-color --no-ext-diff {base} -- . {excludes}")
    r = sh(["docker", "run", "--rm", "--platform", env["platform"], "--network", "none",
            *workspace_mounts(env, run_id, None)[:2], env["image"], "bash", "-c", script], timeout=600)
    if r.returncode != 0:
        raise RuntimeError(f"git diff failed: {(r.stderr or r.stdout)[-400:]}")
    return r.stdout


def give_back(env, run_dir):
    """Linux only: environment images run as root, so hand the run's bind-mounted folders back to the user
    (Docker Desktop on Windows and macOS maps ownership itself)."""
    import os
    if not (env and sysspecs.IS_LINUX and hasattr(os, "getuid")):
        return
    mounts = []
    for sub in ("home", "workspace"):
        mounts += ["-v", f"{str(run_dir / sub)}:/fix/{sub}"]
    sh(["docker", "run", "--rm", "--platform", env["platform"], "--network", "none", *mounts, env["image"],
        "chown", "-R", f"{os.getuid()}:{os.getgid()}", "/fix"], timeout=300)


def cleanup(env, run_id):
    if env and env["workspace"] == "volume":
        sh(["docker", "volume", "rm", "-f", ws_volume(run_id)], timeout=120)


def patched_files(patch):
    return sorted(set(re.findall(r"^diff --git a/(\S+) b/", patch or "", flags=re.M)))
