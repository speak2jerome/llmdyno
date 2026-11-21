"""System: dependency checks and setup, specs, GPU, jobs, cleanup and the panic stop."""
from __future__ import annotations

from typing import Sequence, Union

from ..errors import LLMDynoError
from ._core import Job, _say, call, covers

__all__ = ["Doctor", "doctor", "setup", "specs", "gpu_usage", "active_work", "panic", "cleanup", "list_jobs",
           "clear_jobs", "start_docker", "repair_docker", "install_docker", "use_llama_cpp"]



class Doctor(list):
    """The Setup page's checks as a list of dicts; prints as a table. `ok` is True when nothing required is missing."""

    @property
    def ok(self) -> bool:
        return all(d["ok"] for d in self if d["level"] == "required")

    @property
    def missing(self) -> list:
        return [d for d in self if not d["ok"]]

    def __str__(self):
        lines = []
        for d in self:
            mark = "ok " if d["ok"] else ("!! " if d["level"] == "required" else "-- ")
            lines.append(f"{mark}{d['name']:<24} {d['level']:<26} {d['detail']}")
        return "\n".join(lines)

    def __repr__(self):
        return f"<llmdyno.Doctor ok={self.ok} missing={[d['id'] for d in self.missing]}>"


@covers("GET /api/system/deps")
def doctor() -> Doctor:
    """System and dependency checks (Docker, images, llama.cpp, harnesses, SWE-bench harness, …)."""
    return Doctor(call("system.get_deps", refresh=True))


@covers("POST /api/system/deps/{dep_id}/action")
def setup(harnesses: Union[str, Sequence[str]] = ("pi",), *, quality: bool = True,
          llama_cpp: Union[bool, str] = True, swebench: bool = False, polyglot: bool = False,
          quiet: bool = False, verbose: bool = False) -> Doctor:
    """Install what benchmarks need, skipping what is already there: the sandbox image, the code-quality image,
    harness images, a llama.cpp build for this machine (True picks the best one; or pass a variant such as "cuda-13",
    "metal", "vulkan", "cpu"), and optionally the SWE-bench harness and the polyglot toolchain image.
    These download several GB the first time. Docker must be running."""
    deps = {d["id"]: d for d in call("system.get_deps", refresh=True)}
    if not deps.get("docker", {}).get("ok"):
        raise LLMDynoError("Docker is not running: start Docker Desktop (or the docker service) and try again")
    todo = []

    def dep(dep_id, action, **extra):
        return lambda: call("system.dep_action", dep_id=dep_id, body={"action": action, **extra})

    if not deps["sandbox_image"]["ok"]:
        todo.append(("Sandbox image", dep("sandbox_image", "build_sandbox")))
    if quality and not deps["quality_image"]["ok"]:
        todo.append(("Code-quality image", dep("quality_image", "build_quality")))
    wanted = [harnesses] if isinstance(harnesses, str) else list(harnesses or [])
    if wanted:
        known = {h["id"]: h for h in call("harnesses.list_harnesses")}
        for hid in wanted:
            h = known.get(hid)
            if h is None:
                raise LLMDynoError(f"unknown harness {hid!r}; one of: {', '.join(known)}")
            if h.get("status") != "ready":
                todo.append((f"{h['name']} harness", lambda hid=hid: call("harnesses.build_harness", hid=hid)))
    if llama_cpp and not deps["llama_cpp"]["ok"]:
        if isinstance(llama_cpp, str):
            variant = llama_cpp
        else:
            action = next((a for a in deps["llama_cpp"].get("actions") or [] if a["id"] == "install_llama"), {})
            variant = next((v["id"] for v in action.get("variants") or [] if v.get("ok")), "cpu")
        todo.append((f"llama.cpp ({variant})", dep("llama_cpp", "install_llama", variant=variant)))
    if swebench and not deps["swebench_harness"]["ok"]:
        todo.append(("SWE-bench harness", lambda: call("imports.install_swebench_harness")))
    if polyglot and not deps["polyglot_image"]["ok"]:
        if not call("imports.import_catalog")["polyglot"].get("context_ready"):
            todo.append(("Aider polyglot exercises", lambda: call("imports.import_polyglot", body={})))
        todo.append(("Polyglot toolchain image", lambda: call("imports.build_polyglot_image")))
    for label, start in todo:
        _say(quiet, f"Setting up: {label}")
        Job(start()["job_id"]).wait(quiet=quiet, verbose=verbose)
    if not todo:
        _say(quiet, "Everything requested is already set up.")
    return doctor()


# ------------------------------------------------------------------ machine
@covers("GET /api/system/specs")
def specs(refresh: bool = False) -> dict:
    """This machine: CPU and instruction sets, RAM, GPUs with VRAM and driver, disk, OS and Docker (what the
    Overview page shows). refresh=True detects again instead of using the cached result."""
    return call("system.get_specs", refresh=refresh)


@covers("GET /api/system/gpu")
def gpu_usage() -> list:
    """Live GPU readings: utilisation, VRAM used and free, temperature and power for each GPU."""
    return call("system.system_gpu")


# ------------------------------------------------------------------ stopping things
@covers("GET /api/system/active")
def active_work() -> dict:
    """What panic() would stop right now: running jobs, plans, containers and the llama-server."""
    return call("system.system_active")


@covers("POST /api/system/panic")
def panic() -> dict:
    """Stop everything at once (the red button): cancels every job and plan, kills LLMDyno's containers and the
    llama-server. Finished runs are kept. Returns what was stopped."""
    return call("system.system_panic")


@covers("POST /api/system/cleanup")
def cleanup() -> int:
    """Remove sandbox containers left behind by crashed or interrupted runs; returns how many were removed."""
    return call("system.cleanup_containers")["removed"]


# ------------------------------------------------------------------ background jobs
@covers("GET /api/jobs")
def list_jobs(active: bool = False, kind: str | None = None, limit: int = 100) -> list:
    """Background jobs, newest first (downloads, builds, plans, reviews, imports). active=True keeps the queued and
    running ones; kind filters by type ("download", "build", "plan", "judge", "import", "install", …)."""
    return [Job(d) for d in call("system.list_jobs", active=active, limit=limit, kind=kind)]


@covers("DELETE /api/jobs")
def clear_jobs() -> int:
    """Forget finished jobs (done, failed, cancelled, interrupted); returns how many were removed."""
    return call("system.clear_jobs")["removed"]


# ------------------------------------------------------------------ Docker and llama.cpp
def _dep(dep_id: str, action: str, **extra) -> dict:
    return call("system.dep_action", dep_id=dep_id, body={"action": action, **extra})


@covers("POST /api/system/deps/{dep_id}/action")
def start_docker() -> str:
    """Start Docker Desktop (Windows and macOS); it takes about a minute to come up."""
    return _dep("docker", "start_docker")["message"]


@covers("POST /api/system/deps/{dep_id}/action")
def repair_docker() -> str:
    """Restart Docker Desktop after moving aside stale sockets that keep it from starting (a known Windows issue)."""
    return _dep("docker", "repair_docker")["message"]


@covers("POST /api/system/deps/{dep_id}/action")
def install_docker(quiet: bool = False) -> dict:
    """Download and run the Docker Desktop installer (Windows and macOS; Linux uses the distribution's packages)."""
    return Job(_dep("docker", "install_docker")["job_id"]).wait(quiet=quiet)


@covers("POST /api/system/deps/{dep_id}/action")
def use_llama_cpp(path: str) -> dict:
    """Use a llama.cpp build you already have (the folder holding llama-server) instead of installing one."""
    return _dep("llama_cpp", "use_existing_llama", path=str(path))["llama_cpp"]
