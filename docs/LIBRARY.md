# Using LLMDyno from Python

Everything the app does is also a Python API. `import llmdyno`, describe the models you want to compare, call
`bench()`, and you get scored results back. It is the same engine, data folder and database as the web app, so a plan
you start from a script shows up in the dashboard, and profiles you made in the UI can be used from code.

```python
import llmdyno

gpt = llmdyno.cloud_model("openai", "gpt-6-luna", reasoning_effort="low", budget_usd=2)
qwen = llmdyno.local_model("unsloth/Qwen3.8-27B-GGUF", quant="UD-Q3_K_XL", ctx=49152)

results = llmdyno.bench([gpt, qwen], benchmarks="suite_quick", harnesses="pi")
print(results)
```

A real run, one local model on the smoke-test task (RTX 5080):

```python
qwen = llmdyno.profile("Qwen3.8 27B Q3_K_XL 48k")
results = llmdyno.bench(qwen, benchmarks="t0_smoke_cli", harnesses="pi")
print(results)
```

```
Plan: 1 run(s), about 1 min
  done      Smoke test: word-frequency CLI · Qwen3.8 27B Q3_K_XL 48k · Pi: correctness 1.00 in 0.5 min · $0.0003
Plan done: {'done': 1}
#  Profile                  Harness  Final  Correct  Quality  Runs  Time     Cost
-  -----------------------  -------  -----  -------  -------  ----  -------  -------
1  Qwen3.8 27B Q3_K_XL 48k  Pi       95.5   100.0    81.8     1     0.5 min  $0.0003
```

The cost of a local run is the GPU's electricity at your rate (Settings); cloud runs are priced per token.

## Install

```bash
pip install llmdyno                      # add [pandas] for Results.to_pandas(): pip install "llmdyno[pandas]"
```

Requirements are the same as for the app: Python 3.11+, Docker running (agents work in sandboxes), and for local models
a GPU that llama.cpp supports. `import llmdyno` itself is instant and starts nothing; the first call opens the data
folder.

## First-time setup

```python
import llmdyno

print(llmdyno.doctor())          # what is installed and what is missing (same checks as the Setup page)
llmdyno.setup(harnesses=["pi", "opencode"])   # sandbox + harness images, llama.cpp for this machine
```

`setup()` only does what is missing. It downloads several gigabytes the first time (Docker images, a llama.cpp build).
Add `swebench=True` for the official SWE-bench harness and `polyglot=True` for the Aider polyglot toolchain image.

## Models

A *profile* is a model plus the exact settings it is benchmarked with. Both constructors are idempotent: calling them
again with the same name returns the same profile (updated with any new settings) instead of creating a copy.

### Cloud

```python
claude = llmdyno.cloud_model("anthropic", "claude-sonnet-5-5", reasoning_effort="low")
grok = llmdyno.cloud_model("xai", "grok-5", api_key="...", budget_usd=1.50)
ollama = llmdyno.cloud_model("custom", "qwen3-coder:30b", base_url="http://host.docker.internal:11434/v1")
```

- **Vendors**: openai, anthropic, google, deepseek, moonshot, zai, qwen, minimax, xai, mistral, openrouter, groq,
  together, fireworks, cerebras, or `custom` for any OpenAI-compatible URL (Ollama, LM Studio, vLLM, a gateway).
- **Keys**: `api_key=`, or the usual environment variable (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
  `DEEPSEEK_API_KEY`, `XAI_API_KEY`, `OPENROUTER_API_KEY`, …), or a key you saved in the app. Keys are stored encrypted
  in the data folder and only ever reach LLMDyno's per-run proxy, never an agent sandbox.
- **Spend**: `budget_usd` is a hard cap for that provider (new providers default to $5). `bench(budget_usd=…)` adds a
  cap for one plan. The proxy refuses requests once a cap is reached.
- **Prices**: `pricing="auto"` (the default) looks the model up in OpenRouter's public catalog; pass
  `{"input": 3.0, "output": 15.0, "cached": 0.3}` (USD per million tokens) to set them yourself.
- **Settings**: `ctx`, `max_output_tokens`, `reasoning_effort` (minimal, low, medium, high, max), `temperature`, `top_p`,
  `api_style` (openai-chat, openai-responses, anthropic), `extra_body`.

