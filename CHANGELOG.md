# Changelog

All notable changes to LLMDyno are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While LLMDyno is 0.x, a minor release (0.2.0) may change the HTTP API, the data folder layout or the database schema.
Schema changes always ship with an automatic migration; a data folder written by a newer release is refused rather
than modified. Patch releases (0.1.1) only fix bugs.

## [Unreleased]

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

[Unreleased]: https://github.com/speak2jerome/llmdyno/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/speak2jerome/llmdyno/releases/tag/v0.1.0
