"""python_harness() and node_harness(): your own agent as a harness. The image build and a real run are exercised
separately (they need Docker and a model); here the harness definition is checked, down to the bytes of your code, and
the runners are run against a small agent."""
import base64
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import llmdyno
from llmdyno.sdk.agents import NODE_RUNNER, RUNNER

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "agents"
TS_EXAMPLES = EXAMPLES / "ts"


def _embedded(dockerfile: str) -> dict:
    """{path in the image: bytes} of every file the Dockerfile writes with base64."""
    out = {}
    for b64, path in re.findall(r"echo ([A-Za-z0-9+/=]+) \| base64 -d > (\S+)", dockerfile):
        out[path] = base64.b64decode(b64)
    return out


def test_python_harness_from_a_file():
    h = llmdyno.python_harness("langgraph_agent:run", source=EXAMPLES / "langgraph_agent.py",
                               requirements=["langgraph==1.2.24", "langchain-openai==1.8.5"])
    try:
        assert h.id == "py-langgraph-agent" and not h.builtin and h.apis == ["openai-chat"]
        df = h.dockerfile()
        assert "env -u PIP_NO_INDEX /opt/llmdyno-agent-py-langgraph-agent/bin/pip install --no-cache-dir " \
               "'langgraph==1.2.24' 'langchain-openai==1.8.5'" in df
        files = _embedded(df)
        src = "/opt/llmdyno-agent-py-langgraph-agent/src/langgraph_agent.py"
        assert files[src] == (EXAMPLES / "langgraph_agent.py").read_bytes()
        assert files["/opt/llmdyno-agent-py-langgraph-agent/run.py"] == RUNNER.encode()
        prev = h.preview()
        assert prev["command"].startswith("cd /workspace && /opt/llmdyno-agent-py-langgraph-agent/bin/python ")
        assert "--stage 1" in prev["command"] and prev["env"]["LLMDYNO_ENTRYPOINT"] == "langgraph_agent:run"
        assert prev["env"]["LLMDYNO_BASE_URL"] == prev["env"]["OPENAI_BASE_URL"] and prev["env"]["LLMDYNO_MODEL"]
        again = llmdyno.python_harness("langgraph_agent:run", source=EXAMPLES / "langgraph_agent.py",
                                       name="LangGraph coder")
        assert again.id == h.id and again.name == "LangGraph coder" and "pip install" not in again.dockerfile()
    finally:
        llmdyno.harness("py-langgraph-agent").delete()


def test_python_harness_from_a_package(tmp_path):
    pkg = tmp_path / "myagent"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "__init__.py").write_text("from .core import run\n")
    (pkg / "core.py").write_text("def run(prompt, model, base_url):\n    return {'echo': prompt, 'd': {1: 2}}\n")
    (pkg / "sub" / "tools.py").write_bytes(b"X = '{model}'  # braces survive untouched\n")
    (pkg / "__pycache__").mkdir()
    (pkg / "__pycache__" / "core.cpython-312.pyc").write_bytes(b"junk")
    h = llmdyno.python_harness("myagent:run", source=pkg, id="my-agent", multi_stage="resume", apis=["openai-chat"])
    try:
        files = _embedded(h.dockerfile())
        names = sorted(p.split("/src/", 1)[1] for p in files if "/src/" in p)
        assert names == ["myagent/__init__.py", "myagent/core.py", "myagent/sub/tools.py"]
        assert files["/opt/llmdyno-agent-my-agent/src/myagent/sub/tools.py"] == b"X = '{model}'  # braces survive untouched\n"
        assert h["multi_stage"] == "resume"
    finally:
        h.delete()


def test_python_harness_errors(tmp_path):
    with pytest.raises(llmdyno.InvalidError, match="module:function"):
        llmdyno.python_harness("not a module")
    with pytest.raises(llmdyno.NotFoundError, match="cannot find"):
        llmdyno.python_harness("no_such_module_anywhere:run")
    big = tmp_path / "big.py"
    big.write_bytes(b"#" * (5 * 2**20))
    with pytest.raises(llmdyno.InvalidError, match="under 4 MB"):
        llmdyno.python_harness("big:run", source=big)