### Local (llama.cpp)

```python
# from Hugging Face: downloads once (resumable, checksum-verified), then reuses the file
qwen = llmdyno.local_model("unsloth/Qwen3.8-27B-GGUF", quant="UD-Q3_K_XL", ctx=49152, kv_cache="q8_0")

# a file you already have: registered where it is, nothing is copied
gemma = llmdyno.local_model(path="D:/models/gemma-4-12b-Q8_0.gguf", ctx=65536)

print(qwen.check())      # memory fit: verdict (fits, tight, spill, oom, cpu), projected VRAM, warnings, fixes
qwen.test()              # 20-second load + speed + tool-calling test
qwen.update(ctx=32768)   # change a setting
```

Settings: `ctx`, `cache_k` / `cache_v` (or `kv_cache` for both), `gpu_layers`, `n_cpu_moe`, `flash_attn`, `thinking`,
`max_output_tokens`, `reasoning_budget`, sampling (`temperature`, `top_p`, `top_k`, `min_p`, …) and the rest of
the profile editor's fields. Unknown names raise `TypeError` rather than being ignored. `local_model()` warns when the
profile is projected not to fit in VRAM.

### Existing profiles

```python
llmdyno.list_profiles()                 # everything, or list_profiles("local") / list_profiles("cloud")
qwen = llmdyno.profile("Qwen3.8 27B Q3_K_XL 48k")   # by name (case-insensitive) or id

qwen.update(name="Qwen 27B 48k", notes="baseline", tags=["round2"], ctx=49152)
fast = qwen.duplicate("Qwen 27B 32k", ctx=32768)    # a copy with changed settings
qwen.export("qwen.profile.json")                    # share it; never contains keys
llmdyno.import_profile("qwen.profile.json")         # on another machine (the model must be downloaded there)
llmdyno.profile_defaults("local", model="Qwen3.8-27B-UD-Q3_K_XL")   # what a new profile starts from
```

### Finding and downloading models

```python
llmdyno.search_models("qwen coder")                 # Hugging Face GGUF repositories
info = llmdyno.repo_info("unsloth/Qwen3.8-27B-GGUF")   # quants, sizes, a fit hint for your GPU, license, gated
fit = llmdyno.estimate("unsloth/Qwen3.8-27B-GGUF", "UD-Q3_K_XL", ctx=65536, kv_cache="q8_0")
fit["check"]["verdict"], fit["contexts"]            # will it fit, before downloading (reads the GGUF header)
m = llmdyno.download_model("unsloth/Qwen3.8-27B-GGUF", "UD-Q3_K_XL")   # or wait=False for the Job
llmdyno.recommended_models()

llmdyno.list_models(status="ready")
m = llmdyno.model("Qwen3.8-27B-UD-Q3_K_XL")          # by id, name or "repo:quant"
m.contexts()                                        # memory at each context size on this machine
m.profile(ctx=32768)                                # a profile from it
m.pause(); m.resume(); m.delete(files=True)
llmdyno.import_models("D:/models")                  # register every GGUF in a folder, no copy
```

### Providers

`cloud_model()` creates providers for you; these manage them directly.

```python
p = llmdyno.provider("anthropic")                   # by id, name, or vendor when you have one of it
p.test()                                            # checks the key and lists models: {"ok", "models", "latency_ms"}
p.models()
p.spent_usd, p.budget_usd
p.update(budget_usd=10); p.reset_spend()
p.set_key("sk-..."); p.remove_key(); p.delete()
llmdyno.add_provider("custom", base_url="http://localhost:8000/v1", name="vLLM box")
llmdyno.list_providers(); llmdyno.vendors()
llmdyno.lookup_price("anthropic", "claude-sonnet-5-5")   # per 1M tokens, from OpenRouter's catalog
```

## Benchmarks

```python
llmdyno.list_benchmarks()                       # built-in, your own and imported tasks
llmdyno.list_benchmarks(category="SWE-bench")
llmdyno.list_suites()                           # suite_quick, suite_round1, imported suites, your own

llmdyno.import_swebench("verified_mini")        # 50 SWE-bench Verified tasks (or "lite", "verified", limit=…)
llmdyno.import_polyglot(["python", "rust"])     # Aider polyglot exercises
llmdyno.import_catalog()                        # what can be imported and what is ready
llmdyno.install_swebench_harness(); llmdyno.build_polyglot_image(); llmdyno.remove_imported("polyglot")
```

