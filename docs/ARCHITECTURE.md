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
   ├── server.py    the app: routes, the error handler, the remote-access check, the WebSocket, the built UI (web/static)
   ├── api/         thin FastAPI routes: map HTTP to service calls, nothing else
   ├── services/    what every feature does, one module per area; plain data in and out, llmdyno.errors on failure
   ├── sdk/         the Python library (import llmdyno) over the same services, through a backend seam
   ├── cli.py       the command line, generated from the library; lib.py and aio.py re-export the library
   ├── integrations/ data frames, charts, notebooks, MLflow, W&B, Langfuse, OpenTelemetry, the Hub, Inspect AI
   │                (client side: they use only the library; a test enforces it); pytest_plugin.py
   ├── system/      spec detection (CPU/ISA, RAM, GPUs/VRAM/driver, disk, Docker, WSL, Apple) and dependency checks
   ├── hub/         Hugging Face search, remote GGUF header parsing (HTTP range), resumable downloads
   ├── memory.py    VRAM/RAM projection: estimator (pre-download) + llama-fit-params dry run (post-download) + warnings
   ├── inference/   llama.cpp release installer, llama-fit-params and the llama-server lifecycle
   ├── providers/   vendor catalog (OpenAI, Anthropic, Gemini, DeepSeek, Kimi, GLM, Qwen, MiniMax, xAI, Mistral,
   │                OpenRouter, Groq, Together, Fireworks, Cerebras, LiteLLM, custom), local-server detection, prices
   ├── harnesses/   built-in harness adapters (Python classes), custom manifests, image builds, portable runtimes
   ├── benchmarks/  built-in tasks, suites, the benchmark editor's spec, validation, SWE-bench and polyglot imports,
   │                Artificial Analysis reference data; common/ holds the grader helpers mounted at /grader_common
   ├── runner/      plan scheduler (GPU-serial local runs, parallel cloud runs), sandbox driver, metrics
   ├── proxy/       stdlib logging proxy (runs in a container): token usage, speed, cost cap, transcript capture
   ├── quality/     static analysis image (ruff, radon, bandit, vulture, coverage) and probes
   ├── judge/       blind LLM review with user-chosen judges, agreement and self-preference stats
   ├── llm.py       host-side model calls (judging, quick tests) and the spend ledgers
   ├── scoring.py   configurable weights, iteration statistics (mean, sd, 95% CI, pass@k)
   ├── jobs.py      background jobs: a thread pool, progress and logs in SQLite, exclusive groups (one GPU user)
   ├── events.py    in-process publish/subscribe feeding the WebSocket and the library's listeners
   ├── safety.py    the panic stop; auth.py remote access; secrets.py the key store; config.py settings; db.py SQLite
   ├── docker/      Dockerfiles of the sandbox, code-quality and polyglot images
   └── sample/      the bundled round 1 results
