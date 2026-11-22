# Getting started

This page takes you from nothing to a first scored benchmark: what you need, how to install LLMDyno, what the first
setup downloads, and a first run from the dashboard, Python, the command line or TypeScript.

## What you need

| | Needed | Notes |
|---|---|---|
| Operating system | Windows 10/11, Linux, or macOS 13+ | x86-64 or ARM64, Apple Silicon included. |
| Python | 3.11 or later | Tested on 3.11, 3.12 and 3.13. Not needed separately if you use `npx llmdyno` with uv. |
| Docker | Docker Desktop on Windows and macOS; Docker Engine on Linux | Agents and graders run in containers. On Linux, add your user to the `docker` group. Give Docker Desktop at least 8 GB of memory. |
| GPU | Optional | For local models: NVIDIA, AMD, Intel or Apple Silicon. Cloud models need none. |
| Disk | A few GB to start | Sandbox and harness images and a llama.cpp build, plus the models you download. SWE-bench task images are 1 to 5 GB each. |
| API keys | For cloud models | One per provider you want to test. Keys stay on your machine. |

## Install

The usual way, in a virtual environment:

```bash
python -m venv llmdyno-env
llmdyno-env/bin/pip install llmdyno           # Windows: llmdyno-env\Scripts\pip install llmdyno
```