Your own benchmarks use the same spec as the benchmark editor (see [BENCHMARKS.md](BENCHMARKS.md)):

```python
b = llmdyno.benchmark("t0_smoke_cli")           # everything about one benchmark: prompts, stages, grader
mine = b.duplicate("my_smoke")                  # built-in ones are read-only; copies are yours
spec = mine.spec(); spec["stages"][0]["prompt"] += " Use type hints."
mine.update(spec)
mine.validate()                                 # starter must fail, reference must pass (needs Docker)
mine.export("my_smoke.zip"); llmdyno.import_benchmark("my_smoke.zip")
llmdyno.create_benchmark({...})                 # from scratch

s = llmdyno.create_suite("My suite", ["my_smoke", "t5_bugfix_semver"])
s.update(benchmarks=["my_smoke"]); s.delete()
```

### Harnesses

```python
llmdyno.list_harnesses(ready=True)              # images built
pi = llmdyno.harness("pi")
pi.build(); pi.remove_image()
pi.dockerfile(); pi.preview("anthropic")        # exactly what a run executes
pi.runtime("linux/arm64"); pi.build_runtime("linux/arm64")   # portable runtime for SWE-bench-style images
llmdyno.add_harness("my-agent.json", build=True)   # your own agent (see HARNESSES.md); .update(), .delete()
llmdyno.harness_schema()
```

## Running

```python
results = llmdyno.bench(
    [gpt, qwen],                          # profiles, or profile names
    benchmarks=["suite_quick", "swe_django__django_11099"],   # benchmark and suite ids
    harnesses=["pi", "opencode"],
    iterations=2,
    budget_usd=1.0,                       # cap for this plan's cloud spend
)
```

`bench()` checks the plan first (Docker, images, keys, memory fit, budgets) and raises `PreflightError` listing what
blocks it, before anything starts. Warnings rated danger (VRAM spill, out of memory) need `acknowledge_risks=True`.
`llmdyno.preflight(...)` returns the same report without running anything.

While it runs it prints each run as it finishes. Ctrl+C cancels the plan cleanly (finished runs are kept). With
`wait=False` you get a `Plan` back immediately:

```python
plan = llmdyno.bench([gpt, qwen], "suite_round1", wait=False)
plan.status            # queued, running, paused, done, …
plan.runs()            # every run with its status and scores
plan.pause(); plan.resume(); plan.cancel()
results = plan.wait()
plan.open()            # the live plan page in the dashboard
plan.retry()           # run the failed and cancelled runs again
plan.rename("Round 2"); plan.delete(files=True)
```

### Runs

```python
run = plan.get_runs()[0]                  # or llmdyno.run(run_id); Results.runs() rows carry run ids
t = run.transcript()
t.turns()                # one entry per model call: messages sent, reply blocks, finish, tokens, timings, cost
t.tool_calls()           # every tool call with its arguments and what the tool returned
t.thinking(); t.final_text(); t.usage(); t.to_pandas()
run.files(); run.read_file("app.py"); run.download("workspace.zip")
run.log(stage=1); run.log(stage=1, stream="stderr"); run.server_log()
run.requests()           # each model request through the proxy
run.gpu()                # GPU telemetry during the run
run.retry(); run.regrade(); run.cancel()
```

Local models take the GPU one at a time; cloud runs go in parallel (`cloud_concurrency=`). The process stays alive
until a started plan finishes or is cancelled.

### Following a plan live

`watch()` yields the same events the dashboard shows, until the plan (or run, or job) stops:

```python
plan = llmdyno.bench(qwen, "suite_quick", wait=False)
for ev in llmdyno.watch(plan):
    if ev.kind == "run" and ev.finished:
        print(ev.data["benchmark_id"], ev.status, ev.data["correctness"])
    elif ev.kind == "gpu":
        print("VRAM", ev.data.get("vram_used_mib"))
```

