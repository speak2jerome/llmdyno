# LLMDyno architecture

LLMDyno benchmarks LLMs as **coding agents**: a model profile drives an open-source agent harness inside an
offline Docker sandbox, hidden graders score the result, and the dashboard compares everything.

## Design goals

1. **Pull and run.** One bootstrap script, then everything happens in the browser. Only Docker is required besides
   Python, because agents run inside sandboxes.
2. **Fair comparisons.** Every profile × harness × benchmark × iteration runs in the same sandbox image, the same
   proxy measures tokens and speed, and the same graders and judges score it.
3. **Safe defaults.** Agent sandboxes have no internet. API keys never enter a sandbox: a per-run proxy injects them
   and enforces a hard spend cap.
4. **Honest hardware warnings.** Before you download or run anything, you get a memory projection for your GPU and
   warnings about OOM, spill into shared system RAM, CPU offload, and contexts that are too small for agentic work.

## Components

```
browser ── React + TS UI (Vite build, served by the backend)
   │  REST + one WebSocket (/ws, topic subscriptions)
   ▼
llmdyno (FastAPI, runs natively on the host: it needs the GPU, the disk and Docker)
   ├── system/      spec detection (CPU/ISA, RAM, GPUs/VRAM/driver, disk, Docker, WSL) and dependency checks/installers
   ├── hub/         Hugging Face search, remote GGUF header parsing (HTTP range), resumable downloads
   ├── memory.py    VRAM/RAM projection: estimator (pre-download) + llama-fit-params dry run (post-download) + warnings
   ├── inference/   llama.cpp release installer and llama-server lifecycle; external OpenAI-compatible endpoints
   ├── providers/   vendor catalog (OpenAI, Anthropic, Gemini, DeepSeek, Kimi, GLM, Qwen, MiniMax, xAI, Mistral,
   │                OpenRouter, Groq, Together, Fireworks, Cerebras, custom), key store, OpenRouter price lookup
   ├── harnesses/   data-driven harness manifests (Pi, OpenCode, Codex, Qwen Code, Aider, mini-swe-agent, …) and image builds
   ├── benchmarks/  built-in tasks, suites, custom benchmark creator and grader validation
   ├── runner/      plan scheduler (GPU-serial local runs, parallel cloud runs), sandbox driver, metrics
   ├── proxy/       stdlib logging proxy (runs in a container): token usage, speed, cost cap, transcript capture
   ├── quality/     static analysis image (ruff, radon, bandit, vulture, coverage) and probes
   ├── judge/       blind LLM review with user-chosen judges, agreement and self-preference stats
   └── scoring.py   configurable weights, iteration statistics (mean, sd, 95% CI, pass@k)
SQLite (data/llmdyno.db) — profiles, providers, plans, runs, reviews, jobs
data/runs/<plan>/<run>/ — workspace, proxy logs, transcript stream, grader output
```

### Why no Redis / Celery / Postgres here

An early prototype used Redis + Celery + Postgres. For a project that anyone clones, that is four extra services
to install and keep healthy. LLMDyno keeps the same pieces in-process: jobs are rows in SQLite run by a worker
pool, live events go through an in-memory pub/sub to WebSocket subscribers, and transcripts stream from files the
proxy appends to. Restarting the server marks running jobs as interrupted, and plans can resume.

## Run pipeline

```
plan = profiles × harnesses × benchmarks × iterations
  └─ scheduler groups local runs by profile (one llama-server load per profile) and runs cloud runs concurrently
       per run:
         1. copy the benchmark workspace template
         2. start/reuse the profile's proxy container  (internal network alias → upstream: llama-server or vendor)
         3. render the harness config (models.json, opencode.json, config.toml, env, …) pointing at the proxy
         4. docker run <harness image> on the internal network (no internet), per stage, with a timeout
         5. grade in a fresh offline container (hidden tests copied in only after the agent is gone)
         6. optional: static analysis + probes
         7. store metrics (proxy: tokens, cache, prefill/decode tps, TTFT, cost; GPU: VRAM, shared memory, power)
```

The proxy records every model request and its streamed response in a harness-neutral form (`transcript.jsonl`), so
the live view shows thinking, text, tool calls and tool results for **any** harness, not only ones with JSON output.

## Memory projection

* **Before download**: the GGUF header is read over HTTP range requests (metadata + tensor table, no weights).
  Weights are summed per layer from the tensor table; KV cache is
  `Σ_layers ctx_layer × (n_head_kv × (key_len + val_len)) × bytes(cache type)` with sliding-window, hybrid
  (recurrent) and MLA layers handled; compute buffers and CUDA context are estimated and calibrated.
