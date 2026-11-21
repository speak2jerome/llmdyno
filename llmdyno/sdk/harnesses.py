"""Agent harnesses: built-in and custom, images, Dockerfiles, previews and portable runtimes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Union

from ..errors import LLMDynoError, NotFoundError
from ._core import Handle, Job, call, covers

__all__ = ["Harness", "list_harnesses", "harness", "add_harness", "harness_schema"]


class Harness(Handle):
    """A coding-agent harness (Pi, OpenCode, Codex CLI, Qwen Code, Crush, Aider, mini-SWE-agent, or your own) and the
    Docker image it runs in."""

    @property
    def name(self) -> str:
        return self._data["name"]

    @property
    def status(self) -> str:
        """ready (image built), building, failed or missing (fetched fresh)."""
        return self.refresh()._d["status"]

    @property
    def builtin(self) -> bool:
        return bool(self._data.get("builtin", True))

    @property
    def apis(self) -> list:
        """API styles it can talk: openai-chat, openai-responses, anthropic."""
        return list(self._data.get("apis") or [])

    def refresh(self) -> "Harness":
        hit = [h for h in call("harnesses.list_harnesses") if h["id"] == self.id]
        if not hit:
            raise NotFoundError(f"no harness {self.id}")
        self._d = hit[0]
        return self

    @covers("POST /api/harnesses/{hid}/build")
    def build(self, wait: bool = True, quiet: bool = False) -> Union["Harness", Job]:
        """Build (or rebuild) its image on top of the sandbox image, then smoke-test it. wait=False returns the Job."""
        job = Job(call("harnesses.build_harness", hid=self.id)["job_id"])
        if not wait:
            return job
        job.wait(quiet=quiet)
        return self.refresh()

    @covers("DELETE /api/harnesses/{hid}/image")
    def remove_image(self) -> None:
        """Delete its Docker image (build() makes it again)."""
        call("harnesses.remove_harness_image", hid=self.id)

    @covers("GET /api/harnesses/{hid}/dockerfile")
    def dockerfile(self) -> str:
        """The Dockerfile its image is built from."""
        return call("harnesses.harness_dockerfile", hid=self.id)

    @covers("GET /api/harnesses/{hid}/preview")
    def preview(self, api_style: str = "openai-chat") -> dict:
        """Exactly what a run would execute, for a sample endpoint: config files written into the agent's HOME,
        environment, the first command and the command that continues a multi-stage task."""
        return call("harnesses.harness_preview", hid=self.id, api_style=api_style)

    @covers("GET /api/harnesses/{hid}/runtime")
    def runtime(self, platform: str = "") -> dict:
        """Its portable runtime (used inside benchmarks that bring their own image, such as SWE-bench) for a platform
        ("linux/amd64", "linux/arm64"; default this machine's): whether it is built, plus its Dockerfile."""
        return call("harnesses.harness_runtime", hid=self.id, platform=platform)

    @covers("POST /api/harnesses/{hid}/runtime")
    def build_runtime(self, platform: str = "", wait: bool = True, quiet: bool = False) -> Union[dict, Job]:
        """Build the portable runtime for a platform. Returns its status, or the Job with wait=False."""
        job = Job(call("harnesses.build_harness_runtime", hid=self.id, body={"platform": platform})["job_id"])
        return job.wait(quiet=quiet) if wait else job

    @covers("PUT /api/harnesses/custom/{hid}")
    def update(self, manifest: Union[dict, str, Path]) -> "Harness":
        """Replace a custom harness's manifest (rebuild afterwards for image changes to take effect)."""
        self._own()
        call("harnesses.update_custom_harness", hid=self.id, body=_manifest(manifest))
        return self.refresh()

    @covers("DELETE /api/harnesses/custom/{hid}")
    def delete(self) -> None:
        """Remove a custom harness."""
        self._own()
        call("harnesses.delete_custom_harness", hid=self.id)

    def _own(self):
        if self.builtin:
            raise LLMDynoError(f"{self.name} is built in; only custom harnesses can be changed or removed")

    def __repr__(self):
        d = self._d or {}
        return f"<llmdyno.Harness {self.id} {d.get('version', '')} {d.get('status', '')}>".replace("  ", " ")


def _manifest(m: Union[dict, str, Path]) -> dict:
    return dict(m) if isinstance(m, dict) else json.loads(Path(m).expanduser().read_text(encoding="utf-8"))


@covers("GET /api/harnesses")
def list_harnesses(ready: bool | None = None) -> list:
    """Built-in and custom harnesses with their image status; ready=True keeps the ones whose image is built."""
    rows = call("harnesses.list_harnesses")
    return [Harness(h) for h in rows if ready is None or (h["status"] == "ready") == ready]


def harness(id_or_name: Union[str, Harness]) -> Harness:
    """A harness by id ("pi", "opencode", …) or name."""
    if isinstance(id_or_name, Harness):
        return id_or_name
    key = str(id_or_name)
    rows = call("harnesses.list_harnesses")
    hit = [h for h in rows if h["id"] == key] or [h for h in rows if h["name"].lower() == key.lower()]
    if not hit:
        raise NotFoundError(f"no harness {key!r}; one of: {', '.join(h['id'] for h in rows)}")
    return Harness(hit[0])


@covers("POST /api/harnesses/custom")
def add_harness(manifest: Union[dict, str, Path], build: bool = False, quiet: bool = False) -> Harness:
    """Add your own harness from a manifest (a dict or a JSON file; see harness_schema() and docs/HARNESSES.md):
    id, name, install lines (Dockerfile instructions), the command with $PROMPT, config files, API styles.
    build=True builds its image right away."""
    h = Harness(call("harnesses.add_custom_harness", body=_manifest(manifest)))
    return h.build(quiet=quiet) if build else h


@covers("GET /api/harnesses-schema")
def harness_schema() -> dict:
    """The JSON schema of a custom harness manifest."""
    return call("harnesses.harness_schema")
