# Adding a harness

A harness is the agent program that drives the model: it reads the task, calls tools, edits files and runs tests.
LLMDyno runs every harness the same way: in an offline Docker image built on `llmdyno-sandbox:1`, with its home
directory at `/home/agent`, the task in `/workspace`, and its model endpoint pointing at a per-run proxy.

There are two ways to add one.

## 1. A custom harness from the UI (no code)

**Harnesses → Add custom harness** takes a JSON manifest:

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

- `install` lines are Dockerfile instructions appended after `FROM llmdyno-sandbox:1`. Pin versions.
- `files` are written relative to the agent's home directory before each run.
- Placeholders available in `files`, `env` and commands: `{model}`, `{base_url}`, `{openai_base_url}` (base URL
  plus `/v1`), `{api_style}`, `{ctx}`, `{max_tokens}`, `{reasoning}`, `{session_id}`.
- The stage prompt is in the shell variable `$PROMPT`; the command must use it.
- `apis` lists the wire formats the harness can speak: `openai-chat`, `openai-responses`, `anthropic`. LLMDyno only
  pairs it with profiles whose provider speaks one of them.
- `multi_stage`: `resume` continues the same session for later stages (with `continue_command`); `fresh` starts a
  new session each stage with the same workspace.

The UI shows the generated Dockerfile and config files before you build.

## 2. A built-in adapter (Python)

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

Add an instance to `BUILTIN` at the bottom of the file. `rc` is a `RunCtx` with `model`, `base_url`, `openai_base`,
`api_style`, `ctx`, `max_tokens`, `reasoning`, `temperature`, `local` and `session_id`.

## Rules every adapter follows

- **Never put a real key in a sandbox.** Use a placeholder; the proxy replaces the `Authorization` / `x-api-key`
  header with the real key.
- **Non-interactive and auto-approving.** The harness must not wait for input (stdin is `/dev/null`) and must be
  allowed to run shell commands and edit files.
- **Offline.** The sandbox has no internet. Anything the harness needs at run time must be installed in the image.
- **Machine-readable output if available** (`--json`, `stream-json`). It ends up in the run's logs; the transcript
  itself comes from the proxy, so it works even for harnesses with plain-text output.

## Testing

`tests/test_profiles_harnesses.py` renders every harness for every API style it claims and checks that commands use
`$PROMPT` and that no key leaks into the environment. Then build the image from the Harnesses page and run the
smoke-test benchmark with a local profile: it takes a couple of minutes and exercises the whole path.
