"""A coding agent built with the OpenAI Agents SDK, ready to benchmark with LLMDyno:

    h = llmdyno.python_harness("openai_agents_agent:run", source="examples/agents/openai_agents_agent.py",
                               requirements=REQUIREMENTS)
    llmdyno.bench(profile, "suite_quick", harnesses=h.id)

It talks Chat Completions to LLMDyno's proxy, so it works with local and cloud models alike; tracing to OpenAI is off
(the sandbox is offline, and LLMDyno records the transcript itself)."""
import subprocess
from pathlib import Path

REQUIREMENTS = ["openai-agents==0.25.0"]
INSTRUCTIONS = ("You are a careful coding agent working in {workspace}. Use the tools to look around, write the code, "
                "and run the tests or the program to check it. When the task is done, reply with a short summary.")


def make_tools(workspace: str):
    from agents import function_tool
    root = Path(workspace)

    @function_tool
    def list_files(path: str = ".") -> str:
        """List the files under a folder of the workspace."""
        base = (root / path).resolve()
        return "\n".join(str(p.relative_to(root)) for p in sorted(base.rglob("*"))
                         if p.is_file() and ".git" not in p.parts)[:20000] or "(empty)"

    @function_tool
    def read_file(path: str) -> str:
        """Read a text file of the workspace."""
        return (root / path).read_text(encoding="utf-8", errors="replace")[:50000]

    @function_tool
    def write_file(path: str, content: str) -> str:
        """Create or overwrite a file of the workspace with this content."""
        p = root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"wrote {path} ({len(content)} characters)"

    @function_tool
    def run_command(command: str) -> str:
        """Run a shell command in the workspace (tests, scripts, ls, …) and return its output."""
        r = subprocess.run(command, shell=True, cwd=root, capture_output=True, text=True, timeout=600)
        return (f"exit {r.returncode}\n{r.stdout}{r.stderr}")[-20000:]

    return [list_files, read_file, write_file, run_command]


def run(prompt: str, model: str, base_url: str, api_key: str, workspace: str, max_tokens: int | None = None) -> str:
    from agents import Agent, ModelSettings, OpenAIChatCompletionsModel, Runner, set_tracing_disabled
    from openai import AsyncOpenAI

    set_tracing_disabled(True)
    client = AsyncOpenAI(base_url=base_url, api_key=api_key, timeout=900, max_retries=2)
    agent = Agent(name="coder", instructions=INSTRUCTIONS.format(workspace=workspace), tools=make_tools(workspace),
                  model=OpenAIChatCompletionsModel(model=model, openai_client=client),
                  model_settings=ModelSettings(max_tokens=max_tokens))
    result = Runner.run_sync(agent, prompt, max_turns=60)
    return str(result.final_output)
