# Third-party notices

LLMDyno is MIT licensed (see [LICENSE](LICENSE)). It bundles or downloads the following.

## Bundled in the web UI

| Component | License | Use |
|---|---|---|
| [@lobehub/icons-static-svg](https://github.com/lobehub/lobe-icons) | MIT | vendor and model-family logos |
| [Press Start 2P](https://fonts.google.com/specimen/Press+Start+2P) by CodeMan38 | SIL OFL 1.1 | pixel wordmark |
| [Inter](https://rsms.me/inter/) | SIL OFL 1.1 | UI text |
| [JetBrains Mono](https://www.jetbrains.com/lp/mono/) | SIL OFL 1.1 | code |
| [React](https://react.dev), [TanStack Query](https://tanstack.com/query), [React Router](https://reactrouter.com) | MIT | UI |
| [Apache ECharts](https://echarts.apache.org) | Apache 2.0 | charts |
| [Lucide](https://lucide.dev) | ISC | icons |
| [marked](https://marked.js.org), [DOMPurify](https://github.com/cure53/DOMPurify), [highlight.js](https://highlightjs.org), [jsdiff](https://github.com/kpdecker/jsdiff) | MIT / Apache 2.0 / BSD-3-Clause / BSD-3-Clause | transcripts and diffs |

## Downloaded at setup time (not redistributed)

- [llama.cpp](https://github.com/ggml-org/llama.cpp) prebuilt releases (MIT), from GitHub.
- Agent harnesses, installed into Docker images when you build them: Pi (MIT), OpenCode (MIT), Codex CLI
  (Apache 2.0), Qwen Code (Apache 2.0), Crush (FSL-1.1-MIT), Aider (Apache 2.0) and mini-SWE-agent (MIT). Each keeps
  its own licence.
- Docker base images for the sandbox, code-quality, polyglot and portable-runtime images: `python:3.12-slim-bookworm`,
  `node:24-bookworm-slim`, `ubuntu:22.04`, `golang`, `rust` and `eclipse-temurin`, each under its own licences, and
  [uv](https://github.com/astral-sh/uv) (MIT / Apache 2.0) with
  [python-build-standalone](https://github.com/astral-sh/python-build-standalone) Pythons for the portable runtimes.
- Models you choose from Hugging Face, under their own licences.

When you use them:

- [SWE-bench](https://www.swebench.com): the official evaluation harness (MIT, installed from PyPI into its own
  virtual environment), the SWE-bench Verified, Lite and Verified mini datasets (from Hugging Face), and the official
  task images, each with its repository's licence.
- The [Aider polyglot benchmark](https://github.com/Aider-AI/polyglot-benchmark) exercises (MIT, from Exercism).
- [Artificial Analysis](https://artificialanalysis.ai) reference data, with your own free API key, shown with a link
  back to the source; and OpenRouter's public model and price catalog, for looking up prices.

## Trademarks

Product names and logos (OpenAI, Anthropic, Claude, Google, Gemini, Gemma, Meta, Llama, Qwen, Alibaba, DeepSeek,
Moonshot, Kimi, Z.ai, Zhipu, MiniMax, xAI, Grok, Mistral, NVIDIA, Microsoft, IBM, OpenRouter, Groq, Together,
Fireworks, Cerebras, Hugging Face and others) are trademarks of their owners. LLMDyno shows them only to identify
which provider or model a profile uses. LLMDyno is not affiliated with or endorsed by any of them.

The mascot is original pixel art made for LLMDyno; it is not derived from any other game's sprites.