frontend/          the React UI; `npm run build` writes llmdyno/web/static, which is committed
js/                the npm package: the TypeScript client and the npx launcher
<data folder>/llmdyno.db — profiles, providers, plans, runs, reviews, jobs
<data folder>/runs/<plan>/<run>/ — workspace, proxy logs, transcript stream, grader output
```

The data folder is `./data` in a git checkout and a per-user folder otherwise; [Configuration](CONFIGURATION.md)
lists where it is and everything in it.

### One set of services, two front ends

The web API and the Python library are two doors into the same code. `llmdyno/services/<area>.py` holds what each
feature does and returns plain data (a download comes back as `{filename, media_type, content}` or a file path; file
views as text), raising `llmdyno.errors` with the HTTP status each error means. The routes in `llmdyno/api/` only
turn HTTP into service calls and back, and one exception handler in `server.py` maps errors to `{"detail": …}`.

The library in `llmdyno/sdk/` calls services by name, `call("runs.run_transcript", rid=...)`, through a backend:
`LocalBackend` runs them in-process, and `RemoteBackend` (from `llmdyno.connect()`) sends the same call to another
machine's API, which has the same names and parameters. SDK modules reach the database and the engine only
through services (`tests/test_library.py` checks their imports; the local backend, the remote route table and the
parity map are the named exceptions), so every object works the same either way. Live events reach the library through
`events.add_listener`, which works without the web server; `watch()` falls back to polling for work in another
process. `tests/test_parity.py` maps every route to the library call that covers it (`@covers`), so a feature can't
reach the dashboard without reaching Python too.

The JavaScript client in `js/` (the `llmdyno` npm package) makes the same calls over HTTP. Its table of operations,
`js/src/generated.ts`, is generated from the same route table `RemoteBackend` uses (`scripts/gen_js_client.py`), and
`tests/test_js_client.py` fails when it falls behind. `npx llmdyno` (`js/src/cli.ts`) starts the Python app through an
installed copy, uv or pipx.

### Remote access

Requests from the server's own machine need nothing, provided they name a loopback host in `Host` (so a page using
DNS rebinding to reach 127.0.0.1 counts as remote) and don't come from a browser page on another site (an `Origin`
that isn't a loopback name is refused with 403, and such a WebSocket is closed). Every other request to `/api`,
including one forwarded by a
reverse proxy that adds `X-Forwarded-For`, `Forwarded` or `X-Real-IP`, must present the API token (`auth.py`): an
`Authorization: Bearer` header, or `?token=` (which downloads and the WebSocket use). A reverse proxy that adds none of
those headers makes every request look local, so it must add one (see [Remote mode](REMOTE.md#https-and-reverse-proxies)). One middleware in `server.py` checks it and logs the changes remote clients make. The
library's `RemoteBackend` (`llmdyno/sdk/remote.py`) maps each service call to its route from the API's own route
table, so `llmdyno.connect()` needs no list of endpoints to keep in step.

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
         2. start the run's own proxy container  (internal network alias → upstream: llama-server or vendor)
         3. render the harness config (models.json, opencode.json, config.toml, env, …) pointing at the proxy
         4. docker run <harness image> on the internal network (no internet), per stage, with a timeout
         5. grade in a fresh offline container (hidden tests copied in only after the agent is gone)
         6. optional: static analysis + probes
         7. store metrics (proxy: tokens, cache, prefill/decode tps, TTFT, cost; GPU: VRAM, shared memory, power)
```

The proxy records every model request and its streamed response in a harness-neutral form (`transcript.jsonl`), so
the live view shows thinking, text, tool calls and tool results for **any** harness, not only ones with JSON output.

### Benchmarks with their own image (SWE-bench, Aider polyglot)

Built-in tasks run in `llmdyno-harness-<id>`, which is the sandbox base plus one harness. SWE-bench tasks have to run
in their official images instead (Ubuntu 22.04, the repository at `/testbed`, a conda environment per task), and
building every harness into every one of 500 images would waste hundreds of gigabytes. So each harness is also built
once as a **portable runtime**: `llmdyno-rt-<id>` is an Ubuntu 22.04 image whose `/opt/dyno-rt` holds Node, the
agent CLI and ripgrep, or a standalone Python (python-build-standalone through uv) with the harness in a venv. Its
contents are copied into a Docker volume, and that volume is mounted at `/opt/dyno-rt` in whatever image the task
names. Building on the oldest glibc the task images use means the binaries also run on newer bases such as the Debian
polyglot image. ENV lines from the harness install are passed as `-e` flags, since a mounted folder can't set them.

```
per run (env benchmark):
  1. pull the task image for its platform (linux/amd64 for SWE-bench, emulated on ARM64 hosts)
  2. volume dyno-ws-<run> <- copy of /testbed from the image
  3. per stage: docker run <task image> -v <runtime volume>:/opt/dyno-rt -v dyno-ws-<run>:/testbed
                -v dyno-ws-<run>:/workspace ... bash /bench/stageN.sh   (activates conda, adds the runtime to PATH)
     (the runtime image is llmdyno-rt-<harness>:<version>-<arch>-<hash of its Dockerfile>, copied once into a volume
      named after it)
  4. git diff --binary <start commit> inside the volume -> model.patch   (the image's HEAD when the volume was made:
     SWE-bench images add their own commit on top of the task's base commit, and the harness applies patches there)
  5. official harness (swebench.harness.run_evaluation, own venv) grades the patch -> report.json -> resolved
     (started through swebench_shim.py, which only keeps Unix line endings on Windows: the harness writes the patch
     and eval script in text mode, and CRLF would break git apply and bash inside the Linux container)
  6. remove the workspace volume
```

Runtimes are prepared once per plan, before any run starts, so parallel cloud runs never race to build the same image.

## Live events

