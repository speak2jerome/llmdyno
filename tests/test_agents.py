"""python_harness(): your own Python agent as a harness. The image build and a real run are exercised separately
(they need Docker and a model); here the harness definition is checked, down to the bytes of your code."""
import base64
import re
from pathlib import Path

import pytest

import llmdyno
from llmdyno.sdk.agents import RUNNER

EXAMPLES = Path(__file__).resolve().parent.parent / "examples" / "agents"


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
