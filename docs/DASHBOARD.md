# The dashboard

`llmdyno serve --open` starts the web app at <http://127.0.0.1:8777>. This page goes through it the way the sidebar
does. Everything here can also be done from [Python and the command line](LIBRARY.md).

## Around the app

- **Sidebar**: Overview and Setup; then **Configure** (Models, Cloud providers, LLM profiles, Harnesses, Benchmarks),
  **Evaluate** (Runs, Judging, Results) and **System** (Activity, Settings). A dot on Setup means something required is
  missing. Runs and Activity show how many plans and jobs are active. On windows narrower than 860 pixels the sidebar
  is hidden; Ctrl+Shift+X still works there.
- **Bottom of the sidebar**: the **Stop everything** button, a GPU meter (VRAM in use, turning amber above 75% and red
  above 90%), the theme switch (Light, Dark, System), a **Jobs** popover with the latest background jobs, and the
  version. If the browser and the server run different versions, the version tag says so.
- **"Reconnecting…"** appears when the live connection to the server drops. The app reconnects by itself and reloads
  what it shows.
- **The browser tab** shows what is happening ("Running · …", "Judging · …", "Quick test", "Plan finished"), so you can
  follow a benchmark from another tab. The icon is the mascot in its current state.
- **The mascot** sprints while a benchmark runs, jogs while a model warms up, sits on a podium while judges review,
  celebrates when a plan finishes, and turns red after a stop. It is still when your system asks for reduced motion.
- **Messages** appear at the bottom right and fade after a few seconds; errors stay longer. Dangerous actions ask first.
- **Keyboard**: Ctrl+Shift+X opens the stop dialog anywhere (Ctrl on a Mac too). Escape closes dialogs, drawers and
  menus. Enter confirms the focused dialog. Arrow keys move through menus.
- **Theme in a link**: add `?theme=dark` or `?theme=light` to any address to force a theme for that page load.

## Overview

Your setup, recent runs and what to do next.

- The mascot with a status line and a button for the moment: "Start a benchmark", "Watch it live", "Open judging" or
  "See results".
- Cards for the CPU (instruction-set badges such as AVX2 or NEON), the GPU (VRAM, free VRAM, driver; unified memory on
  Apple Silicon), memory and disks.
- **Getting started**: five steps with a progress bar (install the requirements, add a model or provider, create a
  profile, build a harness, run a plan), each linking where it is done.
- **Inventory**: local models, cloud providers, profiles and harnesses ready.
- **Activity** (the latest jobs) and **Recent plans**, with status, run count, cloud spend and progress. With no plans
  yet, "Explore sample results" loads the bundled study.
- **Setup wizard** reopens the first-run wizard; **New benchmark plan** starts one.

## Setup

What LLMDyno needs and what it found. **Re-scan** checks again; **Clean up containers** removes containers left by
crashed runs.

- **System notes**: how much model fits in your VRAM, the Windows spill warning, Apple Silicon's GPU memory limit and
  how to raise it, ARM and emulation notes, a CPU without AVX2, and Docker not running.
- **Core** (needed for every benchmark):
    - **Docker**: "Start Docker Desktop"; on Windows "Install Docker Desktop (winget)", on macOS and Linux a copyable
      install command. When Docker Desktop fails to start because of stale socket folders, "Fix Docker Desktop
      start-up" moves them aside (images and settings are untouched); avoid Docker's "Reset to factory defaults".
    - **Docker memory**: at least 8 GB is recommended, with how to raise the limit.
    - **Docker on ARM64**: Rosetta or QEMU for x86-64 images (SWE-bench).
    - **Sandbox image** (about 1.6 GB, 3 to 6 minutes) and **Code-quality image** (about 0.2 GB): "Build image".
    - **Agent harnesses**: "Build Pi", or "Choose harnesses".
- **Local models** (needed only for models on this machine):
    - **NVIDIA driver**: 580 or newer for the CUDA 13 build; older drivers get the CUDA 12 build.
    - **llama.cpp**: pick a build (the best one for your hardware is first), "Download and install", or "Use an
      existing folder" with your own build.
    - **Disk space for models** (at least 30 GB recommended) and the **Hugging Face token** for gated models.
    - **GPU memory limit** on Apple Silicon, with the command that raises it.
- **Public benchmarks**: install the SWE-bench harness and import tasks; build the polyglot toolchain image.
- **Details**: a table of GPUs and the software versions found.