Event kinds: `run` (a run changed state), `plan`, `gpu` (telemetry samples while a local model runs), `job` and
`log` (background jobs such as downloads), and with `watch(plan, transcript=True)` also `transcript` (each agent
event) and `proxy` (each model request with tokens, cost and latency). Or pass a callback to the blocking calls:
`llmdyno.bench(..., on_event=print)`.

Events arrive live for work started in the same Python process. Work running elsewhere, such as a plan started from
the dashboard of a separate `llmdyno serve`, is followed by polling: run and plan changes only, every `poll_s` seconds.

### Async code and notebooks

`llmdyno.aio` has every function as a coroutine (each runs in a worker thread), plus an async `watch`:

```python
from llmdyno import aio

plan = await aio.bench(qwen, "suite_quick", wait=False)
async for ev in aio.watch(plan):
    ...
results = await aio.call(plan.results)      # any blocking method, in a thread
```

## Results

```python
print(results)                  # leaderboard, plus SWE-bench / polyglot rates when there are such runs
results.leaderboard()           # one dict per profile × harness, best first (scores 0-100)
results.runs()                  # one dict per run
results.public()                # SWE-bench resolved % and polyglot solved % per configuration
results.best()

results.to_pandas()             # DataFrame (pip install pandas); to_pandas("runs") for every run
results.to_csv("leaderboard.csv")
results.to_json("results.json")
results.open()                  # the full dashboard: charts, transcripts, workspaces

llmdyno.results(plans=[...], correctness=100, quality=0, instruction_following=0, efficiency=0)   # re-weight
plan.swebench_predictions("preds.jsonl")   # SWE-bench patches in the official predictions format
```

Every option and view of the Results page:

```python
r = llmdyno.results(plan, benchmarks=["t5_bugfix_semver"], pass_threshold=1.0,
                    quality_weights={"static": 20, "probes": 30, "review": 50}, efficiency_ref="all")
r.cells()          # profile × harness × benchmark, with spread over iterations (the heatmap)
r.rubric()         # average judge score per rubric dimension
r.agreement()      # how much the judges agree, and self-preference
r.reviews()
r.reference()      # Artificial Analysis coding index next to each score
r.export("runs.csv", level="runs")          # the page's export: level runs / cells / configs, fmt csv / json
llmdyno.save_weights(correctness=60, quality=20)   # the defaults results() and the page start from
llmdyno.load_sample(); llmdyno.unload_sample()     # the bundled round-1 results, to explore without running anything
```

In Jupyter, a `Results` object renders as a table.

## Code review by LLM judges

```python
judge = llmdyno.cloud_model("anthropic", "claude-sonnet-5-5", name="Judge: Sonnet")
results = llmdyno.review(plan, judges=[judge], budget_usd=0.50)
```

Blind, shuffled review with LLMDyno's rubric; the scores feed the code-quality part of the final score.

```python
llmdyno.judge_defaults()                         # the rubric, guidance and default limits
llmdyno.review(judges=[judge], runs=[run_id], rubric=[...], guidance="Be strict about tests",
               include_static=True, skip_reviewed=False)
llmdyno.reviews(plan=plan); llmdyno.reviews(run=run_id)
llmdyno.delete_reviews(judge, plan=plan)
```

## Artificial Analysis reference

```python
llmdyno.set_aa_key("...")        # free key from artificialanalysis.ai
llmdyno.refresh_aa()             # cached for a day; the free tier allows 100 requests a day
llmdyno.aa_reference()           # matches per profile and the model list
llmdyno.set_aa_match(qwen, "qwen3-8-27b")   # pick the match by hand (None: back to automatic)
```

## Settings, system and jobs

```python
s = llmdyno.settings()
s.cloud_concurrency, s.weights, s.data_dir
s.update(cloud_concurrency=4, electricity_usd_per_kwh=0.30)
llmdyno.set_hf_token("hf_..."); llmdyno.remove_hf_token()

llmdyno.specs(); llmdyno.gpu_usage()
llmdyno.list_jobs(active=True); llmdyno.job(job_id).wait(); llmdyno.clear_jobs()
llmdyno.active_work(); llmdyno.panic()           # the red button: stop everything
llmdyno.cleanup()                                # remove containers left by crashed runs
llmdyno.start_docker(); llmdyno.repair_docker(); llmdyno.use_llama_cpp("D:/llama.cpp")
```

