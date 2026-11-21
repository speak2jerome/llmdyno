"""A coding agent built with PydanticAI, ready to benchmark with LLMDyno:

    h = llmdyno.python_harness("pydantic_ai_agent:run", source="examples/agents/pydantic_ai_agent.py",
                               requirements=REQUIREMENTS)
    llmdyno.bench(profile, "suite_quick", harnesses=h.id)
"""
import subprocess
from pathlib import Path

REQUIREMENTS = ["pydantic-ai-slim[openai]==2.71.0"]
INSTRUCTIONS = ("You are a careful coding agent working in {workspace}. Use the tools to look around, write the code, "
                "and run the tests or the program to check it. When the task is done, reply with a short summary.")


def run(prompt: str, model: str, base_url: str, api_key: str, workspace: str, max_tokens: int | None = None) -> str:
    from pydantic_ai import Agent, UsageLimits
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider
    from pydantic_ai.settings import ModelSettings

    root = Path(workspace)
    llm = OpenAIChatModel(model, provider=OpenAIProvider(base_url=base_url, api_key=api_key))
    agent = Agent(llm, instructions=INSTRUCTIONS.format(workspace=workspace),
                  model_settings=ModelSettings(max_tokens=max_tokens, timeout=900) if max_tokens else None)

    @agent.tool_plain
    def list_files(path: str = ".") -> str:
        """List the files under a folder of the workspace."""
        base = (root / path).resolve()
        return "\n".join(str(p.relative_to(root)) for p in sorted(base.rglob("*"))
                         if p.is_file() and ".git" not in p.parts)[:20000] or "(empty)"

    @agent.tool_plain
    def read_file(path: str) -> str:
        """Read a text file of the workspace."""
        return (root / path).read_text(encoding="utf-8", errors="replace")[:50000]

    @agent.tool_plain
    def write_file(path: str, content: str) -> str:
        """Create or overwrite a file of the workspace with this content."""
        p = root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"wrote {path} ({len(content)} characters)"

    @agent.tool_plain
    def run_command(command: str) -> str:
        """Run a shell command in the workspace (tests, scripts, ls, …) and return its output."""
        r = subprocess.run(command, shell=True, cwd=root, capture_output=True, text=True, timeout=600)
        return (f"exit {r.returncode}\n{r.stdout}{r.stderr}")[-20000:]

    result = agent.run_sync(prompt, usage_limits=UsageLimits(request_limit=60))
    return str(result.output)
