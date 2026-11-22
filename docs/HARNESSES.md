# Adding a harness

A harness is the agent program that drives the model: it reads the task, calls tools, edits files and runs tests.
LLMDyno runs every harness the same way: in an offline Docker image built on `llmdyno-sandbox:1`, with its home
directory at `/home/agent`, the task in `/workspace`, and its model endpoint pointing at the run's own proxy.

## Built-in harnesses

| Id | Harness | Version | Installed with | APIs | Later stages |
|---|---|---|---|---|---|
| `pi` | [Pi](https://github.com/earendil-works/pi) | 1.4.0 | npm | openai-chat, openai-responses, anthropic | resumes the session |
| `opencode` | [OpenCode](https://opencode.ai) | 1.19.4 | npm | openai-chat, openai-responses, anthropic | resumes the session |
| `codex` | [Codex CLI](https://github.com/openai/codex) | 0.164.0 | npm | openai-responses | resumes the session |
| `qwen-code` | [Qwen Code](https://github.com/QwenLM/qwen-code) | 0.26.1 | npm | openai-chat | resumes the session |
| `crush` | [Crush](https://github.com/charmbracelet/crush) | 0.98.2 | npm | openai-chat, anthropic | resumes the session |
| `aider` | [Aider](https://aider.chat) | 0.86.2 | pip | openai-chat | resumes the chat; edits come from replies, not tool calls |
| `mini-swe-agent` | [mini-SWE-agent](https://mini-swe-agent.com) | 2.4.6 | pip | openai-chat | fresh start per stage |

Build them on the Harnesses page ("Build", or "Build all missing"), with `llmdyno.setup(harnesses=[...])`, or with
`llmdyno harness build ID`. A local llama.cpp model speaks `openai-chat` and `openai-responses`, so every built-in
harness works with it; a cloud profile speaks its provider's styles. LLMDyno picks the API
style for a run in this order: the profile's or provider's own style when the harness speaks it, then `anthropic`, then
`openai-responses`, then `openai-chat`.

There are three ways to add one: a custom harness from the UI or a manifest, your own Python or TypeScript agent, or a
built-in adapter in Python.

## 1. A custom harness (no code)

On the Harnesses page, **Custom harness** opens a form ("Add a custom harness") with the fields below. The same thing as
JSON goes to `llmdyno.add_harness(manifest)` (a dict or a path to a `.json` file), `llmdyno add-harness FILE`, or
`POST /api/harnesses/custom`:

```json
{
  "id": "my-agent",
  "name": "My Agent",
  "version": "1.2.3",
  "install": ["RUN npm_config_offline=false npm install -g my-agent@1.2.3"],
  "files": { ".config/my-agent/config.json": "{\"baseUrl\": \"{openai_base_url}\", \"model\": \"{model}\"}" },
  "env": { "OPENAI_BASE_URL": "{openai_base_url}", "OPENAI_API_KEY": "proxy-injects-the-key" },
  "command": "my-agent --yes --model {model} \"$PROMPT\"",
  "continue_command": "my-agent --yes --continue --model {model} \"$PROMPT\"",
  "apis": ["openai-chat"],
  "multi_stage": "resume",
  "tool_style": "native"
}
```

| Field | Required | Default | What it is |
|---|---|---|---|
| `id` | yes | | Lower-case letters, digits and dashes, 2 to 41 characters, starting with a letter or digit. Not a built-in id. |
| `name` | yes | | The name shown everywhere. |
| `version` | no | `custom` | Part of the image tag, `llmdyno-harness-<id>:<version>`. Change it when the install changes. |
| `description`, `homepage`, `license` | no | empty | Shown on the harness card. |
| `install` | no | none | Dockerfile lines (`RUN`, `ENV`, `ARG`, `COPY`, `ADD`, `WORKDIR`, `USER`, `LABEL`), appended to the image. Pin versions. |
| `files` | no | none | `{path: content}`, written under `/home/agent` once per run. Paths can't start with `/` or contain `..`. |
| `env` | no | none | `{NAME: value}`, set for every stage. |
| `command` | yes | | The shell command for stage 1. It must use `$PROMPT`. |
| `continue_command` | no | | The command for stages 2 and later, when the harness can continue its session. |
| `apis` | no | `["openai-chat"]` | The wire formats it speaks: `openai-chat`, `openai-responses`, `anthropic`. LLMDyno only pairs it with profiles that speak one of them. |
| `multi_stage` | no | `fresh` | `resume` or `fresh`, shown on the card. What actually happens is set by `continue_command`: when it is present, every stage after the first uses it. |
| `tool_style` | no | `native` | `native` (tool calls) or `text` (edits parsed from replies), shown on the card. |

Placeholders work in `files`, `env` and both commands:

| Placeholder | Becomes |
|---|---|
| `{model}` | The model id to request. For local profiles it is `local-model`. |
| `{base_url}` | The run's proxy, `http://dyno-proxy-<run>:8081`. |
| `{openai_base_url}` | `{base_url}/v1`. |
| `{api_style}` | The API style chosen for the run. |
| `{ctx}` | The profile's context size (65536 when it has none). |
| `{max_tokens}` | The profile's output limit per turn (16384 when it has none). |
| `{reasoning}` | The profile's reasoning effort, empty for local profiles. |
| `{session_id}` | A session id for the run, `bench-<run>`. |
| `{stage}` | The stage number. `files` and `env` are rendered for stage 1, so use it in commands. |
| `{home}`, `{workspace}` | `/home/agent` and `/workspace`. |

Unknown `{names}` are left as they are, so JSON braces in `files` are safe.

After you add it, the harness drawer shows the generated Dockerfile and, per API style, the rendered command,
environment and config files. Build the image from there.

### How the image is built and run

- **The image** is `FROM llmdyno-sandbox:1`, then `USER root`, then your `install` lines. It is built from an empty
  folder, so `COPY` and `ADD` can't take files from your machine: download or write them in `RUN` lines, or use
  `python_harness()` / `node_harness()`, which copy your code in for you.
- **Installs need the network switched back on.** The sandbox image sets `PIP_NO_INDEX=1` and
  `npm_config_offline=true` so that agents can't download packages during a run. In `install` lines, use
  `npm_config_offline=false npm install …` or `env -u PIP_NO_INDEX pip install …`.
- **At run time** each stage runs `<command> < /dev/null` from a script, with the stage's prompt in `$PROMPT`, in
  `/workspace`, with no network except the private one to the proxy. The home folder (`/home/agent`) is kept for the
  whole run, so sessions and config carry over between stages.
- **On Linux** the agent runs as your user id, so anything it writes at run time must be under `/home/agent`,
  `/workspace` or `/tmp`.

## 2. Your own agent

`llmdyno.python_harness("my_agent:run", requirements=[...])` and `llmdyno.node_harness("agent.ts:run")` turn a
Python or TypeScript function into a harness: they write the manifest, copy your code into the image and install its
packages. The ids are `py-<module>` and `js-<file name>`. See [Integrations](INTEGRATIONS.md#your-own-agent) and
[JavaScript and TypeScript](JAVASCRIPT.md#benchmark-your-own-typescript-agent).

These agents are installed outside the portable runtime described below, so they run LLMDyno's own benchmarks but not
those that bring their own image (SWE-bench, Aider polyglot).

## 3. A built-in adapter (Python)

Built-in harnesses live in `llmdyno/harnesses/catalog.py` as subclasses of `Harness`:

```python
class MyAgent(Harness):
    id, name, version = "my-agent", "My Agent", "1.2.3"
    homepage, license = "https://example.com/my-agent", "MIT"
    description = "One line on what makes it different."
    apis = ["openai-chat", "anthropic"]
    multi_stage = "resume"            # or "fresh"
    strengths = ["..."]
    caveats = ["..."]

    def install(self):                # Dockerfile lines
        return npm_install(f"my-agent@{self.version}")

    def files(self, rc):              # {path under HOME: content}
        return {".config/my-agent/config.json": json.dumps({"baseUrl": rc.openai_base, "model": rc.model})}

    def env(self, rc):
        return {"OPENAI_API_KEY": "proxy-injects-the-key"}

    def command(self, rc, stage, n_stages):
        cont = " --continue" if stage > 1 else ""
        return f"cd {WORKSPACE} && my-agent --yes{cont} --model {shlex.quote(rc.model)} \"$PROMPT\""
```

Add an instance to `BUILTIN` at the bottom of the file, a row to the table above and to the README, and its licence to
`NOTICE.md`. `rc` is a `RunCtx` with `model`, `base_url`, `openai_base`, `api_style`, `ctx`, `max_tokens`,
`reasoning`, `temperature`, `local`, `session_id` and `display_name`.

## Rules every adapter follows

- **Never put a real key in a sandbox.** Use a placeholder; the proxy replaces the `Authorization` / `x-api-key`
  header with the real key.
- **Non-interactive and auto-approving.** The harness must not wait for input (stdin is `/dev/null`) and must be
  allowed to run shell commands and edit files.
- **Offline.** The sandbox has no internet. Anything the harness needs at run time must be installed in the image.
- **Machine-readable output if available** (`--json`, `stream-json`). It ends up in the run's logs; the transcript
  itself comes from the proxy, so it works even for harnesses with plain-text output.
- **Portable.** For benchmarks with their own image (SWE-bench, polyglot) the harness is installed into
  `/opt/dyno-rt` on Ubuntu 22.04 (`Harness.runtime_install()`), and that folder is mounted into the task's image.
  npm installs go there automatically through `npm_config_prefix`; Python harnesses set
  `venv = (name, pip spec, [bins])` and get a standalone Python. Keep everything the harness needs at run time inside
  that prefix; paths the install writes elsewhere (such as `/opt/xdg-cache`) are rewritten into it. Custom harnesses
  get the same treatment on a best-effort basis. The runtime is built once per harness version and platform, as the
  image `llmdyno-rt-<id>:<version>-<arch>-<hash>`, and copied into a Docker volume.

## Testing

`tests/test_profiles_harnesses.py` renders every built-in harness for every API style it claims and checks that the
commands use `$PROMPT` and that no `sk-` key appears in the environment. Then build the image from the Harnesses page
and run the smoke-test benchmark (`t0_smoke_cli`) with a local profile: it takes a couple of minutes and exercises the
whole path.
