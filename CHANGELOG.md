# Changelog

All notable changes to LLMDyno are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/)
and the project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

While LLMDyno is 0.x, a minor release (0.2.0) may change the HTTP API, the data folder layout or the database schema.
Schema changes always ship with an automatic migration; a data folder written by a newer release is refused rather
than modified. Patch releases (0.1.1) only fix bugs.

## [Unreleased]

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