* **After download**: `llama-fit-params` performs a dry-run allocation for the exact arguments and reports device,
  host, KV and compute memory. LLMDyno compares this with the free VRAM it measures right now.
* **At run time**: VRAM, Windows shared GPU memory (spill) and llama-server's own fit log are monitored.

Warnings (danger / warning / info) include: exceeds VRAM (Linux OOM, Windows spill to shared memory), tight headroom,
llama.cpp auto-fit moving layers to CPU, partial or MoE CPU offload, CPU-only inference without AVX2/AVX-512, RAM
shortfall, context above training length, context below what a benchmark needs, quantized V cache without flash
attention, very low-bit quants, chat templates without tool support, too-small output limits for reasoning
models, disk space, and missing API keys or budgets.

## Data model (SQLite)

Settings (folders, ports, electricity price, default scoring weights) live in `data/settings.json`; secrets in
`data/secrets.json`, encrypted. Everything else is in SQLite:

| table | purpose |
|---|---|
| `models` | local GGUF files: repo, files, size, parsed metadata, download state |
| `providers` | vendor, base URL, API style, key reference, budget (spend lives in ledger files, see below) |
| `profiles` | local / cloud / endpoint profile with inference + sampling parameters and last fit check |
| `harness_builds` | image build status per harness manifest and version |
| `custom_harnesses` | user harness manifests |
| `suites` | named benchmark sets |
| `plans` | the run matrix, options, status |
| `runs` | one profile × harness × benchmark × iteration: status, metrics, result JSON |
| `reviews` | judge outputs per run and judge profile |
| `jobs` | background work (downloads, installs, builds, plans, judging) with progress and logs |

## Scoring

`final = w_c·correctness + w_i·instruction_following + w_q·quality + w_e·efficiency` (defaults 50/15/25/10), with
`quality = 0.35 static + 0.30 probes + 0.35 review` re-weighted over the parts that exist. Efficiency compares wall
time with the fastest run on the same benchmark that reached ≥ 80% correctness. Weights are adjustable live on the
dashboard. Iterations report mean, standard deviation, 95% CI and pass@k.

## Safety and reliability

* **Panic stop** (`POST /api/system/panic`, the red sidebar button, Ctrl+Shift+X): cancels every job, marks running
  and queued runs of active plans cancelled, removes all containers labelled `org.llmdyno.role` (proxies first, which
  cuts agents off from paid APIs immediately), and kills llama-server plus any stray copy still holding the port.
  Paused plans and finished results are left alone. Stopping the server does the same for containers and llama-server.
* **Spend ledgers**: each writer (every run's proxy, and the host for judging and quick tests) owns one shard file per
  ledger, `data/ledgers/<ledger>__<writer>.json`, and readers sum the shards. Parallel runs therefore never overwrite
  each other's spend. Requests cut off mid-stream are still booked, from a size-based estimate.
* **Stale connections**: the proxy drops agent connections idle for 30 minutes and gives up on an upstream that sends
  nothing for `proxy_idle_timeout_s` (15 minutes by default). The WebSocket server cleans up a closed tab at once and
  tells a client that cannot keep up to resync instead of buffering without limit; the browser reconnects after 50 s
  of silence and refetches whatever it shows.
* **GPU safety**: free VRAM is re-measured right before every model load, and a profile that would spill or run out of
  memory is refused unless the plan allows it.

## Versioning

LLMDyno uses Semantic Versioning; `llmdyno/__init__.py` holds the only copy of the version (pyproject reads it,
`scripts/bump_version.py` updates `frontend/package.json` and the changelog). The database schema version is SQLite's
`user_version`: `db.SCHEMA_VERSION` plus a `MIGRATIONS` table of upgrade steps, and a data folder written by a newer
release is refused rather than modified. Every run's snapshot records the LLMDyno version that produced it, and
result exports carry it in their file name and header.

## The mascot

`scripts/make_logo.py` draws the pixel dinosaur as named 48×48 layers (body, four run-cycle leg frames, booster
flames, belt frames, podium, thought bubble…) and writes `frontend/src/dyno-sprite.ts`, the favicon and the README
images. The `Dyno` component picks layers per state and animates them with CSS `steps()` keyframes; `useDynoState()`
derives the state from background jobs and panic events, and the app mirrors it in the tab icon and title.
