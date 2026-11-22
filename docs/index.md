# LLMDyno

![LLMDyno: a pixel-art dinosaur with a rocket strapped to its back, running on a treadmill](images/banner.svg)

LLMDyno benchmarks local (llama.cpp) and cloud LLMs as **coding agents**. Real agent harnesses (Pi, OpenCode, Codex
CLI, Qwen Code, Crush, Aider, mini-SWE-agent, or your own) work on real tasks in offline Docker sandboxes, behind a proxy
that records every request and enforces budgets. The results come from four sources: hidden tests, static analysis,
behaviour probes and blind LLM judges. Before a local model downloads, LLMDyno tells you whether it will fit in your
GPU's memory.

It is a web dashboard, a Python library and a command line, all working on the same data. From JavaScript or
TypeScript, `npx llmdyno` starts it and the `llmdyno` npm package drives it.

```bash
pip install "llmdyno[plot]"        # plain `pip install llmdyno` without the charts
llmdyno serve --open
```

```python
import llmdyno

gpt = llmdyno.cloud_model("openai", "gpt-6-luna", reasoning_effort="low", budget_usd=2)
qwen = llmdyno.local_model("unsloth/Qwen3.8-27B-GGUF", quant="UD-Q3_K_XL", ctx=49152)
results = llmdyno.bench([gpt, qwen], benchmarks="suite_quick", harnesses="pi")
print(results)
results.plot.leaderboard()
```

![LLMDyno results dashboard: leaderboard, per-benchmark heatmap and radar chart](images/results.png)

## Where to go next

- **[Getting started](GETTING_STARTED.md)**: requirements, installing, first-time setup, and a first benchmark from the
  dashboard, Python, the command line or TypeScript.
- **[The dashboard](DASHBOARD.md)**: what every page of the web app shows and does.
- **[Python library and CLI](LIBRARY.md)**: everything the dashboard does, from code or a terminal.
- **[Integrations](INTEGRATIONS.md)**:
    - pandas and polars, notebooks and charts;
    - MLflow, Weights & Biases, Langfuse and OpenTelemetry;
    - LiteLLM and Ollama, and the Hugging Face Hub;
    - your own LangGraph or other agent, Inspect AI, and pytest and CI.
- **[Remote mode](REMOTE.md)**: run it on the GPU box, drive it from your laptop.
- **[JavaScript and TypeScript](JAVASCRIPT.md)**: `npx llmdyno`, the npm client, and benchmarking your own TypeScript agent.
- **[Benchmarks](BENCHMARKS.md)** and **[Harnesses](HARNESSES.md)**: what is measured, and how to add your own.
- **[Configuration](CONFIGURATION.md)** and **[Troubleshooting](TROUBLESHOOTING.md)**: the data folder, settings and
  environment variables, and what to do when something goes wrong.
- **Reference**: [the Python API](reference/index.md), [every command](reference/cli.md) and
  [every web API route](reference/web-api.md), generated from the code.

Source, issues and releases: [github.com/speak2jerome/llmdyno](https://github.com/speak2jerome/llmdyno). What changed in
each version: [the changelog](CHANGELOG.md).

LLMDyno is part of [Zynxtech open source](https://zynxtech.in/), built by [Jerome Eliezer](https://zynxtech.in/about/). Project page:
[zynxtech.in/projects/llmdyno](https://zynxtech.in/projects/llmdyno/).
