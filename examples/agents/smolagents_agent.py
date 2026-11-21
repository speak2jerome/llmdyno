"""A coding agent built with Hugging Face smolagents, ready to benchmark with LLMDyno:

    h = llmdyno.python_harness("smolagents_agent:run", source="examples/agents/smolagents_agent.py",
                               requirements=REQUIREMENTS)
    llmdyno.bench(profile, "suite_quick", harnesses=h.id)

A ToolCallingAgent (native tool calls; it ends by calling its final_answer tool)."""
import subprocess
from pathlib import Path

REQUIREMENTS = ["smolagents[openai]==1.26.0"]
INSTRUCTIONS = ("You work in {workspace}. Use the tools to look around, write the code, and run the tests or the "
                "program to check it. When the task is done, call final_answer with a short summary.")


def make_tools(workspace: str):
    from smolagents import tool
    root = Path(workspace)

    @tool
    def list_files(path: str = ".") -> str:
        """List the files under a folder of the workspace.

        Args:
            path: folder relative to the workspace, "." for all of it.
        """
        base = (root / path).resolve()
        return "\n".join(str(p.relative_to(root)) for p in sorted(base.rglob("*"))
                         if p.is_file() and ".git" not in p.parts)[:20000] or "(empty)"

    @tool
    def read_file(path: str) -> str:
        """Read a text file of the workspace.

        Args:
            path: file path relative to the workspace.
        """
        return (root / path).read_text(encoding="utf-8", errors="replace")[:50000]

    @tool
    def write_file(path: str, content: str) -> str:
        """Create or overwrite a file of the workspace with this content.

        Args:
            path: file path relative to the workspace.
            content: the whole new content of the file.
        """
        p = root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"wrote {path} ({len(content)} characters)"

    @tool
    def run_command(command: str) -> str:
        """Run a shell command in the workspace (tests, scripts, ls, ...) and return its output.

        Args:
            command: the shell command to run.
        """
        r = subprocess.run(command, shell=True, cwd=root, capture_output=True, text=True, timeout=600)
        return (f"exit {r.returncode}\n{r.stdout}{r.stderr}")[-20000:]

    return [list_files, read_file, write_file, run_command]


def run(prompt: str, model: str, base_url: str, api_key: str, workspace: str, max_tokens: int | None = None) -> str:
    from smolagents import OpenAIServerModel, ToolCallingAgent

    llm = OpenAIServerModel(model_id=model, api_base=base_url, api_key=api_key,
                            **({"max_tokens": max_tokens} if max_tokens else {}))
    agent = ToolCallingAgent(tools=make_tools(workspace), model=llm, max_steps=60, verbosity_level=1,
                             instructions=INSTRUCTIONS.format(workspace=workspace))
    return str(agent.run(prompt))