## Command line

Every call above is also a command, generated from the library so the two always match. Function names become
commands with dashes, methods become `llmdyno <object> <method> ID`, and `--json` gives machine-readable output:

```bash
llmdyno list-models --status ready
llmdyno estimate unsloth/Qwen3.8-27B-GGUF UD-Q3_K_XL --set ctx=65536 --set kv_cache=q8_0
llmdyno bench "Qwen 27B 32k" --benchmarks suite_quick --harnesses pi opencode
llmdyno watch PLAN_ID
llmdyno results --plans PLAN_ID --view cells --json
llmdyno run transcript RUN_ID --view tool-calls
llmdyno plan retry PLAN_ID
llmdyno --help; llmdyno run --help; llmdyno bench --help
```

`llmdyno` alone starts the web app, as before. Errors print to stderr and exit with code 1. Two commands have no
Python twin: `llmdyno ci` (fail a build on a score drop, see [INTEGRATIONS.md](INTEGRATIONS.md#ci-and-pytest)) and
`llmdyno token` (the access token for remote clients, see [REMOTE.md](REMOTE.md)).

## Integrations and remote mode

Data frames, charts, notebooks, MLflow, Weights & Biases, Langfuse, OpenTelemetry, LiteLLM, Ollama, the Hugging Face
Hub, your own LangGraph / OpenAI Agents SDK / smolagents / PydanticAI agent, Inspect AI and pytest: see
[INTEGRATIONS.md](INTEGRATIONS.md). To run LLMDyno on a GPU box and use it from your laptop, see
[REMOTE.md](REMOTE.md).

## The dashboard

```python
llmdyno.serve()                    # blocks; Ctrl+C stops it
llmdyno.serve(block=False)         # background thread, handy in notebooks
```

## Data folder

By default the library uses the same folder as the app: `LLMDYNO_DATA` if set, otherwise `./data` in a git checkout,
`%LOCALAPPDATA%\LLMDyno` on Windows, `~/Library/Application Support/LLMDyno` on macOS and `~/.local/share/llmdyno` on
Linux. To use another one:

```python
llmdyno.init("~/llm-benchmarks")
llmdyno.data_dir()
```

Running plans from a script and from the app at the same time on one machine is not supported: both would try to load
models onto the same GPU.

## Errors

The library and the web API share one error family (`llmdyno.errors`); each carries the HTTP status the API answers
with, so an error means the same thing from Python and over REST.

| Exception | When | HTTP |
|---|---|---|
| `llmdyno.PreflightError` | a plan cannot start; `.problems` lists why, `.report` has the full preflight | 409 |
| `llmdyno.NotFoundError` | no such profile, benchmark, plan, run, file or quant | 404 |
| `llmdyno.ConflictError` | a name or file is ambiguous, already in use, or in the wrong state | 409 |
| `llmdyno.InvalidError` | a request that cannot be valid as given (also a `ValueError`) | 400 |
| `llmdyno.ForbiddenError` | not allowed, such as editing a built-in benchmark | 403 |
| `llmdyno.RiskNotAcknowledgedError` | danger warnings need `acknowledge_risks=True` | 428 |
| `llmdyno.RateLimitError`, `UpstreamError` | an external service limited or failed the request | 429, 502 |
| `llmdyno.InsufficientStorageError` | not enough disk space, for example for a download | 507 |
| `llmdyno.LLMDynoError` | anything else LLMDyno refuses or fails to do (all of the above inherit from it) | 400 |
| `TypeError` | an unknown profile setting | |

## API at a glance

| Call | Returns |
|---|---|
| `init(data_dir=None)`, `data_dir()` | the data folder |
| `doctor()`, `setup(...)` | `Doctor` (list of checks with `.ok`, `.missing`) |
| `cloud_model(vendor, model, ...)`, `local_model(repo, quant=..., ...)`, `profile(name)`, `list_profiles()`, `import_profile(path)` | `Profile` |
| `profile_defaults(kind, model=)` | dict |
| `search_models(q)`, `repo_info(repo)`, `estimate(repo, quant, ...)`, `recommended_models()` | lists and dicts |
| `download_model(repo, quant)`, `model(name)`, `list_models()`, `import_models(folder)` | `Model` |
| `provider(name)`, `list_providers()`, `add_provider(vendor, ...)` | `Provider` |
| `vendors()`, `lookup_price(vendor, model)` | lists and dicts |
| `harness(id)`, `list_harnesses()`, `add_harness(manifest)` | `Harness` |
| `list_benchmarks()`, `list_suites()`, `import_catalog()` | lists and dicts |
| `benchmark(id)`, `create_benchmark(spec)`, `import_benchmark(zip)` | `Benchmark` |
| `suite(id)`, `create_suite(name, benchmarks)` | `Suite` |
| `import_swebench()`, `import_polyglot()`, `install_swebench_harness()`, `build_polyglot_image()`, `remove_imported(kind)` | job results |
| `preflight(models, benchmarks, harnesses)` | dict |
| `bench(models, benchmarks, harnesses, ...)` | `Results` (or `Plan` with `wait=False`) |
| `list_plans()`, `plan(id)` | `Plan` |
| `run(id)`, `plan.get_runs()` | `Run`; `run.transcript()` gives a `Transcript` |
| `results(plans, weights, benchmarks=, ...)`, `review(plans, judges, ...)` | `Results` |
| `judge_defaults()`, `reviews(plan=, run=)`, `delete_reviews(judge)` | dicts, lists, counts |
| `save_weights(...)`, `load_sample()`, `unload_sample()`, `sample_status()` | dicts |
| `aa_reference()`, `refresh_aa()`, `set_aa_key()`, `remove_aa_key()`, `set_aa_match(profile, slug)` | dicts |
| `settings()` | `Settings` (`.update(...)`); `set_hf_token()`, `remove_hf_token()` |
| `specs()`, `gpu_usage()`, `active_work()`, `panic()`, `cleanup()` | dicts, counts |
| `list_jobs()`, `job(id)`, `clear_jobs()` | `Job` (`.status`, `.progress`, `.log`, `.wait()`, `.cancel()`) |
| `start_docker()`, `repair_docker()`, `install_docker()`, `use_llama_cpp(path)` | messages |
| `watch(plan or run or job, transcript=False)` | iterator of `Event` |
| `python_harness("module:function", requirements=[...])` | `Harness` |
| `node_harness("agent.ts:run", packages=[...])` | `Harness` |
| `local_servers()`, `ollama_model()`, `openai_compatible()`, `litellm_model()` | lists, `Profile` |
| `compare_results(current, baseline)` | regression report |
| `inspect_task()`, `import_inspect_samples()` | Inspect `Task`, `Suite` |
| `load_results_from_hub(repo)` | `Results` |
| `connect(url, token)`, `disconnect()`, `connection()` | the backend in use |
| `serve()` | dashboard URL |
| `llmdyno.aio.<any function>`, `aio.watch()`, `aio.call(fn, ...)` | the same, awaitable |

Every object (`Profile`, `Plan`, `Job`, …) gives its raw data with `obj["field"]`, `obj.get("field")` and
`obj.to_dict()`, and `obj.refresh()` fetches it again.

## API stability

LLMDyno follows [Semantic Versioning](https://semver.org). Everything in `llmdyno.__all__` (and the methods of the
objects it returns) is the public API; modules and names that start with an underscore, and everything under
`llmdyno.services`, `llmdyno.api` and the engine packages, are internal.

- Until 1.0, a minor release (0.5 → 0.6) may change the public API; the CHANGELOG says what changed and how to adapt.
- From 1.0, a public name is only removed or changed incompatibly in a major release. It is deprecated first: it keeps
  working for at least one minor release and warns (`DeprecationWarning`) with what to use instead.
- Results stay comparable: a result records the LLMDyno version that computed its scores, and scoring changes are
  listed in the CHANGELOG.
- The web API follows the library: each route has a library call (`tests/test_parity.py`), so a route changes when its
  call does.

## Library and web app parity

Everything the dashboard can do, the library can do. `tests/test_parity.py` checks every web API route against the
library (each library call names the routes it covers with `@covers` in `llmdyno/sdk`), and `tests/test_cli.py` checks
that every library call has its command, so a new feature reaches the dashboard, Python and the command line together.
`python -c "from llmdyno.sdk import parity; print(parity.report())"` prints the map.