Every action runs as a job, with its log on the page.

## Models

Local GGUF models. Tabs: **Library**, **Discover** and **Downloads**.

- **Library**: your models with quant, architecture, parameters, size, trained context, type (dense, MoE, sliding
  window, hybrid) and whether the chat template supports tools. **Create profile** starts a profile from a model. The
  menu has **Details** (memory by context size, tensor types), **Open on Hugging Face** and **Remove**, which can also
  delete the file from disk.
- **Import folder** registers the GGUF files in a folder where they are, without copying. Split files are grouped and
  vision projectors skipped.
- **Discover**: search Hugging Face, or start from the models recommended for your GPU. A repository shows its quants
  with a first guess at the fit ("likely fits", "tight", "too big for VRAM"). **Check fit** reads only the file's
  header and gives the exact verdict for your machine before you download. **Download** starts at once and resumes
  after interruptions. Gated models need a Hugging Face token (Settings) and the model's terms accepted on
  huggingface.co.
- **Downloads**: progress and speed, **Pause** and **Resume**, and deleting a paused partial file.

Fit verdicts: **Fits in VRAM**; **Tight fit** (under about 600 MiB to spare); **Spills to RAM** (Windows moves the
overflow into system memory and the model runs several times slower); **Out of memory**; **CPU only**.

## Cloud providers

The API accounts LLMDyno can use. Keys are encrypted with DPAPI on Windows and kept in a file only you can read on
Linux and macOS; they only ever reach the per-run proxy.

- **Add provider** shows the vendors: OpenAI, Anthropic, Google Gemini, DeepSeek, Moonshot (Kimi), Z.ai (GLM),
  Alibaba Qwen, MiniMax, xAI, Mistral, OpenRouter, Groq, Together AI, Fireworks AI, Cerebras, a LiteLLM proxy, or any
  OpenAI-compatible server ("Custom"). Give it a key and a **Budget**: a hard cap on what LLMDyno may spend with this
  provider, $5 by default. Judging and quick tests count toward it. For a server on your own machine, use
  `host.docker.internal` instead of `localhost` in the base URL, because sandboxes reach it through Docker.
- Each provider card shows its API style, the key's last characters, the spend bar ("$x of $y", amber above 70%, red
  above 90%), and **Test** (checks the key and lists models with the latency), **Models**, and **New profile**.
- The menu has **Edit**, **Add / Replace API key** (never shown again after saving), **Remove API key**, **Reset spend
  counter** (the provider still bills what was used) and **Delete provider**.

## LLM profiles

A profile is a model plus the exact settings it is benchmarked with. The page groups them into Local and Cloud; the
sample's profiles are listed separately when it is loaded. Each card shows the key settings, the last memory check and
the last quick test (speed, whether tool calls worked, any spill). The menu has **Edit**, **Run quick test**,
**Duplicate**, **Export JSON** (no keys) and **Delete** (results of past runs are kept). **Import** reads an exported
profile; the same model or provider must exist here.

### The profile editor

**New profile** offers a local (llama.cpp) or cloud (API) profile.

