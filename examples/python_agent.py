"""Benchmark your own Python agent next to the built-in harnesses.

Turns the LangGraph agent in examples/agents/ into a harness (its code and pinned requirements are built into an
image on top of LLMDyno's sandbox), then runs it and Pi on the same tasks with the same model. The agent reaches the
model only through LLMDyno's proxy, so its transcript, tokens, cost and grading are recorded like any other harness.

    python examples/python_agent.py "Qwen3.8 27B Q3_K_XL 32k"

The other templates work the same way: openai_agents_agent.py, smolagents_agent.py, pydantic_ai_agent.py."""
import importlib.util
import sys
from pathlib import Path

import llmdyno

AGENTS = Path(__file__).parent / "agents"
spec = importlib.util.spec_from_file_location("langgraph_agent", AGENTS / "langgraph_agent.py")
template = importlib.util.module_from_spec(spec)
spec.loader.exec_module(template)

profile = sys.argv[1] if len(sys.argv) > 1 else llmdyno.list_profiles()[0].name
harness = llmdyno.python_harness("langgraph_agent:run", source=AGENTS / "langgraph_agent.py",
                                 requirements=template.REQUIREMENTS, name="LangGraph coder", build=True)
results = llmdyno.bench(profile, benchmarks="t0_smoke_cli", harnesses=[harness.id, "pi"], name="My agent vs Pi")
print(results)
run = llmdyno.run(results.runs()[0]["run_id"])
print(run.transcript().usage())
