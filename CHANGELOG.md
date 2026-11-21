# Changelog

All notable changes to LLMDyno are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While LLMDyno is 0.x, a minor release (0.2.0) may change the HTTP API, the data folder layout or the database schema.
Schema changes always ship with an automatic migration; a data folder written by a newer release is refused rather
than modified. Patch releases (0.1.1) only fix bugs.

## [Unreleased]

### Added

- **The library can do everything the dashboard does.** Every web API route has a library call (116 of them), and a
  test keeps it that way. New objects with their methods: `Model`, `Provider`, `Harness`, `Benchmark`, `Suite`, `Run`,
  `Transcript`, `Settings` and `Job`. Among the new calls:
  - models: `search_models()`, `repo_info()`, `estimate()` (fit before downloading), `download_model()`,
    `import_models()`, `recommended_models()`, `Model.contexts()`, `.profile()`, `.pause()`, `.resume()`, `.delete()`;
  - profiles: `Profile.duplicate()`, `.export()`, `import_profile()`, `profile_defaults()`, and `update()` for the name,
    notes, tags and pricing;
  - providers: `provider()`, `add_provider()`, `Provider.test()`, `.models()`, keys, budget and spend, `vendors()`,
    `lookup_price()`;
  - harnesses: `harness()`, `Harness.build()`, `.dockerfile()`, `.preview()`, runtimes, custom harnesses;
  - benchmarks: `benchmark()`, `create_benchmark()`, `Benchmark.update()`, `.duplicate()`, `.export()`, `.validate()`,
    `import_benchmark()`, suites, and the SWE-bench and polyglot setup calls;
  - runs: `run()`, `Run.transcript()` with `turns()`, `tool_calls()`, `thinking()` and `usage()`, `.files()`,
    `.read_file()`, `.download()`, `.log()`, `.gpu()`, `.requests()`, `.retry()`, `.regrade()`, `.cancel()`;
  - plans: `Plan.retry()`, `.rename()`, `.delete()`, `.get_runs()`;
  - results: every Results-page option (`benchmarks=`, `pass_threshold=`, `quality_weights=`, `efficiency_ref=`),
    `cells()`, `rubric()`, `agreement()`, `reviews()`, `reference()`, `export()`, `save_weights()`, the sample data;
  - judging: `review()` with a custom rubric, guidance and single runs, `judge_defaults()`, `reviews()`,
    `delete_reviews()`;
  - Artificial Analysis, settings, Hugging Face token, specs, GPU, jobs, cleanup, panic and Docker repair.
- **Command line for everything**: every library call is a `llmdyno` command, generated from the library
  (`llmdyno list-models`, `llmdyno run transcript RUN_ID --view tool-calls`, `--json` for scripts). A test keeps the
  two in step.
- `llmdyno.watch(plan or run or job)` yields live events (run and plan changes, GPU samples, job progress and, with
  `transcript=True`, every agent event and model request). `bench()`, `Plan.wait()` and `Plan.resume()` take
  `on_event=`. Live events no longer need the web server to be running.
- `llmdyno.aio`: every library function as a coroutine, plus `aio.watch()` and `aio.call()`.
- `llmdyno.job(id)` and the `Job` object (status, progress, log, `wait()`, `cancel()`).
- Library objects expose their data: `obj["field"]`, `obj.get()`, `obj.to_dict()` and `obj.refresh()`.
- The full error family is public: `InvalidError`, `ForbiddenError`, `RiskNotAcknowledgedError`, `RateLimitError`,
  `UpstreamError` and `InsufficientStorageError` join `NotFoundError`, `ConflictError` and `PreflightError`.
