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
```

## Benchmarks

```python
llmdyno.list_benchmarks()                       # built-in, your own and imported tasks
llmdyno.list_benchmarks(category="SWE-bench")
llmdyno.list_suites()                           # suite_quick, suite_round1, imported suites, your own

llmdyno.import_swebench("verified_mini")        # 50 SWE-bench Verified tasks (or "lite", "verified", limit=…)
llmdyno.import_polyglot(["python", "rust"])     # Aider polyglot exercises
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

In Jupyter, a `Results` object renders as a table.

## Code review by LLM judges

```python
judge = llmdyno.cloud_model("anthropic", "claude-sonnet-5-5", name="Judge: Sonnet")
results = llmdyno.review(plan, judges=[judge], budget_usd=0.50)
```

Blind, shuffled review with LLMDyno's rubric; the scores feed the code-quality part of the final score.

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
| `cloud_model(vendor, model, ...)`, `local_model(repo, quant=..., ...)`, `profile(name)`, `list_profiles()` | `Profile` |
| `list_benchmarks()`, `list_suites()`, `import_swebench()`, `import_polyglot()` | lists and dicts |
| `preflight(models, benchmarks, harnesses)` | dict |
| `bench(models, benchmarks, harnesses, ...)` | `Results` (or `Plan` with `wait=False`) |
| `list_plans()`, `plan(id)` | `Plan` |
| `results(plans, weights...)`, `review(plans, judges)` | `Results` |
| `watch(plan or run or job, transcript=False)` | iterator of `Event` |
| `job(id)` | `Job` (`.status`, `.progress`, `.log`, `.wait()`, `.cancel()`) |
| `serve()` | dashboard URL |
| `llmdyno.aio.<any function>`, `aio.watch()`, `aio.call(fn, ...)` | the same, awaitable |

Every object (`Profile`, `Plan`, `Job`, …) gives its raw data with `obj["field"]`, `obj.get("field")` and
`obj.to_dict()`, and `obj.refresh()` fetches it again.

## Library and web app parity

Everything the dashboard can do is being brought to the library. `tests/test_parity.py` checks every web API route
against the library: each one has a library call (marked with `@covers` in `llmdyno/sdk`) or is listed as pending in
its area's module, and 0.4.0 ships with no pending routes. `python -c "from llmdyno.sdk import parity; print(parity.report())"`
shows where it stands.