def test_runner_calls_the_entry_point(tmp_path, monkeypatch):
    """The runner passes only the arguments the function declares, awaits coroutines and prints the result."""
    import subprocess
    import sys
    (tmp_path / "agent_mod.py").write_text(
        "import asyncio\n"
        "async def run(prompt, workspace, stage):\n"
        "    await asyncio.sleep(0)\n"
        "    return {'prompt': prompt, 'stage': stage, 'cwd_ok': workspace.endswith('ws')}\n")
    (tmp_path / "ws").mkdir()
    (tmp_path / "run.py").write_text(RUNNER, encoding="utf-8")
    env = {"LLMDYNO_ENTRYPOINT": "agent_mod:run", "LLMDYNO_AGENT_SRC": str(tmp_path), "LLMDYNO_MODEL": "m",
           "LLMDYNO_BASE_URL": "http://proxy/v1", "LLMDYNO_WORKSPACE": str(tmp_path / "ws"), "SYSTEMROOT": "C:\\Windows",
           "PATH": ""}
    out = subprocess.run([sys.executable, str(tmp_path / "run.py"), "--stage", "2", "Fix the bug"], env=env,
                         capture_output=True, text=True, cwd=tmp_path / "ws")
    assert out.returncode == 0, out.stderr
    assert '"stage": 2' in out.stdout and '"cwd_ok": true' in out.stdout and "Fix the bug" in out.stdout


# ------------------------------------------------------------------ node_harness()
def test_node_harness_from_a_template():
    """A template's own PACKAGES list is installed; its code, a package.json and the runner go into the image."""
    h = llmdyno.node_harness("vercel_ai_agent.ts:run", source=TS_EXAMPLES / "vercel_ai_agent.ts")
    try:
        assert h.id == "js-vercel-ai-agent" and h.name == "vercel_ai_agent (TypeScript agent)" and not h.builtin
        opt = "/opt/llmdyno-agent-js-vercel-ai-agent"
        df = h.dockerfile()
        assert (f"RUN cd {opt}/app && npm_config_offline=false npm install --no-audit --no-fund --omit=dev "
                "'ai@7.0.179' '@ai-sdk/openai-compatible@3.0.94' 'zod@4.6.7' && npm cache clean --force") in df
        files = _embedded(df)
        assert files[f"{opt}/app/vercel_ai_agent.ts"] == (TS_EXAMPLES / "vercel_ai_agent.ts").read_bytes()
        assert json.loads(files[f"{opt}/app/package.json"]) == {"name": h.id, "private": True, "type": "module"}
        assert files[f"{opt}/run.mjs"] == NODE_RUNNER.encode()
        prev = h.preview()
        assert prev["command"].startswith(f"cd /workspace && node --disable-warning=ExperimentalWarning {opt}/run.mjs ")
        assert "--stage 1" in prev["command"] and '"$PROMPT"' in prev["command"]
        assert prev["env"]["LLMDYNO_ENTRY_FILE"] == "vercel_ai_agent.ts" and prev["env"]["LLMDYNO_ENTRY_EXPORT"] == "run"
        assert prev["env"]["LLMDYNO_AGENT_DIR"] == f"{opt}/app" and prev["env"]["LLMDYNO_BASE_URL"]
        again = llmdyno.node_harness("vercel_ai_agent.ts", source=TS_EXAMPLES / "vercel_ai_agent.ts", packages=[],
                                     name="Vercel coder")
        assert again.id == h.id and again.name == "Vercel coder" and "npm install" not in again.dockerfile()
    finally:
        llmdyno.harness("js-vercel-ai-agent").delete()


def test_every_typescript_template_declares_pinned_packages():
    from llmdyno.sdk.agents import _declared_packages
    templates = sorted(TS_EXAMPLES.glob("*.ts"))
    assert [t.stem for t in templates] == ["langgraph_agent", "mastra_agent", "openai_agents_agent", "vercel_ai_agent"]
    for t in templates:
        packages = _declared_packages(t.read_text(encoding="utf-8"))
        assert packages and all(re.fullmatch(r"(@[\w.-]+/)?[\w.-]+@\d+\.\d+\.\d+", p) for p in packages), t.name
        assert "export async function run(task: Task)" in t.read_text(encoding="utf-8")


