# Examples

Runnable scripts, agent templates and notebooks for LLMDyno. Each script's opening comment says what it needs. Install
LLMDyno first (`pip install llmdyno`), and have Docker running for anything that runs a benchmark.

## Scripts

| File | What it does | Needs |
|---|---|---|
| [quickstart.py](quickstart.py) | Sets up Pi, then compares a cloud model (GPT-6 Luna) with a local Qwen3.8 27B on the quick suite, saves a CSV and opens the dashboard. | Docker, `OPENAI_API_KEY`, a GPU with about 16 GB; several GB of downloads; under $1 of API spend; about 5 minutes per model locally. |
| [local_settings_sweep.py](local_settings_sweep.py) | Tries one local model at three context sizes and two KV-cache types, keeps the settings that fit, and ranks them on two tasks. | Docker and a GPU; no API spend; up to 24 runs. |
| [python_agent.py](python_agent.py) | Builds the LangGraph template below into a harness and runs it next to Pi on the smoke task. | Docker, internet for the image build, and an existing profile (`python examples/python_agent.py "<profile>"`). |
| [swebench_mini.py](swebench_mini.py) | Installs the official SWE-bench harness, imports three tasks from SWE-bench Verified mini, runs Pi on them and writes the predictions file. | Docker, internet, 1 to 5 GB per task image, 10 to 40 minutes per task on a local model, and a profile with about 64k context (`python examples/swebench_mini.py "<profile>"`). |

```bash
python examples/quickstart.py
```

## Your own agent

Templates for benchmarking an agent you built, in the same sandbox as the built-in harnesses. Nothing needs installing
on your machine: the packages are installed into the harness image.

| File | Framework | Register it with |
|---|---|---|
| [agents/langgraph_agent.py](agents/langgraph_agent.py) | LangGraph | `llmdyno.python_harness("langgraph_agent:run", source=..., requirements=REQUIREMENTS)` |
| [agents/openai_agents_agent.py](agents/openai_agents_agent.py) | OpenAI Agents SDK | the same, with that file |
| [agents/smolagents_agent.py](agents/smolagents_agent.py) | smolagents | the same |
| [agents/pydantic_ai_agent.py](agents/pydantic_ai_agent.py) | PydanticAI | the same |
| [agents/ts/vercel_ai_agent.ts](agents/ts/vercel_ai_agent.ts) | Vercel AI SDK | `llmdyno.node_harness("vercel_ai_agent.ts:run", source=...)` |
| [agents/ts/mastra_agent.ts](agents/ts/mastra_agent.ts) | Mastra | the same, with that file |
| [agents/ts/langgraph_agent.ts](agents/ts/langgraph_agent.ts) | LangGraph.js | the same |
| [agents/ts/openai_agents_agent.ts](agents/ts/openai_agents_agent.ts) | OpenAI Agents SDK for JavaScript | the same |

Each Python template lists its pinned packages in `REQUIREMENTS`, which you pass to `python_harness()`; each
TypeScript template lists them in `export const PACKAGES`, which `node_harness()` reads by itself. See
[Integrations](https://speak2jerome.github.io/llmdyno/INTEGRATIONS/#your-own-agent) and
[JavaScript and TypeScript](https://speak2jerome.github.io/llmdyno/JAVASCRIPT/#benchmark-your-own-typescript-agent).

## Notebooks

Both run on the bundled sample results, so they need no Docker, GPU, keys or network.

| File | What it shows | Needs |
|---|---|---|
| [notebooks/01_explore_results.ipynb](notebooks/01_explore_results.ipynb) | Data frames, the dashboard's charts, re-weighting the scores, judge agreement. | `pip install "llmdyno[data,plot]" jupyterlab` |
| [notebooks/02_tracking_and_tracing.ipynb](notebooks/02_tracking_and_tracing.ipynb) | Sending results to MLflow (a local folder), Weights & Biases (offline) and OpenTelemetry (in memory). | `pip install "llmdyno[data,mlflow,wandb,otel]" jupyterlab` |

```bash
jupyter lab examples/notebooks/01_explore_results.ipynb
```

## CI

[ci/llmdyno-regression.yml](ci/llmdyno-regression.yml) is a GitHub Actions workflow that benchmarks a cloud model on
every pull request and fails it when scores drop against a baseline kept in the repository. It needs a self-hosted
runner with Docker (and a GPU for local models). See
[CI and pytest](https://speak2jerome.github.io/llmdyno/INTEGRATIONS/#ci-and-pytest).
