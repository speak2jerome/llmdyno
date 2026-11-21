# Integrations

LLMDyno works with the tools you already use. Each integration is an optional extra, so the core install stays small:

```bash
pip install "llmdyno[plot]"          # or data, notebook, mlflow, wandb, langfuse, otel, litellm, hub, inspect
pip install "llmdyno[all]"           # everything
```

Nothing is imported until you use it. If an extra is missing, the error names the one to install.

| Extra | Gives you |
|---|---|
| `data` | `to_pandas()`, `to_polars()`, `to_parquet()` for every table |
| `notebook` | a live widget for a running plan, progress bars |
| `plot` | the dashboard's charts in matplotlib or plotly |
| `mlflow`, `wandb`, `langfuse`, `otel` | experiment tracking and tracing |
| `litellm`, `hub` | models behind LiteLLM, publishing results to Hugging Face |
| `inspect` | Inspect AI tasks, datasets and logs |

Benchmarking your own Python agent (`python_harness`) and the pytest plugin need no extra.

## Data frames

Every table of a `Results` comes out as a data frame or a Parquet file:

```python
r = llmdyno.results(plan)
r.to_pandas()                 # the leaderboard; or "runs", "cells", "reviews", "rubric", "public"
r.to_polars("cells")
r.to_parquet("runs.parquet", level="runs")
r.rows("cells")               # the same rows as plain dicts

t = llmdyno.run(run_id).transcript()
t.to_pandas()                 # one row per model call: tokens, time to first token, cost, tool calls
```

## Notebooks

`Results`, `Plan` and `Run` render as tables with score bars in Jupyter. A running plan has a live panel:

```python
plan = llmdyno.bench(qwen, "suite_quick", wait=False)
plan.live()                   # progress, finished runs with scores, GPU readings, updating as it runs
```

`bench()` and `Plan.wait()` show a progress bar when tqdm is installed and you are in a terminal or a notebook.
Pass `progress=False` to turn it off. `llmdyno.aio` has every call as a coroutine, for notebooks that run their own
event loop.

## Charts

The dashboard's charts, in its colours, with matplotlib (default) or plotly:

```python
r.plot.leaderboard()                       # stacked points per configuration, best on top
r.plot.heatmap("correctness")              # configuration × benchmark
r.plot.pareto(x="cost_usd_total")          # or wall_s_total, peak_vram_mib, decode_tps
r.plot.radar()                             # the judges' rubric
r.plot.tokens()
r.plot.leaderboard(backend="plotly").show()
```

Each method returns the figure, so you can save it or restyle it.

## Experiment tracking and tracing

```python
r.log_to_mlflow(experiment="coding-agents", tracking_uri="http://localhost:5000")
r.log_to_wandb(project="coding-agents")                  # mode="offline" needs no account
r.log_to_langfuse()                                      # LANGFUSE_PUBLIC_KEY / _SECRET_KEY / _HOST
r.to_otel(endpoint="http://localhost:6006/v1/traces")    # any OTLP backend: Phoenix, Datadog, Honeycomb, Tempo, …
```

- **MLflow**: one run per configuration. Params are the profile's settings, model and harness. Metrics are the scores,
  time, cost, speed and VRAM. Artifacts are the result JSON and each run's transcript.
- **Weights & Biases**: the leaderboard, configurations and runs as tables, summary metrics for the best
  configuration, and the transcripts as an artifact.
- **Langfuse**: each run is a trace, and each model request is a generation with its messages, reply, usage and cost.
  Grader scores become Langfuse scores. Langfuse stamps observations with the time you log them, and the real times
  are in metadata. For an exact timeline, send the same runs with `to_otel()` to Langfuse's OTLP endpoint.
- **OpenTelemetry**: each run is a trace with one span per model request. Spans use the GenAI semantic conventions
  (`gen_ai.usage.input_tokens`, `gen_ai.request.model`, …) and keep the real start and end times.

To send results as soon as a plan finishes, use `bench(..., auto_log="mlflow")`. It also takes a list, or a dict of
options such as `{"wandb": {"mode": "offline"}}`.

## Model gateways and servers