def test_node_harness_from_a_folder(tmp_path):
    """A project folder: its package.json is used and installed, node_modules and build output are left out."""
    proj = tmp_path / "my-agent"
    (proj / "src" / "lib").mkdir(parents=True)
    (proj / "package.json").write_text('{"name": "my-agent", "type": "module", "dependencies": {"zod": "4.6.7"}}\n')
    (proj / "src" / "agent.ts").write_text("export async function solve(task: { prompt: string }) { return task.prompt; }\n")
    (proj / "src" / "lib" / "tools.ts").write_bytes(b"export const X = '{model}';  // braces survive\n")
    for junk in ("node_modules/zod/index.js", "dist/agent.js", ".git/HEAD"):
        (proj / junk).parent.mkdir(parents=True, exist_ok=True)
        (proj / junk).write_text("junk")
    h = llmdyno.node_harness("./src/agent.ts:solve", source=proj, packages=[], multi_stage="resume")
    try:
        assert h.id == "js-agent" and h["multi_stage"] == "resume"
        app = "/opt/llmdyno-agent-js-agent/app"
        files = _embedded(h.dockerfile())
        assert sorted(p[len(app) + 1:] for p in files if p.startswith(app)) == \
            ["package.json", "src/agent.ts", "src/lib/tools.ts"]
        assert files[f"{app}/src/lib/tools.ts"] == b"export const X = '{model}';  // braces survive\n"
        assert f"RUN cd {app} && npm_config_offline=false npm install --no-audit --no-fund --omit=dev && npm cache" \
            in h.dockerfile()
        env = h.preview()["env"]
        assert env["LLMDYNO_ENTRY_FILE"] == "src/agent.ts" and env["LLMDYNO_ENTRY_EXPORT"] == "solve"
    finally:
        h.delete()


def test_node_harness_errors(tmp_path):
    with pytest.raises(llmdyno.InvalidError, match="file.ts:function"):
        llmdyno.node_harness("agent:run")
    with pytest.raises(llmdyno.NotFoundError, match="does not exist"):
        llmdyno.node_harness(str(tmp_path / "missing.ts"))
    (tmp_path / "proj").mkdir()
    with pytest.raises(llmdyno.NotFoundError, match="not in"):
        llmdyno.node_harness("agent.ts", source=tmp_path / "proj")
    big = tmp_path / "big.js"
    big.write_bytes(b"//" * (3 * 2**20))
    with pytest.raises(llmdyno.InvalidError, match="under 4 MB"):
        llmdyno.node_harness("big.js:run", source=big)


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node.js")
def test_node_runner_calls_the_entry_point(tmp_path):
    """The runner passes one task object, awaits the result, prints it, and runs TypeScript as it is (Node 22.18+)."""
    (tmp_path / "app").mkdir()
    (tmp_path / "ws").mkdir()
    (tmp_path / "app" / "package.json").write_text('{"type": "module"}\n')
    (tmp_path / "app" / "agent.mjs").write_text(
        "export default async function (task) {\n"
        "  return { prompt: task.prompt, stage: task.stage, max: task.maxTokens, cwdOk: process.cwd().endsWith('ws') };\n"
        "}\n")
    (tmp_path / "app" / "typed.ts").write_text(
        "interface Task { prompt: string; model: string }\n"
        "export async function run(task: Task): Promise<string> { return `${task.model}: ${task.prompt.toUpperCase()}`; }\n")
    (tmp_path / "app" / "broken.mjs").write_text("export function run() { throw new Error('agent crashed'); }\n")
    (tmp_path / "run.mjs").write_text(NODE_RUNNER, encoding="utf-8")

    def run(entry, export="run"):
        env = {**{k: v for k, v in os.environ.items() if k.upper() in ("PATH", "SYSTEMROOT")},
               "LLMDYNO_AGENT_DIR": str(tmp_path / "app"), "LLMDYNO_ENTRY_FILE": entry, "LLMDYNO_ENTRY_EXPORT": export,
               "LLMDYNO_MODEL": "m", "LLMDYNO_BASE_URL": "http://proxy/v1", "LLMDYNO_WORKSPACE": str(tmp_path / "ws"),
               "LLMDYNO_MAX_TOKENS": "4096"}
        return subprocess.run(["node", "--disable-warning=ExperimentalWarning", str(tmp_path / "run.mjs"), "--stage", "2",
                               "Fix the bug"], env=env, capture_output=True, text=True, cwd=tmp_path / "ws", timeout=60)

    out = run("agent.mjs")
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == {"prompt": "Fix the bug", "stage": 2, "max": 4096, "cwdOk": True}
    version = tuple(int(x) for x in subprocess.run(["node", "-p", "process.versions.node"], capture_output=True,
                                                   text=True).stdout.strip().split("."))
    if version >= (22, 18):
        typed = run("typed.ts")
        assert typed.returncode == 0 and typed.stdout.strip() == "m: FIX THE BUG", typed.stderr
    crashed = run("broken.mjs")
    assert crashed.returncode == 1 and "agent crashed" in crashed.stderr
    missing = run("agent.mjs", export="nope")
    assert missing.returncode == 1 and "exports no function nope" in missing.stderr
