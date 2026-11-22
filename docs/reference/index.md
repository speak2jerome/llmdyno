# API reference

Everything here is available as `llmdyno.<name>` after `import llmdyno`, and nearly all of it as a `llmdyno`
command too (see [the command line reference](cli.md)). The pages follow the areas of the dashboard. The async
versions are in `llmdyno.aio` ([Live events and async](live.md)), and the pytest plugin's fixtures are on
[Interop and CI](interop.md).

| Page | What is in it |
|---|---|
| [Setup, system and jobs](system.md) | Opening a data folder, checking and installing dependencies, the machine's specs and GPU, background jobs, cleanup and the panic stop, and the dashboard. |
| [Profiles](profiles.md) | A model plus the exact settings it is benchmarked with. |
| [Models](models.md) | GGUF models: Hugging Face search, fit estimates, downloads and imports. |
| [Providers](providers.md) | Cloud providers, local OpenAI-compatible servers and LiteLLM. |
| [Harnesses and agents](harnesses.md) | Built-in and custom harnesses, and your own Python or TypeScript agent as a harness. |
| [Benchmarks and suites](benchmarks.md) | Built-in, your own and imported benchmarks (SWE-bench, Aider polyglot), and suites. |
| [Plans](plans.md) | Running profiles × harnesses × benchmarks × iterations. |
| [Runs and transcripts](runs.md) | One run's details, transcript, workspace, logs and telemetry. |
| [Results](results.md) | Scores, every view of the Results page, exports and charts. |
| [Judging](judging.md) | Blind code review by LLM judges. |
| [Live events and async](live.md) | Following work as it happens. |
| [Remote mode](remote.md) | Driving a LLMDyno server on another machine. |
| [Settings and references](settings.md) | Settings, tokens and Artificial Analysis reference numbers. |
| [Interop and CI](interop.md) | Inspect AI, regression checks for CI and the pytest plugin. |
| [Errors](errors.md) | One error family for the library and the web API. |
| [Command line](cli.md) | Every `llmdyno` command with its arguments and defaults. |
| [Web API map](web-api.md) | Every web API route with its Python call, command and JavaScript method. |

Integrations with other libraries are methods of these objects (`Results.to_pandas()`, `Results.plot`,
`Results.log_to_mlflow()`, …) and are described in [Integrations](../INTEGRATIONS.md).
