"""A coding agent built with LangGraph, ready to benchmark with LLMDyno:

    h = llmdyno.python_harness("langgraph_agent:run", source="examples/agents/langgraph_agent.py",
                               requirements=REQUIREMENTS)
    llmdyno.bench(profile, "suite_quick", harnesses=h.id)

A tool-calling loop (model -> tools -> model …) over four tools that work inside the task's workspace."""
import subprocess
from pathlib import Path

REQUIREMENTS = ["langgraph==1.2.24", "langchain-openai==1.8.5"]
SYSTEM = ("You are a careful coding agent working in {workspace}. Use the tools to look around, write the code, and run "
          "the tests or the program to check it. When the task is done, reply with a short summary.")


def make_tools(workspace: str):
    from langchain_core.tools import tool
    root = Path(workspace)

    @tool
    def list_files(path: str = ".") -> str:
        """List the files under a folder of the workspace."""
        base = (root / path).resolve()
        return "\n".join(str(p.relative_to(root)) for p in sorted(base.rglob("*"))
                         if p.is_file() and ".git" not in p.parts)[:20000] or "(empty)"

    @tool
    def read_file(path: str) -> str:
        """Read a text file of the workspace."""
        return (root / path).read_text(encoding="utf-8", errors="replace")[:50000]

    @tool
    def write_file(path: str, content: str) -> str:
        """Create or overwrite a file of the workspace with this content."""
        p = root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"wrote {path} ({len(content)} characters)"

    @tool
    def run_command(command: str) -> str:
        """Run a shell command in the workspace (tests, scripts, ls, …) and return its output."""
        r = subprocess.run(command, shell=True, cwd=root, capture_output=True, text=True, timeout=600)
        return (f"exit {r.returncode}\n{r.stdout}{r.stderr}")[-20000:]

    return [list_files, read_file, write_file, run_command]


def run(prompt: str, model: str, base_url: str, api_key: str, workspace: str, max_tokens: int | None = None) -> str:
    from langchain_core.messages import SystemMessage
    from langchain_openai import ChatOpenAI
    from langgraph.graph import START, MessagesState, StateGraph
    from langgraph.prebuilt import ToolNode, tools_condition

    tools = make_tools(workspace)
    llm = ChatOpenAI(model=model, base_url=base_url, api_key=api_key, max_tokens=max_tokens, timeout=900,
                     max_retries=2).bind_tools(tools)

    def agent(state: MessagesState):
        return {"messages": [llm.invoke(state["messages"])]}

    graph = StateGraph(MessagesState)
    graph.add_node("agent", agent)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", tools_condition)
    graph.add_edge("tools", "agent")
    app = graph.compile()
    out = app.invoke({"messages": [SystemMessage(SYSTEM.format(workspace=workspace)), ("user", prompt)]},
                     config={"recursion_limit": 120})
    last = out["messages"][-1]
    return last.content if isinstance(last.content, str) else str(last.content)
