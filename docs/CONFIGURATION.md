# Configuration

LLMDyno keeps everything it knows in one data folder: the database, your settings, encrypted API keys, downloaded
models and every run's files. This page covers where that folder is, what is in it, the settings you can change, and
the environment variables LLMDyno reads.

## The data folder

| How you installed it | Data folder |
|---|---|
| `pip install llmdyno` on Windows | `%LOCALAPPDATA%\LLMDyno` |
| `pip install llmdyno` on macOS | `~/Library/Application Support/LLMDyno` |
| `pip install llmdyno` on Linux | `$XDG_DATA_HOME/llmdyno`, usually `~/.local/share/llmdyno` |
| A git checkout (there is a `pyproject.toml` next to the package) | `./data` inside the checkout |

`LLMDYNO_DATA=/some/folder` overrides it for the web app, the library and the command line. You can also pick it per
call: `llmdyno --data DIR <command>` on the command line, `llmdyno.init("DIR")` in Python. The web app, the library and
the CLI share whatever folder they point at, so a plan started from Python shows up in the dashboard.

`llmdyno.data_dir()` (or `llmdyno data-dir`) prints the folder in use. `GET /api/health` reports it too.

What is inside:

| Path | What it holds |
|---|---|
| `llmdyno.db` | The SQLite database: models, profiles, providers, harnesses, plans, runs, reviews and jobs. The `-wal` and `-shm` files next to it belong to it. |
| `settings.json` | Settings you changed from their defaults (see below). |
| `secrets.json` | API keys, the Hugging Face and Artificial Analysis keys and the remote access token. Encrypted with Windows DPAPI for your Windows user; on Linux and macOS the file is readable only by you (mode 600). |
| `models/` | Downloaded GGUF files, one folder per Hugging Face repository. Change it with the `models_dir` setting. |
| `runs/<plan>/<run>/` | One folder per run: the agent's `workspace/`, `transcript.jsonl` (what the model saw and said), `proxy.jsonl` (every API request with tokens, timing and cost), `result.json` (scores), and the harness's stdout and stderr per stage. Change it with the `runs_dir` setting. |
| `runs/<plan>/gpu_<profile>.jsonl`, `server_<profile>.log` | GPU telemetry and the llama-server log while that profile was loaded. |
| `bin/llama.cpp/` | llama.cpp builds installed by the Setup page or `llmdyno.setup()`. |
| `benchmarks/` | Your own benchmarks and imported SWE-bench tasks. |
| `imports/` | Downloaded sources of imported benchmarks (the Aider polyglot exercises). |
| `tools/swebench/` | The official SWE-bench harness, in its own virtual environment. |
| `ledgers/` | Spend so far per provider and per plan, which the proxy checks budgets against. |
| `cache/`, `references/` | Cached GGUF headers from Hugging Face, the OpenRouter model list and Artificial Analysis data. Safe to delete. |
| `validation/` | Scratch folders from the benchmark validator. Safe to delete. |
| `logs/remote-requests.jsonl` | Changes made from other machines in [remote mode](REMOTE.md): time, address, method, path and status. |

To back up LLMDyno, copy the whole folder while it is not running. To start fresh, point `LLMDYNO_DATA` at an empty
folder. A data folder written by a newer LLMDyno is refused rather than modified, and an older one is migrated
automatically when it is opened.

`secrets.json` on Windows can only be decrypted by the Windows user who wrote it. If you copy the folder to another
machine or user, add the keys again on the Providers and Settings pages.

## Settings

Change settings on the **Settings** page, or from Python:

```python
s = llmdyno.settings()
s.cloud_concurrency                          # read as attributes or keys: s["weights"]
s.update(cloud_concurrency=4, electricity_usd_per_kwh=0.30)
```

| Setting | Default | What it does |
|---|---|---|
| `models_dir` | `<data>/models` | Where downloaded models go. |
| `runs_dir` | `<data>/runs` | Where run folders go. |
| `electricity_usd_per_kwh` | `0.15` | Electricity price used to turn a local run's measured GPU energy into a cost. |
| `default_vram_margin_mib` | `1024` | VRAM left free when `llama-fit-params` checks whether a profile fits, for the desktop, browser and other apps. |
| `cloud_concurrency` | `3` | Cloud runs in parallel within a plan. A plan can set its own (`bench(cloud_concurrency=...)`). Local runs always take the GPU one model at a time. |
| `weights` | correctness 50, instruction following 15, quality 25, efficiency 10 | How the final score is weighted. The Results page can try other weights without saving them. |
| `quality_weights` | static analysis 35, behaviour probes 30, judge review 35 | How the quality score is made up. |
| `llama_port` | `18180` | The port llama-server listens on. Change it if something else uses that port. |
| `theme` | `system` | `system`, `light` or `dark` for the web app. |
| `onboarded` | `false` | Whether the first-run wizard has been completed. Set it back to `false` to see the wizard again. |