`events.publish(topic, kind, data)` fans out to WebSocket subscribers and to the library's listeners, in process.
Topics are `jobs`, `job:<id>`, `plans`, `plan:<id>`, `run:<id>`, `models`, `profiles`, `reviews` and `system`; a
message is `{topic, kind, data, ts}`. On `/ws`, a client sends `{"sub": [...], "unsub": [...]}` to choose topics
(every socket gets `jobs`). The server pings every 20 seconds, sends events in batches of up to 200, and when a client
falls more than 5000 events behind it sends `{"topic": "*", "kind": "resync"}` instead, after which the client
refetches. A remote socket without a valid token is closed with code 1008.

## Sandboxes and networking

* **Agents** run on `llmdyno-internal`, a Docker network created with `--internal`: no route to the internet or the
  LAN. They get a memory limit (the plan's `memory_gb`, 12 GB by default), 2 to 8 CPUs and a process limit. On Linux
  they run as your user id in the sandbox image, and as root in task images such as SWE-bench's.
* **The proxy** for each run (512 MB, read-only code) sits on the same internal network under the run's own alias,
  listens on port 8081, and is the only container that can reach the outside: llama-server on the host or the
  vendor's API.
* **llama-server** listens on 127.0.0.1 on Windows and macOS (Docker Desktop forwards `host.docker.internal`) and on
  Docker's bridge gateway on Linux, never on 0.0.0.0. The `llama_bind_host` setting overrides it.
* **Graders, code-quality analysis, probes, workspace copies and patch extraction** run with `--network none`. Only
  image builds have network access.

## Judging

A judging job sends each finished run to each judge profile. Every judge sees a blind id per run and its own shuffled
order, the task's prompts and the files the agent wrote (up to 450 lines per file and 90 000 characters in all), and
optionally the static-analysis summary. It scores the rubric's dimensions (eight by default) from 1 to 10 and answers
in JSON; the overall score defaults to the mean of the dimensions. Each review gets two attempts; a rate limit or a
refusal stops the job. Cloud judges run in parallel (4 by default), local judges take the GPU like any local run. Runs
a judge already reviewed are skipped unless asked. Agreement between two judges needs at least three runs both
reviewed; self-preference compares how each judge scores its own model family against the other judges.

## Memory projection

* **Before download**: the GGUF header is read over HTTP range requests (metadata + tensor table, no weights).
  Weights are summed per layer from the tensor table; KV cache is
  `Σ_layers ctx_layer × (n_head_kv × (key_len + val_len)) × bytes(cache type)` with sliding-window, hybrid
  (recurrent) and MLA layers handled; compute buffers and CUDA context are estimated and calibrated.
* **After download**: `llama-fit-params` performs a dry-run allocation for the exact arguments and reports device,
  host, KV and compute memory. LLMDyno compares this with the free VRAM it measures right now.
* **At run time**: VRAM, Windows shared GPU memory (spill) and llama-server's own fit log are monitored.
* **Unified memory (Apple Silicon)**: the budget is Metal's working-set limit (`iogpu.wired_limit_mb` if set,
  otherwise about 2/3 of RAM up to 36 GB and 3/4 above), not total RAM. Going over it means swapping, not a driver
  spill, so it is reported as out of memory. Offloading layers to the CPU saves nothing there (it is the same memory),
  and the fix offered is a smaller context or quant instead. GPU memory in use and utilisation come from
  IOAccelerator statistics (no root needed); power does not, so Mac runs have no energy figure.

Warnings (danger / warning / info) include: exceeds VRAM (Linux OOM, Windows spill to shared memory), tight headroom,
llama.cpp auto-fit moving layers to CPU, partial or MoE CPU offload, CPU-only inference without AVX2/AVX-512, RAM
shortfall, context above training length, context below what a benchmark needs, quantized V cache without flash
attention, very low-bit quants, chat templates without tool support, too-small output limits for reasoning
models, disk space, and missing API keys or budgets.

## Data model (SQLite)

Settings (folders, ports, electricity price, default scoring weights) live in `settings.json` in the data folder;
API keys and tokens in `secrets.json` (encrypted with DPAPI on Windows; on Linux and macOS a file only your user can
read). Benchmarks you create are folders under `benchmarks/`. Everything else is in SQLite:

