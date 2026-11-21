# pyright: strict, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false
"""Benchmark your own agent: python_harness() turns a Python function into a harness, so an agent built with LangGraph,
the OpenAI Agents SDK, smolagents, PydanticAI or plain code runs in the same offline sandbox, behind the same proxy, with
the same transcripts, budgets and grading as the built-in harnesses.

    h = llmdyno.python_harness("my_agent:run", requirements=["langgraph==1.0.2", "langchain-openai==1.0.1"])
    llmdyno.bench(qwen, "suite_quick", harnesses=h.id)

The entry point is called once per stage, in the task's workspace, with any of these keyword arguments it declares:
prompt, model, base_url, api_key, workspace, stage, ctx, max_tokens, reasoning. base_url is LLMDyno's OpenAI-compatible
proxy (api_key is a placeholder; the proxy adds the real key). It may be async. Whatever it returns is printed.
Ready-made agents for each framework are in examples/agents/."""
from __future__ import annotations

import base64
import importlib.util
import re
from pathlib import Path
from typing import Any, Sequence, Union

from ..errors import InvalidError, NotFoundError
from ._core import call, covers
from .harnesses import Harness

__all__ = ["python_harness"]

MAX_SOURCE_BYTES = 4 * 2**20

RUNNER = '''"""LLMDyno's runner for a Python agent: calls the entry point with the task and the model endpoint."""
import argparse
import asyncio
import importlib
import inspect
import json
import os
import sys

ap = argparse.ArgumentParser()
ap.add_argument("--stage", type=int, default=1)
ap.add_argument("prompt")
a = ap.parse_args()
module, _, name = os.environ["LLMDYNO_ENTRYPOINT"].partition(":")
sys.path.insert(0, os.environ.get("LLMDYNO_AGENT_SRC", ""))
fn = getattr(importlib.import_module(module), name or "run")
env = os.environ
ctx = {"prompt": a.prompt, "model": env["LLMDYNO_MODEL"], "base_url": env["LLMDYNO_BASE_URL"],
       "api_key": env.get("OPENAI_API_KEY", "llmdyno"), "workspace": env.get("LLMDYNO_WORKSPACE") or os.getcwd(),
       "stage": a.stage, "ctx": int(env.get("LLMDYNO_CTX") or 0) or None,
       "max_tokens": int(env.get("LLMDYNO_MAX_TOKENS") or 0) or None, "reasoning": env.get("LLMDYNO_REASONING") or None}
params = inspect.signature(fn).parameters
takes_all = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())
out = fn(**{k: v for k, v in ctx.items() if takes_all or k in params})
if inspect.isawaitable(out):
    out = asyncio.run(out) if inspect.iscoroutine(out) else asyncio.get_event_loop().run_until_complete(out)
if out is not None:
    print(out if isinstance(out, str) else json.dumps(out, default=str, indent=2))
'''


def _sources(module: str, source: Any) -> dict[str, Any]:
    """{relative path: bytes} of the agent's code: one file, or a whole package folder."""
    if source is None:
        spec = importlib.util.find_spec(module.split(".")[0])
        if spec is None or not spec.origin or spec.origin in ("built-in", "frozen"):
            raise NotFoundError(f"cannot find the module {module!r}; pass source= (its file or folder)")
        origin = Path(spec.origin)
        source = origin.parent if origin.name == "__init__.py" else origin
    src = Path(source).expanduser()
    if not src.exists():
        raise NotFoundError(f"{src} does not exist")
    if src.is_file():
        files = {src.name: src.read_bytes()}
    else:
        files = {f"{src.name}/{p.relative_to(src).as_posix()}": p.read_bytes() for p in sorted(src.rglob("*"))
                 if p.is_file() and "__pycache__" not in p.parts and p.suffix not in (".pyc", ".pyo")}
    total = sum(len(b) for b in files.values())
    if total > MAX_SOURCE_BYTES:
        raise InvalidError(f"the agent's code is {total / 2**20:.1f} MB; keep it under 4 MB (data goes in the image "
                           "through requirements, not the source folder)")
    return files


def _write(path: str, data: bytes) -> str:
    folder = path.rsplit("/", 1)[0]
    return f"RUN mkdir -p {folder} && echo {base64.b64encode(data).decode()} | base64 -d > {path}"


@covers("POST /api/harnesses/custom")
def python_harness(entrypoint: str, *, requirements: Sequence[str] = (), source: Union[str, Path, None] = None,
                   id: str | None = None, name: str | None = None, version: str = "1", apis: Sequence[str] = ("openai-chat",),
                   multi_stage: str = "fresh", build: bool = False,
                   quiet: bool = False, replace: bool = True) -> Harness:
    """Make a harness from a Python function ("module:function"). requirements are pip packages installed into the
    image (pin versions for repeatable results); source is the module's file or package folder (found on your path
    when omitted). id defaults to "py-<module>". replace=True updates an existing harness with that id.
    build=True builds the image right away (it also builds on first use)."""
    module, _, fn = entrypoint.partition(":")
    if not module or not re.fullmatch(r"[A-Za-z_][\w.]*", module) or (fn and not fn.isidentifier()):
        raise InvalidError("entrypoint is 'module:function', e.g. 'my_agent:run'")
    hid = id or "py-" + re.sub(r"[^a-z0-9-]+", "-", module.lower()).strip("-")[:38]
    opt = f"/opt/llmdyno-agent-{hid}"
    install = [f"RUN python -m venv {opt}"]
    if requirements:
        reqs = " ".join(f"'{r}'" for r in requirements)
        install.append(f"RUN env -u PIP_NO_INDEX {opt}/bin/pip install --no-cache-dir {reqs}")
    for rel, data in _sources(module, source).items():
        install.append(_write(f"{opt}/src/{rel}", data))
    install.append(_write(f"{opt}/run.py", RUNNER.encode()))
    manifest = {
        "id": hid, "name": name or f"{module} (Python agent)", "version": version,
        "description": f"Python agent {entrypoint}" + (f" with {', '.join(requirements)}" if requirements else ""),
        "install": install,
        "env": {"OPENAI_BASE_URL": "{openai_base_url}", "OPENAI_API_BASE": "{openai_base_url}",
                "OPENAI_API_KEY": "proxy-injects-the-key", "LLMDYNO_MODEL": "{model}",
                "LLMDYNO_BASE_URL": "{openai_base_url}", "LLMDYNO_WORKSPACE": "{workspace}", "LLMDYNO_CTX": "{ctx}",
                "LLMDYNO_MAX_TOKENS": "{max_tokens}", "LLMDYNO_REASONING": "{reasoning}",
                "LLMDYNO_ENTRYPOINT": f"{module}:{fn or 'run'}", "LLMDYNO_AGENT_SRC": f"{opt}/src",
                "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1"},
        "command": f'cd {{workspace}} && {opt}/bin/python {opt}/run.py --stage {{stage}} "$PROMPT"',
        "apis": list(apis), "multi_stage": multi_stage, "tool_style": "native",
    }
    existing = {h["id"] for h in call("harnesses.list_harnesses")}
    if hid in existing and replace:
        call("harnesses.update_custom_harness", hid=hid, body=manifest)
        h = Harness(hid).refresh()
    else:
        h = Harness(call("harnesses.add_custom_harness", body=manifest))
    if build:
        h.build(quiet=quiet)
    return h.refresh()