These can be read but not changed through the API (edit `settings.json` while LLMDyno is stopped if you must):

| Setting | Default | What it does |
|---|---|---|
| `port` | `8777` | The web app's port. `llmdyno serve --port N` overrides it for one start. |
| `proxy_idle_timeout_s` | `900` | The run proxy gives up on an upstream API that sends nothing for this many seconds. |
| `llama_bind_host` | empty | The address llama-server listens on so sandboxes can reach it. Empty means 127.0.0.1 on Windows and macOS (Docker Desktop forwards `host.docker.internal`) and Docker's bridge gateway on Linux, never 0.0.0.0. Set it when your Docker runs in a VM that can't reach the host's loopback, such as Colima. |
| `llama_cpp` | empty | Path, version and backend of the llama.cpp build in use. The Setup page and `llmdyno.use_llama_cpp()` set it. |
| `swebench.harness_version` | `5.0.2` | Version of the official SWE-bench harness that Setup installs. |
| `aa_reference.overrides` | empty | Artificial Analysis models matched to profiles by hand (`llmdyno.set_aa_match()`). |
| `hf_token_set` | `false` | Whether a Hugging Face token is saved. Use `llmdyno.set_hf_token()` to change it. |

## Environment variables

| Variable | Read by | Meaning |
|---|---|---|
| `LLMDYNO_DATA` | app, library, CLI | The data folder (see above). |
| `LLMDYNO_URL` | library, CLI, JS client | A LLMDyno server to drive instead of this machine, such as `http://gpu-box:8777`. The JS client defaults to `http://127.0.0.1:8777`. |
| `LLMDYNO_TOKEN` | library, CLI, JS client | The access token for that server (printed once on the server when it is made; `llmdyno token --rotate` makes a new one). |
| `LLMDYNO_PYTHON` | `npx llmdyno` | A Python interpreter to try first when the launcher looks for an installed LLMDyno (before `py -3`, `python` and `python3`, and before falling back to uv or pipx). |
| `LLMDYNO_LAUNCHER_DRY_RUN` | `npx llmdyno` | Set to `1` to print the command the launcher would run instead of running it. |
| `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` or `GOOGLE_API_KEY`, `DEEPSEEK_API_KEY`, `MOONSHOT_API_KEY`, `ZAI_API_KEY`, `DASHSCOPE_API_KEY`, `MINIMAX_API_KEY`, `XAI_API_KEY`, `MISTRAL_API_KEY`, `OPENROUTER_API_KEY`, `GROQ_API_KEY`, `TOGETHER_API_KEY`, `FIREWORKS_API_KEY`, `CEREBRAS_API_KEY` | `cloud_model()` | The provider's key when `cloud_model()` gets no `api_key=`. When the variable is set it replaces a saved key, and it is saved, encrypted, in the data folder for the web app to use too. |
| `LITELLM_API_KEY` or `LITELLM_MASTER_KEY` | `litellm_model()` | The key for a LiteLLM proxy. |
| `HF_TOKEN` | model downloads | Used through `huggingface_hub` when it is installed (the `hub` extra) and no token is saved in Settings, as is the token from `hf auth login`. |
| `LOCALAPPDATA`, `XDG_DATA_HOME` | app | Where the default data folder goes on Windows and Linux. |

Variables such as `UPSTREAM`, `LEDGERS` or `LLMDYNO_ENTRYPOINT` in the code are set by LLMDyno for the containers it
starts (the run proxy and agent sandboxes). You don't set them.

## Ports

| Port | What listens | Who can reach it |
|---|---|---|
| 8777 | The web app and its API (`llmdyno serve`) | This machine only, unless you start it with `--host 0.0.0.0` (then other machines need the token). |
| 18180 | llama-server while a local profile is loaded | This machine and its Docker containers. Never the network. |
| none | Run proxies and sandboxes | Containers talk to their proxy over a private Docker network. Sandboxes have no internet access. |

## Secrets

API keys, the Hugging Face token, the Artificial Analysis key and the remote access token are kept in `secrets.json`,
not in `settings.json` or the database. Only the run proxy container receives a provider's real key; agents in the
sandbox get a placeholder and have no internet access. The access token for remote clients is printed once, when it
is made (by `llmdyno serve --host 0.0.0.0` or `llmdyno token`); `llmdyno token --rotate` replaces it and prints the new
one, and the old one stops working at once. See [Remote mode](REMOTE.md).