| table | purpose |
|---|---|
| `models` | local GGUF files: repo, files, size, parsed metadata, download state |
| `providers` | vendor, base URL, API style, budget (the key is in secrets.json under `provider:<id>`; spend lives in ledger files, see below) |
| `profiles` | local / cloud / endpoint profile with inference + sampling parameters and last fit check |
| `harness_builds` | image build status per harness manifest and version |
| `custom_harnesses` | user harness manifests |
| `suites` | named benchmark sets |
| `plans` | the run matrix, options, status |
| `runs` | one profile × harness × benchmark × iteration: status, metrics, result JSON |
| `reviews` | judge outputs per run and judge profile |
| `jobs` | background work (downloads, installs, image builds, imports, plans, judging, quick tests, validation and re-grading) with progress and logs |

## Scoring

`final = w_c·correctness + w_i·instruction_following + w_q·quality + w_e·efficiency` (defaults 50/15/25/10),
re-weighted over the parts a run has, with `quality = 0.35 static + 0.30 probes + 0.35 review` re-weighted the same
way. Each part is 0 to 1:

- **correctness**: the share of hidden tests passed (1 or 0 for SWE-bench and polyglot);
- **instruction following**: the benchmark's checks averaged with three checks every run gets (no package installs,
  finished within the time limit, a real final summary);
- **quality**: static analysis, behaviour probes and judge reviews (the mean over judges of their overall score / 10);
- **efficiency**: `1 − log2(wall time / reference) / 4`, clamped to 0..1, so it reaches 0 at 16 times slower than the
  reference. The reference is the fastest local run on the same benchmark that passed (correctness ≥ the pass
  threshold, 0.8 by default), or with `efficiency_ref="all"` the fastest run of any kind.

Weights, the pass threshold and the efficiency reference are adjustable live on the dashboard and in `results()`.
Iterations report mean, standard deviation, 95% CI and pass@k.

## Safety and reliability

* **Panic stop** (`POST /api/system/panic`, the red sidebar button or Ctrl+Shift+X, then a confirmation): cancels every job, marks running
  and queued runs of active plans cancelled, removes all containers labelled `org.llmdyno.role` (proxies first, which
  cuts agents off from paid APIs immediately), and kills llama-server plus any stray copy still holding the port.
  Paused plans and finished results are left alone. Stopping the server does the same for containers and llama-server.
* **Spend ledgers**: each writer (every run's proxy, and the host for judging and quick tests) owns one shard file per
  ledger, `<data>/ledgers/<ledger>__<writer>.json`, and readers sum the shards. Parallel runs therefore never
  overwrite each other's spend. Requests cut off mid-stream are still booked, from a size-based estimate. The proxy
  refuses requests once a provider's or plan's ledger reaches its budget. Judging and quick tests run on the host:
  their spend is booked to the provider's ledger, and a judging job stops at its own budget.
* **Stale connections**: the proxy drops agent connections idle for 30 minutes and gives up on an upstream that sends
  nothing for `proxy_idle_timeout_s` (15 minutes by default). The WebSocket server cleans up a closed tab at once and
  tells a client that cannot keep up to resync instead of buffering without limit; the browser reconnects after 50 s
  of silence and refetches whatever it shows.
* **GPU safety**: free VRAM is re-measured right before every model load, and a profile that would spill or run out of
  memory is refused unless the plan allows it.

## Versioning

LLMDyno uses Semantic Versioning; `llmdyno/__init__.py` holds the source of the version (pyproject reads it, and
`scripts/bump_version.py` writes it into the frontend and JS packages and their lock files, `js/src/version.ts`,
`CITATION.cff`, `codemeta.json`, the bug report template and the changelog; tests check they agree). The database schema version is SQLite's
`user_version`: `db.SCHEMA_VERSION` plus a `MIGRATIONS` table of upgrade steps, and a data folder written by a newer
release is refused rather than modified. Every run's snapshot records the LLMDyno version that produced it, and
result exports carry it in their file name and header.

## The mascot

`scripts/make_logo.py` draws the pixel dinosaur as named 48×48 layers (body, four run-cycle leg frames, booster
flames, belt frames, podium, thought bubble…) and writes `frontend/src/dyno-sprite.ts`, the favicon and the README
images. The `Dyno` component picks layers per state and animates them with CSS `steps()` keyframes; `useDynoState()`
derives the state from background jobs and panic events, and the app mirrors it in the tab icon and title.