LLMDyno pins its own dependencies (FastAPI, SQLAlchemy, pydantic, …) to exact versions, so give it its own environment
rather than installing it into one you use for other work. Optional extras add charts, data frames, notebooks and
experiment tracking, for example `pip install "llmdyno[plot,data]"`; [Integrations](INTEGRATIONS.md#install) lists
them all.

Other ways to install it:

- **uv or pipx**, which keep it in its own environment for you: `uv tool install llmdyno` or `pipx install llmdyno`.
- **From Node 22 or later**: `npx llmdyno` runs it through an installed copy, uv or pipx, whichever it finds first (see
  [JavaScript and TypeScript](JAVASCRIPT.md#start-llmdyno)).
- **From a clone**, with a script that makes the virtual environment and starts LLMDyno:

    ```bash
    git clone https://github.com/speak2jerome/llmdyno.git
    cd llmdyno
    ./setup.sh                                          # Linux and macOS
    powershell -ExecutionPolicy Bypass -File setup.ps1  # Windows
    ```

    The scripts install LLMDyno in editable mode, so its data goes to `./data` inside the clone. `--no-start`
    (`-NoStart` on Windows) installs without starting it.

## Start it

```bash
llmdyno serve --open
```

This starts the web app at <http://127.0.0.1:8777> and opens it in your browser. `llmdyno` on its own does the same
without opening the browser; `--port` picks another port. LLMDyno listens only on your own machine unless you start it
with `--host` (see [Remote mode](REMOTE.md)).

The first time, a setup wizard opens:

1. **Welcome**, then **Scan my system**.
2. **Your system**: what LLMDyno found (CPU, GPU, memory, disks, Docker) and notes such as how much model fits in your
   VRAM.
3. **Dependencies**: Docker, the images and llama.cpp, each with a button to install or fix it. You can continue
   with items missing and finish later on the Setup page.
4. **Get started**: go to local models, cloud APIs, or the bundled sample results.

You can skip the wizard and reopen it later from the Overview page or Settings.

## Set up what benchmarks need

The **Setup** page (or `llmdyno doctor` in a terminal) shows what is in place. What a first benchmark needs:

| Item | Size and time | Needed for |
|---|---|---|
| Docker, running | | everything. "Start Docker Desktop" on the Setup page or `llmdyno start-docker` starts it on Windows and macOS. |
| Sandbox image | about 1.6 GB, 3 to 6 minutes | every run |
| Code-quality image | about 0.2 GB | the code-quality score (recommended) |
| At least one harness image | 1 to 4 minutes each | every run; Pi is the default |
| llama.cpp | one download | local models only; LLMDyno picks the build for your OS, CPU and GPU |

From a terminal or Python, one call installs whatever is missing and skips the rest:

```bash
llmdyno setup --harnesses pi opencode
```

```python
import llmdyno
llmdyno.setup(harnesses=["pi", "opencode"])
```

`--no-llama-cpp` skips llama.cpp for cloud-only use, and `--llama-cpp cuda-13` (or `metal`, `vulkan`, `cpu`, …) picks a
build. SWE-bench and the Aider polyglot benchmark need more: see
[Public benchmarks](https://github.com/speak2jerome/llmdyno#public-benchmarks-swe-bench-aider-polyglot-artificial-analysis).

## Look around first

**Settings → Sample results → Load sample results** (or `llmdyno.load_sample()`) loads the round 1 study that ships
with LLMDyno: 15 configurations, five tasks each, judged by two models. The Results page then has data, and you can
try every chart and option before running anything. Remove it again from the same place.

## Your first benchmark

The smoke test (`t0_smoke_cli`, suite `suite_smoke`) takes about two minutes per model. `suite_quick` adds a Flask
site and a bug-fixing task, about five minutes per local model.

### In the dashboard

1. **Add a model.**
    - Cloud: **Cloud providers**, pick the vendor, paste the API key, set a budget (the hard spend cap; $5 by default),
      then **Add & test**. Then **LLM profiles → New profile → Cloud model (API)**, choose the provider and model, and
      **Create profile**.
    - Local: **Models → Discover**, search for a model, open it, **Check fit** on a quant to see whether it fits your
      GPU, then **Download**. When it is in the **Library**, **Create profile**, set the context size, and
      **Save & test** to load it and measure speed, VRAM and tool calling (about 20 seconds).
2. **Plan the run.** **Runs → New plan**: tick the profiles, keep the Pi harness, pick the **Smoke test** or
   **Quick three** suite, and on **Review & start** read the preflight: estimated time and cost, and anything that
   blocks the plan (an image not built, a missing key) with a button to fix it. Then **Start**.
3. **Watch it.** The plan page fills a matrix of runs; click one to see the agent's transcript live, its files, the
   model requests and GPU use.
4. **Read the results.** **Results** ranks the configurations and has the charts. For code-quality scores from LLM
   judges, run **Judging** on the finished plan.

[The dashboard](DASHBOARD.md) describes every page in detail.

### From Python

```python
import llmdyno

gpt = llmdyno.cloud_model("openai", "gpt-6-luna", reasoning_effort="low", budget_usd=2)   # key from OPENAI_API_KEY
qwen = llmdyno.local_model("unsloth/Qwen3.8-27B-GGUF", quant="UD-Q3_K_XL", ctx=49152)    # downloads once

print(qwen.check()["verdict"])                 # fits, tight, spill, oom …
results = llmdyno.bench([gpt, qwen], benchmarks="suite_smoke", harnesses="pi")
print(results)
results.open()                                 # the same results in the dashboard
```

`bench()` checks the plan first and raises `PreflightError` with the reasons if something blocks it. Ctrl+C cancels it
cleanly. See [the library guide](LIBRARY.md).

### From the command line

```bash
llmdyno cloud-model openai gpt-6-luna --name "GPT-6 Luna low" --set reasoning_effort=low --budget-usd 2
llmdyno local-model --repo unsloth/Qwen3.8-27B-GGUF --quant UD-Q3_K_XL --name "Qwen 27B 48k" --set ctx=49152
llmdyno bench "GPT-6 Luna low" "Qwen 27B 48k" --benchmarks suite_smoke --harnesses pi
llmdyno results --view leaderboard
```

Every command takes `--json`. See [the command line reference](reference/cli.md).

### From TypeScript

With LLMDyno running (`npx llmdyno`), and the profiles above:

```ts
import { connect } from "llmdyno";

const dyno = await connect();
const results = await dyno.bench(["GPT-6 Luna low", "Qwen 27B 48k"], { benchmarks: "suite_smoke" });
console.table(results.leaderboard());
```

See [JavaScript and TypeScript](JAVASCRIPT.md).

## What it costs

- **Cloud models** cost what the provider charges for the tokens. The preflight estimates it per profile, the run
  proxy counts it exactly, and it stops a provider at its budget. In the round 1 study, all five tasks with GPT-6 Luna
  at low reasoning effort cost about 3 cents.
- **Local models** cost the electricity the GPU used, at the price in Settings ($0.15 per kWh by default).
- **Judging** costs what the judge models charge (about 25 000 tokens in and 4 000 out per review), capped by the
  judging job's budget ($1 by default).

## Upgrading

```bash
pip install -U llmdyno                       # or: uv tool upgrade llmdyno / pipx upgrade llmdyno
```

From a clone, `git pull` and run the setup script again. Your data folder is upgraded the first time the new version
opens it; a folder that a newer version has written is refused by an older one, so don't downgrade without a backup.
When a new version updates a harness, its image shows as not built on the Harnesses page until you build it again.

## Uninstalling

```bash
pip uninstall llmdyno
```

That leaves your data and Docker images in place. To remove them too:

- **The data folder** (`llmdyno data-dir` prints where it is, before you uninstall): models, runs, the database and
  saved keys. Delete it yourself if you no longer want any of it.
- **Docker images**: `docker image ls --filter "reference=llmdyno-*"` lists them (`llmdyno-sandbox`,
  `llmdyno-quality`, `llmdyno-harness-*`, `llmdyno-rt-*`, `llmdyno-polyglot`), and `docker image rm` removes them.
  SWE-bench task images keep their own names (`swebench/…`).
- **Docker volumes and network**: `docker volume ls --filter label=org.llmdyno.role` lists the harness runtime
  volumes, and `docker network rm llmdyno-internal` removes the sandbox network.
