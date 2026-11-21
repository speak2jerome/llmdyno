"""System: dependency checks and setup, specs, GPU, jobs, cleanup and the panic stop."""
from __future__ import annotations

from typing import Sequence, Union

from ..errors import LLMDynoError
from ._core import Job, _say, call, covers

__all__ = ["Doctor", "doctor", "setup"]

# Web API routes this module does not cover yet (see sdk/parity.py); remove each one as it gets a library call.
PENDING_ROUTES = (
    "DELETE /api/jobs",
    "GET /api/jobs",
    "GET /api/system/active",
    "POST /api/system/cleanup",
    "GET /api/system/gpu",
    "POST /api/system/panic",
    "GET /api/system/specs",
)


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