```python
llmdyno.local_servers()                          # Ollama, LM Studio, vLLM, SGLang, llama.cpp, LiteLLM on this machine
qwen = llmdyno.ollama_model("qwen3-coder:30b", ctx=65536)
lm = llmdyno.openai_compatible("http://localhost:1234/v1", "qwen3-coder-30b")
claude = llmdyno.litellm_model("bedrock/anthropic.claude-sonnet-4-5", reasoning_effort="low")
```

`litellm_model()` uses a LiteLLM proxy you start yourself, for example `litellm --model bedrock/...` or `litellm --config
config.yaml` (needs `pip install "litellm[proxy]"`). That puts Azure OpenAI, Bedrock, Vertex AI and over a hundred
other providers behind one endpoint. Prices come from LiteLLM's own table when the `litellm` package is installed, and
budgets cap spend as for any cloud provider. The proxy's master key, if it has one, goes in `api_key=` or
`LITELLM_API_KEY`.

## Hugging Face Hub

```python
r.push_to_hub("you/llmdyno-results")                       # private by default
r2 = llmdyno.load_results_from_hub("you/llmdyno-results")  # a Results object again
```

The dataset has Parquet tables (`configs`, `runs`, `cells`), a dataset card with the leaderboard, and the full results
JSON. With `huggingface_hub` installed, LLMDyno also uses the token from `hf auth login` for downloads when you have not
saved one in LLMDyno.

## Your own agent

`python_harness()` turns a Python function into a harness. Your agent then runs in the same offline sandbox as the
built-in harnesses, reaching the model only through LLMDyno's proxy. Its transcripts, token counts, budgets and
grading work the same way.

```python
h = llmdyno.python_harness("my_agent:run", requirements=["langgraph==1.2.24", "langchain-openai==1.8.5"])
llmdyno.bench(qwen, "suite_quick", harnesses=[h.id, "pi"])
```

The function is called once per stage, in the task's workspace. It receives any of these it declares: `prompt`,
`model`, `base_url` (the proxy, OpenAI-compatible), `api_key`, `workspace`, `stage`, `ctx`, `max_tokens`, `reasoning`.
It may be async. Your code is built into the image together with the pinned requirements.

Ready-made agents are in [examples/agents](https://github.com/speak2jerome/llmdyno/tree/main/examples/agents). Each one
was checked end to end against a scripted model:

| Framework | Template |
|---|---|
| LangGraph | `langgraph_agent.py` |
| OpenAI Agents SDK | `openai_agents_agent.py` |
| smolagents | `smolagents_agent.py` |
| PydanticAI | `pydantic_ai_agent.py` |

## Inspect AI

```python
from inspect_ai import eval
task = llmdyno.inspect_task(["t0_smoke_cli", "t5_bugfix_semver"], profile="Qwen 27B 32k")
eval(task, model="none/none")                    # LLMDyno runs the agent; Inspect's own model is not called

suite = llmdyno.import_inspect_samples(dataset, prefix="gsm8k")   # Inspect samples as LLMDyno benchmarks
r.to_inspect_log("logs/llmdyno.eval")            # open with `inspect view`
```

Imported samples ask the agent to write its answer to `answer.txt`, and the grader checks that file contains the
sample's target.

## CI and pytest

Fail a build when a model, prompt or harness change makes things worse:

```bash
llmdyno results --plans PLAN --json > .llmdyno/baseline.json      # once, from a good run
llmdyno ci --baseline .llmdyno/baseline.json --plans NEW_PLAN --max-drop 2
```

`llmdyno ci` exits with 1 in two cases: a configuration's score (final by default, or `--metric correctness`, …)
dropped by more than `--max-drop` points, or a configuration is missing (unless you pass `--allow-missing`). From
Python, `llmdyno.compare_results(current, baseline)` returns the same report.
[examples/ci/llmdyno-regression.yml](https://github.com/speak2jerome/llmdyno/blob/main/examples/ci/llmdyno-regression.yml)
is a GitHub Actions workflow to start from.

The pytest plugin is installed with LLMDyno:

```python
@pytest.mark.llmdyno(models="Qwen 27B 32k", benchmarks="t0_smoke_cli", min_score=80)
def test_smoke_still_passes(llmdyno_results):
    assert llmdyno_results.best()["correctness"] == 100
```

The marker runs the plan once per session for each set of arguments. The test fails when the best score is under
`min_score` or `min_correctness`. Use `--llmdyno-skip` on machines without Docker, and `--llmdyno-data DIR` to pick
the data folder.
