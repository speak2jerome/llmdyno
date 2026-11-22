# Integrations

LLMDyno works with the tools you already use. Each integration is an optional extra, so the core install stays small.
Nothing is imported until you use it, and if an extra is missing, the error names the one to install.

## Install

```bash
pip install "llmdyno[plot]"          # one extra
pip install "llmdyno[data,plot]"     # several
pip install "llmdyno[all]"           # every integration below
```

| Extra | Installs | Gives you |
|---|---|---|
| `pandas` | pandas | `to_pandas()` for every table |
| `data` | pandas, polars, pyarrow | `to_pandas()`, `to_polars()` and `to_parquet()` |
| `notebook` | ipywidgets, tqdm (and rich) | a live panel for a running plan, progress bars |
| `plot` | matplotlib, plotly | the dashboard's charts |
| `mlflow` | mlflow-skinny | `log_to_mlflow()` |
| `wandb` | wandb | `log_to_wandb()` |
| `langfuse` | langfuse 3 | `log_to_langfuse()` |
| `otel` | opentelemetry-sdk, the OTLP HTTP exporter | `to_otel()` |
| `litellm` | litellm | LiteLLM's price table for `litellm_model()` |
| `hub` | huggingface_hub, pyarrow | `push_to_hub()`, `load_results_from_hub()`, `hf auth login` tokens for downloads |
| `inspect` | inspect-ai | Inspect AI tasks, datasets and logs |
| `all` | all of the above | |