- **Integrations** with mainstream libraries, each an optional extra (`pip install "llmdyno[all]"` for all of them;
  a missing one says what to install). See docs/INTEGRATIONS.md.
  - Data and notebooks: `to_pandas()`, `to_polars()` and `to_parquet()` for every table and transcripts; rich tables
    for `Results`, `Plan` and `Run` in Jupyter; `Plan.live()` widget; tqdm progress in `bench()`.
  - Charts like the dashboard's: `results.plot.leaderboard()`, `.heatmap()`, `.pareto()`, `.radar()`, `.tokens()`,
    in matplotlib or plotly.
  - Tracking and tracing: `log_to_mlflow()`, `log_to_wandb()` (offline works), `log_to_langfuse()` and `to_otel()`
    (GenAI semantic conventions, real timestamps); `bench(auto_log=...)`.
  - Model gateways: a LiteLLM vendor and `litellm_model()` (Azure OpenAI, Bedrock, Vertex AI, …, prices from
    LiteLLM's table), `local_servers()`, `ollama_model()` and `openai_compatible()`; the Hugging Face token from
    `hf auth login` is reused; `Results.push_to_hub()` and `load_results_from_hub()`.
  - Your own agent: `python_harness("my_agent:run", requirements=[...])` benchmarks a Python agent in the same
    sandbox as the built-in harnesses, with templates for LangGraph, the OpenAI Agents SDK, smolagents and PydanticAI.
  - Inspect AI: `inspect_task()`, `import_inspect_samples()`, `Results.to_inspect_log()`.
  - CI: `llmdyno ci --baseline ... --max-drop 2` and `compare_results()`, a pytest plugin
    (`@pytest.mark.llmdyno(min_score=...)`), and a GitHub Actions workflow in examples/ci.
- **Remote mode**: `llmdyno serve --host 0.0.0.0` asks other machines for an access token (made on first use, shown
  once, `llmdyno token --rotate` replaces it) and logs the changes they make; `llmdyno.connect(url, token)` sends every
  library call to that server, with live events over its WebSocket; `--url` / `--api-token` on every command; the web
  UI asks for the token when opened from another machine. Requests from the server's own machine need nothing, as
  before. See docs/REMOTE.md.
- A documentation site (MkDocs) with guides and an API reference generated from the code, and example notebooks that
  CI runs.

### Changed

- Internals: the web API's logic moved into `llmdyno/services` (one module per area) and the library into
  `llmdyno/sdk`, both over the same services. The HTTP API is unchanged: every endpoint answers with the same status,
  headers and body as in 0.3.1.
- `cloud_model()` saves the given or environment API key every time instead of comparing it with the stored one first
  (same result, and it works without reading the secret store).
- Library calls raise the same errors the web API answers with (a missing benchmark is `NotFoundError`, a built-in one
  you try to edit is `ForbiddenError`, …) instead of Python's `KeyError` or `PermissionError`; the mapping lives in one
  place, `llmdyno.errors.from_exception`, used by both.
- The `custom` vendor is no longer the only one that may run without an API key: vendors carry `key_optional`
  (`custom` and the new `litellm`).
- The library is type-checked: pyright strict on `llmdyno.sdk` and `llmdyno.errors` (fully typed signatures),
  standard on the services, web API, CLI and integrations; CI runs it with every extra installed.

### Fixed

- Uploading a file that is not a zip as a benchmark answered with a server error; it now says what is wrong (400).
- A dependency action posted without an `action` answered with a server error; it is now a 400 naming the problem.

## [0.3.1] - 2026-11-22

### Added

- LLMDyno is on PyPI: `pip install llmdyno`. Releases publish there automatically through trusted publishing.

### Fixed

- The README's images and links are absolute, so they work on the PyPI project page too (a test keeps them that way).

## [0.3.0] - 2026-11-22

### Added

- **Python library**: `import llmdyno` gives the whole app as an API: `cloud_model()` and `local_model()` (download or
  register GGUF files), `bench()` with a preflight that raises `PreflightError` before anything starts, `Results`
  with `leaderboard()`, `runs()`, `to_pandas()`, `to_csv()`, `to_json()` and `open()`, plus `setup()`, `doctor()`,
  SWE-bench and polyglot imports, LLM-judge `review()` and `serve()`. Long operations print progress and Ctrl+C cancels
  them cleanly. It uses the same data folder as the app, so plans run from Python show up in the dashboard.
  `import llmdyno` stays instant: the API loads on first use. Guide: docs/LIBRARY.md; examples in examples/.
- The release workflow can publish to PyPI (trusted publishing), switched on with the `PUBLISH_PYPI` repository
  variable.

### Fixed

- `CITATION.cff` and the bug-report template said 0.3.0 in the 0.2.0 release: the version test bumped the real files
  instead of its temporary copies. The test now redirects every file the bump script writes and fails if it touches
  the repository.

## [0.2.0] - 2026-11-21

### Added

- **Apple Silicon and ARM64**: LLMDyno now runs on macOS (Apple Silicon), Linux on ARM64 and Windows on ARM, as well
  as x86-64. Detection covers ARM CPU features (NEON, dot product, i8mm, SVE), performance and efficiency cores,
  Apple GPUs (chip, GPU cores, bandwidth) and Qualcomm Adreno. The Setup page explains the Metal memory limit and
  offers the command to raise it, and on ARM64 hosts it notes that SWE-bench images need x86-64 emulation.
- **llama.cpp builds for every platform**: release assets are parsed instead of hard-coded, so the installer picks
  the right archive for the OS, CPU architecture and backend (CUDA 12/13, Metal, Vulkan, ROCm, SYCL, OpenVINO,
  OpenCL for Adreno, CPU) and keeps working when llama.cpp moves to a new CUDA version (it just did, to 13.5).
- **Unified memory**: on Apple Silicon the memory check plans against the GPU's share of unified memory, reports
  going over it as out of memory (swap) rather than a spill, and offers smaller context or quant fixes instead of
  CPU offload. Runs record GPU memory in use and utilisation from IOAccelerator statistics.
- **SWE-bench**: import Verified, Lite or Verified mini from the official datasets. Agents work inside each task's
  official image; patches are graded by the official `swebench` harness (installed into its own venv from Setup), so
  "resolved" means what it means on the leaderboard. Validate grades a task's gold patch. Plans export their patches
  in the SWE-bench predictions format.
- **Aider polyglot**: import the 225 exercises (C++, Go, Java, JavaScript, Python, Rust) with suites per language,
  and build the toolchain image from Setup. Every test is enabled, the original tests are restored before grading,
  and an exercise is solved only when all of them pass.
- **Artificial Analysis reference**: with a free API key (Settings), Results shows each profile's model with its
  Intelligence Index, output speed, TTFT and 3:1 blended price next to what LLMDyno measured, with attribution.
  Matches are automatic and can be corrected per profile.
- **Portable harness runtimes**: each harness can be built once into a self-contained folder that is mounted into
  any benchmark image, which is how every harness runs SWE-bench and polyglot tasks. Benchmarks can name their own
  image (`env` in `benchmark.json`), so custom tasks can use this too.
- Results: a Public benchmarks card (SWE-bench resolved rate, polyglot solved rate per language).
- **Re-grade**: a finished run can be graded again from the workspace (or SWE-bench patch) it left behind, without
  running the agent again, for when a grader is fixed after the fact. Token, time and GPU figures are kept.
- CI runs on Apple Silicon, Linux ARM64 and Windows on ARM; `scripts/platform_probe.py` prints what LLMDyno detects.

### Changed

- `setup.sh` accepts macOS and ARM64. Docker Desktop on macOS can be started from Setup, with a Homebrew install
  command when it is missing.
- On macOS the data folder for pip installs is `~/Library/Application Support/LLMDyno`.
- llama-server's bind address can be overridden with the `llama_bind_host` setting.

### Fixed

- Setup spots Docker Desktop on Windows stuck at start-up ("The file cannot be accessed by the system") because a
  crash left socket files behind, and offers a one-click fix that moves them aside. "Reset to factory defaults",
  which Docker suggests, would delete every image.
- Setup loads on Apple Silicon Macs where macOS does not report the CPU frequency (psutil raised "'pmgr' entry
  was not found"), as seen on GitHub's macOS runners.
- Setup, Harnesses and the import dialog load on machines without Docker installed; before, the missing `docker`
  command crashed them.
- Leaderboard bars add up to the final score when a configuration has no code-quality score (before, they were
  scaled as if quality counted as zero while the score left it out).

## [0.1.0] - 2026-10-26

First public release.

### Added

- **Setup**: detects the OS, CPU (AVX2/AVX-512), RAM, NVIDIA/AMD/Intel GPUs, driver and CUDA version, disks and Docker
  on x86-64 Windows and Linux; a guided first-run wizard installs or points to Docker and a matching prebuilt
  llama.cpp release (CUDA 12/13, Vulkan, ROCm, SYCL or CPU).
- **Models**: Hugging Face search with a memory-fit check before download; resumable downloads with SHA-256
  verification; import of existing GGUF folders; GGUF metadata read over HTTP range requests.
- **Memory projection**: per-layer KV cache (sliding-window, shared-KV, hybrid recurrent and MLA layers), compute
  buffers and CUDA overhead, checked against `llama-fit-params`; warnings for out-of-memory, VRAM spilling into
  shared system memory (Windows Sysmem Fallback), CPU offload, context limits and risky sampling settings.
- **LLM profiles** for local (llama.cpp) and cloud models, with one-click fixes, an exact memory check and a quick
  test that measures real VRAM, speed and tool calling.
- **Cloud providers**: OpenAI, Anthropic, Google Gemini, DeepSeek, Moonshot (Kimi), Z.ai, Qwen, MiniMax, xAI,
  Mistral, OpenRouter, Groq, Together, Fireworks, Cerebras and any OpenAI-compatible endpoint; keys encrypted at
  rest (DPAPI on Windows); per-provider and per-plan spend caps enforced by a proxy.
- **Harnesses**: Pi, OpenCode, Codex CLI, Qwen Code, Crush, Aider and mini-SWE-agent in offline Docker sandboxes,
  plus custom harnesses from a JSON manifest.
- **Benchmarks**: six built-in tasks with hidden tests, a benchmark editor, suites, zip import/export and a grader
  validator that checks the starter fails and the reference passes.
- **Plans**: profiles × harnesses × benchmarks × iterations, preflight checks, live transcripts for every harness,
  GPU telemetry, pause, resume, retry and cancel.
- **Judging**: blind, shuffled LLM code review with an editable rubric, any number of judges, judge agreement and
  self-preference statistics.
- **Results dashboard**: leaderboard with confidence intervals, per-benchmark heatmap, radar, cost/speed scatter
  with a Pareto front, consistency (pass@k, pass^k), token use, harness comparison, rubric heatmap, side-by-side
  compare, adjustable weights and CSV/JSON export.
- **Panic stop**: one button (Ctrl+Shift+X) that cancels every job and run, removes all sandbox and proxy
  containers and kills llama-server.
- **Mascot**: an animated pixel dinosaur on a treadmill that shows what the app is doing; the browser tab icon and
  title follow it.
- Bundled sample results: 15 configurations × 5 tasks on an RTX 5080, judged by two models.

[Unreleased]: https://github.com/speak2jerome/llmdyno/compare/v0.3.1...HEAD
[0.3.1]: https://github.com/speak2jerome/llmdyno/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/speak2jerome/llmdyno/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/speak2jerome/llmdyno/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/speak2jerome/llmdyno/releases/tag/v0.1.0