- **Local settings**, with the defaults a new profile gets:
    - **Context & KV cache**: context window (64k, at most the model's trained context), K and V cache types (q8_0),
      flash attention (On), and the full-size sliding-window cache for models that have one.
    - **GPU offload**: layers on the GPU (all), MoE expert layers on the CPU, llama.cpp's own auto-fit (off), and a
      safety margin (1024 MiB).
    - **Performance**: CPU threads, parallel slots (1), batch and micro-batch sizes, mlock, mmap.
    - **Sampling**: temperature, top-p, top-k, min-p, repeat and presence penalty, empty meaning the model's default;
      **Use model's recommended** fills them in.
    - **Reasoning & output**: thinking mode (Auto, On, Off), reasoning budget, and the output limit per turn (16384).
    - **Advanced**: extra llama-server arguments and chat-template options.
- **Memory fit** (local): a live projection of GPU memory (weights, KV cache, compute buffers, CUDA overhead, other
  apps), **Exact check** (llama.cpp's own dry run, about 2 seconds), a chart of memory by context size, and warnings,
  most with a one-click fix: spill or out of memory ("Use q8_0 KV cache", "Reduce context", "Offload experts to the
  CPU"), tight headroom, context above the training length or below what the benchmarks need, a quantized V cache
  without flash attention, very low-bit quants, a chat template without tool support, too small an output limit for a
  thinking model, and more.
- **Cloud settings**: context window, output limit, reasoning effort (None to Max), temperature and API style.
  **Pricing** per million tokens for input, cached input and output, with **Look up price** (OpenRouter's catalog).
  **Cost estimate** shows what each built-in benchmark would cost.
- **Save & test** saves and runs the **quick test**: for a local model it loads the model and measures load time, real
  VRAM, any spill, decode and prefill speed and whether tool calls work (about 20 seconds); for a cloud model it sends
  two short requests (a fraction of a cent).

## Harnesses

The agent programs. Each card shows the harness's status (image ready, not built, building, failed), the APIs it
speaks, whether it resumes its session across stages, and whether it uses native tool calls. **Build** builds its image
(1 to 4 minutes); **Build all missing** builds every built-in one. The drawer has an overview (strengths, caveats, how
LLMDyno runs it), the generated config per API style, and the Dockerfile. **Custom harness** adds your own; see
[Adding a harness](HARNESSES.md).

## Benchmarks

The tasks. Filter by category or search; each card shows the difficulty, stages, context needed, typical time and
languages. The drawer shows the task (prompts per stage, time limit), the files (starting workspace, files added later,
the reference solution) and the grading (hidden tests, checks, probes, the environment image).

- **Create benchmark** opens the editor; **More → Duplicate to edit** copies any benchmark, built-in ones included.
  See [Writing a benchmark](BENCHMARKS.md).
- **Validate grader** checks that the starter fails and the reference passes.
- **Export as zip**, **Import zip** and **Delete** (for your own and imported ones).
- **Suites**: the built-in suites (Round 1, Smoke test, Quick three, Web apps) and yours. **New suite** makes one.
- **Import SWE-bench / polyglot**: SWE-bench Verified (500 tasks), Lite (300) or Verified mini (50, a good first run),
  with how many to import; or the Aider polyglot exercises by language. The dialog says what each needs (the SWE-bench
  harness, the polyglot toolchain image) and what it costs in disk space and time.

## Runs

Every plan with its status, progress, duration and cloud spend. **New plan** opens the plan builder:

1. **Profiles**: any of yours, each with its fit verdict and quick-test result.
2. **Harnesses**: Pi is ticked by default. A compatibility grid shows which harness works with which profile;
   a harness that hasn't been built is flagged with a button to build it.
3. **Benchmarks**: suites and single benchmarks.
4. **Options**: the name, iterations (3 or more give confidence intervals), code-quality analysis, cloud runs in
   parallel, a budget for this plan, a time-limit multiplier, the agent's memory limit (12 GB), whether to allow
   profiles that spill out of VRAM, and whether to start judging when the plan finishes.
5. **Review & start**: the preflight. It estimates the time and the cloud cost per profile, lists what **blocks** the
   plan (Docker not running, an image not built, a model not downloaded, no API key) with buttons to fix it, and
   **warnings** (no prices set, an estimate above the remaining budget, a context below what a benchmark needs,
   images to pull, emulation on ARM). Serious memory risks need a tick: "I understand: run anyway and flag the affected
   results". **Start** then queues the runs.

Local runs take the GPU one model at a time; cloud runs go in parallel. Just before each local model loads, LLMDyno
checks free VRAM again and fails the run instead of letting it spill, unless the plan allows spills.

### A plan

- **Pause** (runs in progress finish), **Resume**, **Cancel** (running agents stop, finished results are kept),
  **Retry failed / cancelled**, **Rename** and **Delete** (removes its runs, files and reviews for good).
- **Judge** and **Results** jump to those pages for this plan; **SWE-bench predictions** downloads the patches in the
  official format.
- Progress, time elapsed and left, outcomes, and spend (API cost against the cap, GPU electricity).
- A live GPU chart, the matrix (one dot per run, coloured by status or score), and a table of every run.

### A run

The run page shows the profile, benchmark, harness and stage, with **Stop**, **Re-grade** (grade the finished
workspace again without re-running the agent), **Retry** and **Workspace .zip**. A banner warns when VRAM spilled into
system memory during the run. Tabs:

- **Transcript**: the system prompt, the prompt, thinking, replies and tool calls with their results, live while it
  runs. Filter to messages or tool calls.
- **Files**: the workspace and the agent's home folder (its config and sessions).
- **Grading**: hidden tests and checks, the score after each stage, and the agent's final message.
- **Code quality**: static analysis, robustness probes, lint and security findings.
- **Reviews**: each judge's scores and comments.
- **Requests**: every model request with tokens, cache hits, context use, time to first token, speed and cost.
- **GPU** (local runs): VRAM, shared memory (spill), power and utilisation over time.
- **Logs**: the harness's output per stage and the llama-server log.
- **Details**: the profile as it was run, and the harness and model.

## Judging

Blind code review of finished runs by LLM judges.

1. **What to review**: pick plans; "Skip runs a judge has already reviewed" is on by default.
2. **Judges**: any of your profiles, local or cloud. A judge from the same vendor as a model under test is marked.
   Two judges from different vendors are recommended, so LLMDyno can measure how much they agree.
3. **Rubric**: eight dimensions by default (readability, structure, idiomatic code, robustness, security, tests,
   simplicity, completeness), each editable, plus guidance for the judge.
4. **Limits**: a budget for the judging job ($1), parallel reviews for cloud judges (4), the output limit, and whether
   judges see the static-analysis summary.

The footer estimates the cost (about 25 000 tokens in and 4 000 out per review). **Start judging** starts it; the job
log streams on the right. Below it, **Judge agreement** (correlation and mean gap between judges, and any preference
for their own vendor's models) and the list of reviews, which can be deleted per judge.

## Results

The scored comparison of finished runs. A link with `?plans=id,id` opens it filtered to those plans.

- **Filters**: plans, local or cloud, harnesses and benchmarks. When configurations ran different benchmarks, a
  warning offers to keep only the shared ones.
- **Scoring weights**: presets (Balanced, Correctness only, Code quality focus, Speed matters), sliders for the four
  parts of the final score and the three parts of code quality, the pass threshold for pass@k (80% of hidden tests),
  and the efficiency reference (the fastest local run, or the fastest run). The ranking updates as you move them.
  **Save as default** keeps the weights.
- **Highlights**: the top configuration, the best local one, the best value (points per dollar), the fastest strong
  one, the most consistent one (with two or more iterations) and the judges' agreement (with two judges).
- **Leaderboard**: as a chart (stacked points with 95% confidence intervals) or a table with every score, pass@k,
  time, tokens, speed, cost and lines of code. A "spill" badge marks configurations with runs that spilled.
- **Public benchmarks**: SWE-bench resolved and polyglot solved rates, when such runs exist.
- **Public reference**: with an Artificial Analysis key (Settings), each profile's model with its Intelligence Index,
  output speed, time to first token and price, next to what LLMDyno measured. Correct a wrong match from the list.
- **Charts**: a per-benchmark heatmap, radar profiles, a trade-off explorer (any two measures, with the Pareto front),
  consistency across iterations, tokens and cost, the harness comparison and the rubric heatmap. Clicking a chart
  filters the runs table at the bottom.
- **Compare** puts two configurations side by side. **Export**: configurations, per-benchmark rows or all runs as CSV,
  all runs as JSON, or print the page to PDF.

## Activity

Every background job (downloads, image builds, installs, plans, judging, quick tests, validation, imports) with its
status, progress and duration. Click one for its log and, while it runs, **Cancel**. **Clear finished** removes
finished jobs from the list.

## Settings

- **Folders**: where models and runs are stored, and the data folder and database in use.
- **Runs**: electricity price (for the cost of local runs), the default number of cloud runs in parallel, the VRAM
  safety margin for exact checks, and the llama-server port.
- **Appearance**: Light, Dark or System.
- **Hugging Face token**, for gated models and higher download limits.
- **Artificial Analysis reference**: a free API key, and when the data was last fetched.
- **Sample results**: load or remove the bundled round 1 study.
- **About**: the version, the mascot's states, and the licence.

[Configuration](CONFIGURATION.md) describes every setting.

## Stop everything

The red **Stop everything** button (or Ctrl+Shift+X) first shows what is running: plans, runs, jobs, containers and
llama-server. **Stop everything** then cancels every job and plan, removes the proxy containers first (cutting agents
off from paid APIs at once), then every other LLMDyno container, and stops llama-server. Paused plans and finished
results are kept, downloads pause and can be resumed, and requests already sent to a provider may still be billed.

## Opening it from another machine

When the server was started with `llmdyno serve --host 0.0.0.0`, the dashboard on another machine asks for the access
token once ("Connect to this LLMDyno") and keeps it in that browser. See [Remote mode](REMOTE.md).