None of these installs Jupyter itself. Benchmarking your own Python or TypeScript agent (`python_harness()`,
`node_harness()`), the local-server helpers and the pytest plugin need no extra. The `dev`, `docs`, `typing` and
`notebooks` extras are for working on LLMDyno itself (see
[CONTRIBUTING.md](https://github.com/speak2jerome/llmdyno/blob/main/CONTRIBUTING.md)); `notebooks` runs the example
notebooks in CI and is not the same as `notebook`.

## Data frames

Every table of a `Results` comes out as a data frame or a Parquet file:

```python
r = llmdyno.results(plan)
r.to_pandas()                 # the leaderboard; or "runs", "cells", "reviews", "rubric", "public"
r.to_polars("cells")
r.to_parquet("runs.parquet", level="runs")     # returns the path; level defaults to "runs"
r.rows("cells")               # the same rows as plain dicts, no extra needed

t = llmdyno.run(run_id).transcript()
t.to_pandas()                 # one row per model call: tokens, time to first token, cost, tool calls
t.to_polars()
```

`run.transcript()` reads at most 20 000 events by default; pass `limit=` for longer runs.

## Notebooks

In Jupyter, `Results` and `Plan` render as tables with score bars, and a `Run` as a table of its details. A running
plan has a live panel (needs the `notebook` extra):

```python
plan = llmdyno.bench(qwen, "suite_quick", wait=False)
plan.live()                   # progress, finished runs with scores, GPU use and VRAM, updating as it runs
```

`Plan.wait()` shows a progress bar when tqdm is installed and you are in a terminal or a notebook;
`plan.wait(progress=False)` turns it off. `bench()` waits the same way; `bench(..., quiet=True)` prints nothing,
progress bar included. `llmdyno.aio` has every call as a coroutine, for notebooks that run their own event loop.

## Charts

The dashboard's charts, in its colours, with matplotlib (default) or plotly. Each method returns the figure, so you can
save or restyle it:

```python
r.plot.leaderboard()                       # stacked points per configuration, best on top
r.plot.heatmap("correctness")              # configuration × benchmark (default metric: "final")
r.plot.pareto(x="cost_usd_total")          # or wall_s_total, peak_vram_mib, decode_tps; y defaults to "final"
r.plot.radar(top=6)                        # the judges' rubric for the top configurations
r.plot.tokens()                            # tokens and cost per configuration
r.plot.leaderboard(backend="plotly").show()
```

`radar()` needs judge reviews (see [Judging](LIBRARY.md#code-review-by-llm-judges)) and raises `ValueError` without
them.

## Experiment tracking and tracing

```python
r.log_to_mlflow(experiment="coding-agents", tracking_uri="http://localhost:5000")
r.log_to_wandb(project="coding-agents")                  # mode="offline" needs no account
r.log_to_langfuse()                                      # LANGFUSE_PUBLIC_KEY / _SECRET_KEY / _HOST
r.to_otel(endpoint="http://localhost:6006/v1/traces")    # any OTLP/HTTP backend: Phoenix, Datadog, Honeycomb, Tempo, …
```

- **MLflow** (`log_to_mlflow(experiment="llmdyno", tracking_uri=None, transcripts=True)`, returns the MLflow run
  ids): one MLflow run per configuration. Params are the profile's settings, model and harness; metrics are the
  scores, time, cost, speed and VRAM; tags start with `llmdyno.`. Artifacts are `llmdyno/configuration.json`,
  `llmdyno/runs.json` and each run's transcript under `transcripts/`. The extra installs `mlflow-skinny`, which logs
  to a tracking server or a folder; a `sqlite:///` store or `mlflow ui` needs the full `mlflow` package.
- **Weights & Biases** (`log_to_wandb(project="llmdyno", entity=None, name=None, mode=None, dir=None,
  transcripts=True)`, returns the run id): one W&B run with the leaderboard, configurations and runs as tables,
  summary metrics for the best configuration, and the transcripts as an artifact.
- **Langfuse** (`log_to_langfuse(client=None, public_key=None, secret_key=None, host=None)`, returns the trace ids):
  each run is a trace, and each model request is a generation with its messages, reply, usage and cost. Correctness,
  instruction following, quality and the final score become Langfuse scores. Langfuse stamps observations with the
  time you log them, and the real times are in metadata. For an exact timeline, send the runs with `to_otel()` to
  Langfuse's OTLP endpoint, with its authorization in `headers=`.
- **OpenTelemetry** (`to_otel(tracer_provider=None, endpoint=None, headers=None, service_name="llmdyno")`, returns
  how many spans were sent): each run is a trace with one span per model request. Spans use the GenAI semantic
  conventions (`gen_ai.usage.input_tokens`, `gen_ai.request.model`, …) and keep the real start and end times. It
  exports over OTLP/HTTP (protobuf), so give the HTTP endpoint (usually port 4318 or a `/v1/traces` URL), not gRPC's
  4317. Without `endpoint=`, the exporter reads `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_HEADERS`. Pass
  your own `tracer_provider` to send spans through your setup; LLMDyno then leaves flushing and shutting it down to you.

To send results as soon as a plan finishes, use `bench(..., auto_log="mlflow")`. It takes `"mlflow"`, `"wandb"`,
`"langfuse"`, `"otel"`, a list of them, or a dict of options such as `{"wandb": {"mode": "offline"}}`. It works only
when `bench()` waits for the plan (the default); with `wait=False`, call the `log_to_…` methods on the results
yourself. If logging fails, for example because an extra is missing, the error comes after the plan has finished and
its results are already saved.

## Model gateways and servers

```python
llmdyno.local_servers()                          # Ollama, LM Studio, vLLM, SGLang, llama.cpp, LiteLLM on this machine
qwen = llmdyno.ollama_model("qwen3-coder:30b", ctx=65536)
lm = llmdyno.openai_compatible("http://localhost:1234/v1", "qwen3-coder-30b")
claude = llmdyno.litellm_model("bedrock/anthropic.claude-sonnet-4-5", reasoning_effort="low")
```

- **`local_servers()`** looks for OpenAI-compatible servers on the machine running LLMDyno, on their usual ports:
  Ollama 11434, LM Studio 1234, vLLM 8000, SGLang 30000, llama.cpp's server 8080 and LiteLLM 4000. It lists each one it
  finds with its models.
- **`ollama_model()`** and **`openai_compatible()`** make a profile on a `custom` provider pointing at that server. The
  sandboxes reach it through `host.docker.internal`. `ctx=` tells LLMDyno and the harness how much context to plan
  for; it does not change the server's own context setting, so set that in Ollama (or your server) to match.
- **`litellm_model()`** uses a LiteLLM proxy you start yourself, for example `litellm --model bedrock/...` or
  `litellm --config config.yaml` (needs `pip install "litellm[proxy]"`). That puts Azure OpenAI, Bedrock, Vertex AI and
  over a hundred other providers behind one endpoint. The default `base_url` is
  `http://host.docker.internal:4000/v1`. The proxy's master key, if it has one, goes in `api_key=`, `LITELLM_API_KEY`
  or `LITELLM_MASTER_KEY`. Budgets cap spend as for any cloud provider.

`litellm_model()` works without the `litellm` extra. The extra only adds LiteLLM's own price table; without it, prices
are looked up in OpenRouter's catalog by the last part of the model name, or you pass `pricing=`.

## Hugging Face Hub

```python
url = r.push_to_hub("you/llmdyno-results")                 # private by default; returns the dataset's URL
r2 = llmdyno.load_results_from_hub("you/llmdyno-results")  # a Results object again (revision=, token=)
```

The dataset has Parquet tables (`configs`, `runs`, `cells`), a dataset card with the leaderboard, and the full results
JSON. The token comes from `token=` or `hf auth login`. Results loaded from the Hub stand alone: their tables, charts
and data frames work, but `export()`, `reference()`, `open()` and transcripts look in your own data folder, where those
plans don't exist.

With `huggingface_hub` installed, LLMDyno also uses the token from `hf auth login` (or `HF_TOKEN`) for model downloads
when you have not saved one in LLMDyno.

## Your own agent

`python_harness()` turns a Python function into a harness. Your agent then runs in the same offline sandbox as the
built-in harnesses, reaching the model only through LLMDyno's proxy. Its transcripts, token counts, budgets and
grading work the same way.

```python
h = llmdyno.python_harness("my_agent:run", requirements=["langgraph==1.2.24", "langchain-openai==1.8.5"])
llmdyno.bench(qwen, "suite_quick", harnesses=[h.id, "pi"])
```

```bash
llmdyno python-harness my_agent:run --requirements "langgraph==1.2.24" "langchain-openai==1.8.5" --build
```

- **The function** is called once per stage, in the task's workspace. It receives any of these keyword arguments it
  declares: `prompt`, `model`, `base_url` (the proxy, OpenAI-compatible), `api_key` (a placeholder; the proxy adds the
  real key), `workspace`, `stage`, `ctx`, `max_tokens`, `reasoning`. It may be async.
- **The return value** is printed: a string as it is, anything else as JSON.
- **The code**: without `source=`, LLMDyno finds the module the way Python would on this machine and copies it into
  the image. `source=` takes the module's file (whose name must match the module) or a folder.
- **Dependencies**: pass `requirements=` with pinned versions. Unlike `node_harness()`, the entry file's own list is
  not read automatically, so the templates' `REQUIREMENTS` lists have to be imported and passed.
- **Stages**: each stage starts a fresh process (`multi_stage="fresh"`); the workspace carries over.
- **The image** is built the first time it is needed, or straight away with `build=True`. It runs Python 3.12.

Ready-made agents are in [examples/agents](https://github.com/speak2jerome/llmdyno/tree/main/examples/agents):

| Framework | Template | Requirements |
|---|---|---|
| LangGraph | `langgraph_agent.py` | `langgraph`, `langchain-openai` |
| OpenAI Agents SDK | `openai_agents_agent.py` | `openai-agents` |
| smolagents | `smolagents_agent.py` | `smolagents[openai]` |
| PydanticAI | `pydantic_ai_agent.py` | `pydantic-ai-slim[openai]` |

```python
from examples.agents.langgraph_agent import REQUIREMENTS
h = llmdyno.python_harness("langgraph_agent:run", source="examples/agents/langgraph_agent.py",
                           requirements=REQUIREMENTS, build=True)
```

[examples/python_agent.py](https://github.com/speak2jerome/llmdyno/blob/main/examples/python_agent.py) does this and
runs the agent next to Pi on the smoke task.

A TypeScript agent works the same way with `node_harness("agent.ts:run")`. Templates for the Vercel AI SDK, Mastra,
LangGraph.js and the OpenAI Agents SDK are in
[examples/agents/ts](https://github.com/speak2jerome/llmdyno/tree/main/examples/agents/ts). See
[JavaScript and TypeScript](JAVASCRIPT.md#benchmark-your-own-typescript-agent).

## Inspect AI

```python
from inspect_ai import eval
task = llmdyno.inspect_task(["t0_smoke_cli", "t5_bugfix_semver"], profile="Qwen 27B 32k")
eval(task, model="none/none")                    # LLMDyno runs the agent; Inspect's own model is not called

suite = llmdyno.import_inspect_samples(dataset, prefix="gsm8k")   # Inspect samples as LLMDyno benchmarks
r.to_inspect_log("logs/llmdyno.eval")            # open with `inspect view`
```

- **`inspect_task(benchmarks, profile, harness="pi", name="llmdyno", **bench_options)`** makes an Inspect task whose
  samples are LLMDyno benchmarks. Each sample runs its own `bench()` plan, so options such as `budget_usd=` apply to
  each sample, not to the whole evaluation.
- **`import_inspect_samples(samples, prefix="inspect", suite=None, answer_file="answer.txt", timeout_s=600)`** turns
  an Inspect dataset into benchmarks called `<prefix>_<sample id>` and a suite called `Inspect: <prefix>`. The agent
  is asked to write its answer to `answer.txt`; multiple-choice options are added to the prompt, and a sample's files
  become the starting workspace. The grader passes when the file contains the target, as a case-sensitive substring,
  so a short target such as `4` also matches `14`: prefer targets that can't appear by accident. Every sample needs a
  target.
- **`to_inspect_log(path, task="llmdyno")`** writes the results as an Inspect log file.

## CI and pytest

Fail a build when a model, prompt or harness change makes things worse:

```bash
llmdyno ci --baseline .llmdyno/baseline.json --plans NEW_PLAN --max-drop 2
llmdyno ci --baseline .llmdyno/baseline.json --plans NEW_PLAN --save .llmdyno/current.json
```

To make the baseline, save a good run's results with `--save` (or `results.to_json(".llmdyno/baseline.json")` from
Python). The file is the `to_json()` format.

| Option | Default | What it does |
|---|---|---|
| `--baseline FILE` | required | The results JSON to compare with. |
| `--plans ID …` | every plan | The plans to check. |
| `--results FILE` | | A results JSON to check instead of plans. |
| `--metric` | `final` | `final`, `correctness`, `quality`, … on a 0-100 scale. |
| `--max-drop` | `2` | How many points a configuration may lose. |
| `--allow-missing` | off | A configuration missing from the new results is fine. |
| `--save FILE` | | Also save the current results there, as the next baseline. |
| `--json` | off | Print the report as JSON. |

`llmdyno ci` exits with 0 when nothing dropped, 1 when a configuration's score dropped by more than `--max-drop` points
or a configuration is missing (unless `--allow-missing`), and 2 when it can't compare (no baseline, no results).
Configurations are matched by profile and harness name, so renaming a profile makes it look missing. From Python,
`llmdyno.compare_results(current, baseline)` returns the same report without failing; so does the
`llmdyno compare-results` command, which always exits 0.
[examples/ci/llmdyno-regression.yml](https://github.com/speak2jerome/llmdyno/blob/main/examples/ci/llmdyno-regression.yml)
is a GitHub Actions workflow to start from. It needs a self-hosted runner with Docker (and a GPU for local models).

### The pytest plugin

The plugin is registered whenever LLMDyno is installed (pytest itself is not a dependency of LLMDyno):

```python
import pytest

@pytest.mark.llmdyno(models="Qwen 27B 32k", benchmarks="t0_smoke_cli", min_score=80)
def test_smoke_still_passes(llmdyno_results):
    assert llmdyno_results.best()["correctness"] == 100
```

- **The marker** takes `models` (also as the first positional argument), `min_score` and `min_correctness` (0-100),
  and any other keyword of `bench()` (default benchmarks `suite_quick`, harness `pi`). A marker without models is an
  error.
- **The plan** runs once per session for each distinct set of arguments, quietly, and tests with the same arguments
  share it. It runs only when the test asks for `llmdyno_results` or the marker has a `min_` limit.
- **The limits** apply to the top configuration (the best final score): the test fails when its final score is under
  `min_score` or its correctness is under `min_correctness`. With limits, a marked test needs no body.
- **Fixtures**: `llmdyno_results` (the plan's `Results`; needs the marker) and `llmdyno` (the library, opened once on
  the data folder).
- **Options**: `--llmdyno-data DIR` picks the data folder, and `--llmdyno-skip` skips marked tests, for machines without
  Docker or a GPU. `-p no:llmdyno` turns the plugin off.
