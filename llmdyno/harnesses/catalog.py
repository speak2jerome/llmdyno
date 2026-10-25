"""Agent harnesses: how to install each one in a sandbox image and how to point it at the benchmark proxy.

Every harness talks to http://<proxy>:8081 inside the sandbox network; the proxy holds the real key, measures usage
and records the transcript, so adapters only render config files and a command line. A run's HOME (/home/agent)
is a per-run folder, which keeps sessions between stages and lets you inspect what the harness stored."""
import json
import re
import shlex

HOME = "/home/agent"
WORKSPACE = "/workspace"


class RunCtx:
    """What an adapter needs to know about the model endpoint for one run."""

    def __init__(self, model, base_url, api_style, ctx, max_tokens, reasoning=None, temperature=None,
                 local=False, session_id="bench", display_name=None):
        self.model, self.base_url, self.api_style = model, base_url, api_style
        self.ctx, self.max_tokens, self.reasoning, self.temperature = ctx, max_tokens, reasoning, temperature
        self.local, self.session_id, self.display_name = local, session_id, display_name or model

    @property
    def openai_base(self):
        return self.base_url.rstrip("/") + "/v1"


class Harness:
    id = ""
    name = ""
    version = ""
    homepage = ""
    license = ""
    description = ""
    apis = ["openai-chat"]
    multi_stage = "resume"       # resume: continue the same session per stage | fresh: new session, same workspace
    tool_style = "native"        # native tool calls | text (commands parsed from plain text)
    strengths = []
    caveats = []
    builtin = True

    def image(self):
        return f"llmdyno-harness-{self.id}:{self.version}"

    def install(self):
        """Dockerfile lines appended after FROM the sandbox base."""
        return []

    def dockerfile(self, base):
        lines = [f"FROM {base}", "USER root"] + self.install()
        lines += [f'LABEL org.llmdyno.role=harness org.llmdyno.harness="{self.id}" '
                  f'org.llmdyno.version="{self.version}"', f"WORKDIR {WORKSPACE}"]
        return "\n".join(lines) + "\n"

    def files(self, rc):
        """{path relative to HOME: content}"""
        return {}

    def env(self, rc):
        return {}

    def command(self, rc, stage, n_stages):
        """Shell command (bash). The stage prompt is available as "$PROMPT"."""
        raise NotImplementedError

    def info(self):
        return {"id": self.id, "name": self.name, "version": self.version, "homepage": self.homepage,
                "license": self.license, "description": self.description, "apis": self.apis,
                "multi_stage": self.multi_stage, "tool_style": self.tool_style, "image": self.image(),
                "strengths": self.strengths, "caveats": self.caveats, "builtin": self.builtin,
                "install": self.install()}


def npm_install(pkg):
    return [f"RUN npm_config_offline=false npm install -g --no-audit --no-fund {pkg} && npm cache clean --force"]


def venv_install(name, spec, bins):
    links = " && ".join(f"ln -sf /opt/{name}/bin/{b} /usr/local/bin/{b}" for b in bins)
    return [f"RUN python -m venv /opt/{name} && env -u PIP_NO_INDEX /opt/{name}/bin/pip install --no-cache-dir {spec} "
            f"&& {links}"]


class Pi(Harness):
    id, name, version = "pi", "Pi", "1.4.0"
    homepage, license = "https://github.com/earendil-works/pi", "MIT"
    description = ("Minimal, fast coding agent with a small tool set (read, write, edit, bash) and automatic context "
                   "compaction. The harness used for LLMDyno's reference results.")
    apis = ["openai-chat", "openai-responses", "anthropic"]
    strengths = ["JSON event stream", "session resume across stages", "automatic compaction"]

    def install(self):
        return npm_install(f"--ignore-scripts @earendil-works/pi-coding-agent@{self.version}") + [
            "ENV PI_OFFLINE=1 PI_SKIP_VERSION_CHECK=1 PI_TELEMETRY=0"]

    def files(self, rc):
        api = {"openai-chat": "openai-completions", "openai-responses": "openai-responses",
               "anthropic": "anthropic-messages"}[rc.api_style]
        prov = {"name": "bench", "baseUrl": rc.base_url if rc.api_style == "anthropic" else rc.openai_base,
                "api": api, "apiKey": "proxy-injects-the-key",
                "models": [{"id": rc.model, "name": rc.display_name, "reasoning": bool(rc.reasoning) and not rc.local,
                            "contextWindow": rc.ctx, "maxTokens": rc.max_tokens,
                            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}}]}
        if rc.api_style == "openai-chat":
            prov["compat"] = {"supportsDeveloperRole": False, "supportsStore": False, "maxTokensField": "max_tokens",
                              "supportsReasoningEffort": bool(rc.reasoning) and not rc.local}
        settings = {"defaultProjectTrust": "never", "quietStartup": True,
                    "compaction": {"enabled": True, "reserveTokens": 16384, "keepRecentTokens": 20000},
                    "retry": {"enabled": True, "maxRetries": 3}}
        return {".pi/agent/models.json": json.dumps({"providers": {"bench": prov}}, indent=2),
                ".pi/agent/settings.json": json.dumps(settings, indent=2)}

    def command(self, rc, stage, n_stages):
        think = f" --thinking {rc.reasoning}" if rc.reasoning and not rc.local else ""
        return (f"pi --mode json --model {shlex.quote('bench/' + rc.model)} --session-dir {HOME}/sessions "
                f"--session-id {rc.session_id}{think} -- \"$PROMPT\"")


class OpenCode(Harness):
    id, name, version = "opencode", "OpenCode", "1.19.4"
    homepage, license = "https://opencode.ai", "MIT"
    description = "Feature-rich terminal coding agent (sst/opencode) with LSP support, sub-agents and todo tracking."
    apis = ["openai-chat", "openai-responses", "anthropic"]
    strengths = ["rich built-in tools (glob, grep, todo, task)", "session continue", "JSON events"]
    caveats = ["larger system prompt and tool schemas than Pi: needs more context"]
    PKG = {"openai-chat": "@ai-sdk/openai-compatible", "openai-responses": "@ai-sdk/openai", "anthropic": "@ai-sdk/anthropic"}

    def install(self):
        # opencode installs AI SDK provider packages on first use; pre-install them so the offline sandbox works
        warm = json.dumps({"$schema": "https://opencode.ai/config.json", "autoupdate": False, "provider": {
            f"w{i}": {"npm": pkg, "options": {"baseURL": "http://127.0.0.1:9/v1", "apiKey": "x"},
                      "models": {"m": {"name": "m"}}} for i, pkg in enumerate(self.PKG.values())}})
        return npm_install(f"opencode-ai@{self.version}") + [
            "ENV XDG_CACHE_HOME=/opt/xdg-cache OPENCODE_DISABLE_AUTOUPDATE=1 OPENCODE_DISABLE_LSP_DOWNLOAD=true",
            f"RUN mkdir -p /tmp/warm && echo {shlex.quote(warm)} > /tmp/warm/opencode.json "
            "&& cd /tmp/warm && (OPENCODE_CONFIG=/tmp/warm/opencode.json timeout 180 opencode models > /tmp/warm/models.txt 2>&1 || true) "
            "&& ls /opt/xdg-cache/opencode 2>/dev/null; chmod -R a+rwX /opt/xdg-cache || true"]

    def files(self, rc):
        base = rc.base_url.rstrip("/") + "/v1"
        model = {"name": rc.display_name, "limit": {"context": rc.ctx, "output": rc.max_tokens}}
        cfg = {"$schema": "https://opencode.ai/config.json", "autoupdate": False, "share": "disabled",
               "provider": {"bench": {"npm": self.PKG[rc.api_style], "name": "Bench",
                                      "options": {"baseURL": base, "apiKey": "proxy-injects-the-key"},
                                      "models": {rc.model: model}}},
               "model": f"bench/{rc.model}", "small_model": f"bench/{rc.model}",
               "permission": {"edit": "allow", "bash": "allow", "webfetch": "deny", "external_directory": "allow"}}
        return {".config/opencode/opencode.json": json.dumps(cfg, indent=2)}

    def command(self, rc, stage, n_stages):
        cont = " --continue" if stage > 1 else ""
        variant = f" --variant {rc.reasoning}" if rc.reasoning and not rc.local else ""
        return f"opencode run --format json --auto -m {shlex.quote('bench/' + rc.model)}{variant}{cont} \"$PROMPT\""


class Codex(Harness):
    id, name, version = "codex", "Codex CLI", "0.164.0"
    homepage, license = "https://github.com/openai/codex", "Apache-2.0"
    description = "OpenAI's open-source coding agent (Rust). Speaks only the Responses API."
    apis = ["openai-responses"]
    strengths = ["strong planning and patch tools", "JSONL events", "resume"]
    caveats = ["needs a Responses API upstream (OpenAI, xAI, or llama-server's /v1/responses)"]

    def install(self):
        return npm_install(f"@openai/codex@{self.version}")

    def files(self, rc):
        effort = f'model_reasoning_effort = "{rc.reasoning}"\n' if rc.reasoning and not rc.local else ""
        toml = (f'model = "{rc.model}"\nmodel_provider = "bench"\n{effort}model_context_window = {rc.ctx}\n'
                'approval_policy = "never"\nsandbox_mode = "danger-full-access"\n'
                'check_for_update_on_startup = false\n\n[analytics]\nenabled = false\n\n'
                f'[model_providers.bench]\nname = "Bench"\nbase_url = "{rc.openai_base}"\nenv_key = "BENCH_API_KEY"\n'
                'wire_api = "responses"\n')
        return {".codex/config.toml": toml}

    def env(self, rc):
        return {"BENCH_API_KEY": "proxy-injects-the-key", "CODEX_HOME": f"{HOME}/.codex"}

    def command(self, rc, stage, n_stages):
        flags = f"--json --skip-git-repo-check --dangerously-bypass-approvals-and-sandbox -C {WORKSPACE}"
        if stage > 1:
            return f"codex exec resume --last {flags} \"$PROMPT\""
        return f"codex exec {flags} \"$PROMPT\""


class QwenCode(Harness):
    id, name, version = "qwen-code", "Qwen Code", "0.26.1"
    homepage, license = "https://github.com/QwenLM/qwen-code", "Apache-2.0"
    description = "Qwen's fork of Gemini CLI, tuned for Qwen coder models but works with any OpenAI-compatible model."
    apis = ["openai-chat"]
    strengths = ["stream-json output with partial messages", "session resume"]
    caveats = ["large tool set and system prompt"]

    def install(self):
        return npm_install(f"@qwen-code/qwen-code@{self.version}")

    def files(self, rc):
        settings = {"security": {"auth": {"selectedType": "openai"}}, "model": {"name": rc.model},
                    "general": {"disableAutoUpdate": True, "disableUpdateNag": True},
                    "privacy": {"usageStatisticsEnabled": False}, "telemetry": {"enabled": False}}
        return {".qwen/settings.json": json.dumps(settings, indent=2)}

    def env(self, rc):
        return {"OPENAI_API_KEY": "proxy-injects-the-key", "OPENAI_BASE_URL": rc.openai_base, "OPENAI_MODEL": rc.model}

    def command(self, rc, stage, n_stages):
        cont = " --continue" if stage > 1 else ""
        return f"qwen --yolo -o stream-json --include-partial-messages -m {shlex.quote(rc.model)}{cont} \"$PROMPT\""


class Aider(Harness):
    id, name, version = "aider", "Aider", "0.86.2"
    homepage, license = "https://aider.chat", "Apache-2.0"
    description = "Pair-programming tool that edits files from model replies (diff/whole formats) rather than tool calls."
    apis = ["openai-chat"]
    tool_style = "text"
    strengths = ["works with models that cannot call tools", "efficient edit formats"]
    caveats = ["not autonomous: it does not run tests or iterate on its own unless the model asks for shell commands",
               "one message per stage"]

    def install(self):
        return venv_install("aider", f"aider-chat=={self.version}", ["aider"]) + [
            "ENV AIDER_CHECK_UPDATE=false AIDER_ANALYTICS=false LITELLM_LOCAL_MODEL_COST_MAP=True"]

    def files(self, rc):
        meta = {f"openai/{rc.model}": {"max_input_tokens": rc.ctx, "max_output_tokens": rc.max_tokens,
                                       "input_cost_per_token": 0, "output_cost_per_token": 0,
                                       "litellm_provider": "openai", "mode": "chat"}}
        return {".aider.model.metadata.json": json.dumps(meta, indent=2)}

    def env(self, rc):
        return {"OPENAI_API_BASE": rc.openai_base, "OPENAI_API_KEY": "proxy-injects-the-key"}

    def command(self, rc, stage, n_stages):
        restore = " --restore-chat-history" if stage > 1 else ""
        return (f"cd {WORKSPACE} && aider --model {shlex.quote('openai/' + rc.model)} "
                f"--model-metadata-file {HOME}/.aider.model.metadata.json --yes-always --no-git --no-auto-commits "
                "--no-show-model-warnings --no-check-update --analytics-disable --no-pretty --no-fancy-input "
                f"--chat-history-file {HOME}/.aider.chat.history.md --input-history-file {HOME}/.aider.input.history"
                f"{restore} --message \"$PROMPT\"")


class MiniSwe(Harness):
    id, name, version = "mini-swe-agent", "mini-SWE-agent", "2.4.6"
    homepage, license = "https://mini-swe-agent.com", "MIT"
    description = "Minimal agent from the SWE-bench team: a single bash tool, called through native tool calls (v2)."
    apis = ["openai-chat"]
    multi_stage = "fresh"
    strengths = ["tiny prompt, very little overhead", "tests raw model ability with a single tool"]
    caveats = ["new session per stage (the workspace carries over)"]

    def install(self):
        # litellm imports its MCP client lazily; without the package every request fails
        return venv_install("mini", f"mini-swe-agent=={self.version} mcp", ["mini"]) + [
            "ENV MSWEA_CONFIGURED=true MSWEA_COST_TRACKING=ignore_errors MSWEA_SILENT_STARTUP=1 LITELLM_LOCAL_MODEL_COST_MAP=True"]

    def env(self, rc):
        return {"OPENAI_API_BASE": rc.openai_base, "OPENAI_BASE_URL": rc.openai_base,
                "OPENAI_API_KEY": "proxy-injects-the-key", "MSWEA_GLOBAL_CONFIG_DIR": f"{HOME}/.config/mini-swe-agent"}

    def command(self, rc, stage, n_stages):
        return (f"cd {WORKSPACE} && mini -y --exit-immediately -l 0 -m {shlex.quote('openai/' + rc.model)} "
                f"-o {HOME}/trajectory_stage{stage}.json -t \"$PROMPT\"")


class Crush(Harness):
    id, name, version = "crush", "Crush", "0.98.2"
    homepage, license = "https://github.com/charmbracelet/crush", "FSL-1.1-MIT"
    description = "Charm's terminal coding agent (Go) with LSP integration and a polished tool set."
    apis = ["openai-chat", "anthropic"]
    strengths = ["fast native binary", "session continue"]
    caveats = ["source-available licence (FSL, converts to MIT after two years)"]

    def install(self):
        return npm_install(f"@charmland/crush@{self.version}") + ["ENV CRUSH_DISABLE_METRICS=1 DO_NOT_TRACK=1"]

    def files(self, rc):
        ptype = {"openai-chat": "openai-compat", "anthropic": "anthropic"}[rc.api_style]
        base = rc.base_url if rc.api_style == "anthropic" else rc.openai_base
        cfg = {"$schema": "https://charm.land/crush.json",
               "providers": {"bench": {"type": ptype, "base_url": base, "api_key": "proxy-injects-the-key",
                                       "models": [{"id": rc.model, "name": rc.display_name, "context_window": rc.ctx,
                                                   "default_max_tokens": rc.max_tokens,
                                                   "can_reason": bool(rc.reasoning) and not rc.local}]}},
               "models": {"large": {"model": rc.model, "provider": "bench"},
                          "small": {"model": rc.model, "provider": "bench"}},
               "options": {"disable_metrics": True, "disable_provider_auto_update": True},
               "permissions": {"allowed_tools": ["bash", "edit", "multiedit", "write", "view", "ls", "grep", "glob",
                                                 "diagnostics", "todos", "agent", "job_output", "job_kill"]}}
        return {".config/crush/crush.json": json.dumps(cfg, indent=2)}

    def command(self, rc, stage, n_stages):
        cont = " --continue" if stage > 1 else ""
        return f"crush run --quiet -c {WORKSPACE}{cont} \"$PROMPT\""


class Custom(Harness):
    """User-defined harness from a manifest: install lines plus templated files, env and command.

    Placeholders: {model} {base_url} {openai_base_url} {api_style} {ctx} {max_tokens} {reasoning} {session_id}
    {stage} {home} {workspace}; the prompt is "$PROMPT"."""
    builtin = False

    def __init__(self, m):
        self.m = m
        self.id, self.name, self.version = m["id"], m["name"], m.get("version") or "custom"
        self.homepage, self.license = m.get("homepage", ""), m.get("license", "")
        self.description = m.get("description", "")
        self.apis = m.get("apis") or ["openai-chat"]
        self.multi_stage = m.get("multi_stage", "fresh")
        self.tool_style = m.get("tool_style", "native")
        self.caveats = ["custom harness: results depend on your manifest"]

    def _fmt(self, s, rc, stage=1):
        vals = {"model": rc.model, "base_url": rc.base_url, "openai_base_url": rc.openai_base, "api_style": rc.api_style,
                "ctx": rc.ctx, "max_tokens": rc.max_tokens, "reasoning": rc.reasoning or "", "session_id": rc.session_id,
                "stage": stage, "home": HOME, "workspace": WORKSPACE}
        return re.sub(r"\{(\w+)\}", lambda m_: str(vals.get(m_.group(1), m_.group(0))), s)

    def install(self):
        return [line for line in self.m.get("install", []) if line.strip()]

    def files(self, rc):
        return {k: self._fmt(v, rc) for k, v in (self.m.get("files") or {}).items()}

    def env(self, rc):
        return {k: self._fmt(v, rc) for k, v in (self.m.get("env") or {}).items()}

    def command(self, rc, stage, n_stages):
        tpl = self.m.get("continue_command") if stage > 1 and self.m.get("continue_command") else self.m["command"]
        return self._fmt(tpl, rc, stage)


BUILTIN = [Pi(), OpenCode(), Codex(), QwenCode(), Crush(), Aider(), MiniSwe()]
BY_ID = {h.id: h for h in BUILTIN}

MANIFEST_SCHEMA = {
    "id": "lowercase id, letters/digits/dashes", "name": "display name", "version": "pinned version string",
    "install": ["Dockerfile lines, e.g. RUN npm_config_offline=false npm install -g my-agent@1.2.3"],
    "files": {".config/my-agent/config.json": "{\"baseUrl\": \"{openai_base_url}\", \"model\": \"{model}\"}"},
    "env": {"OPENAI_BASE_URL": "{openai_base_url}", "OPENAI_API_KEY": "proxy-injects-the-key"},
    "command": "my-agent --yes --model {model} \"$PROMPT\"", "continue_command": "optional, used for stages 2+",
    "apis": ["openai-chat"], "multi_stage": "fresh | resume", "tool_style": "native | text",
}


def validate_manifest(m):
    errs = []
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,40}", m.get("id", "")):
        errs.append("id must be 2-41 lowercase letters, digits or dashes")
    if m.get("id") in BY_ID:
        errs.append("id clashes with a built-in harness")
    if not m.get("name"):
        errs.append("name is required")
    if not m.get("command") or "$PROMPT" not in m["command"]:
        errs.append('command is required and must contain "$PROMPT"')
    for line in m.get("install", []):
        if line.strip() and not re.match(r"^(RUN|ENV|ARG|COPY|ADD|WORKDIR|USER|LABEL)\b", line.strip()):
            errs.append(f"install line must be a Dockerfile instruction: {line[:60]}")
    bad = set(m.get("apis") or []) - {"openai-chat", "openai-responses", "anthropic"}
    if bad:
        errs.append(f"unknown api styles: {', '.join(sorted(bad))}")
    if m.get("multi_stage", "fresh") not in ("fresh", "resume"):
        errs.append("multi_stage must be fresh or resume")
    for path in (m.get("files") or {}):
        if path.startswith("/") or ".." in path:
            errs.append(f"file paths are relative to the agent HOME: {path}")
    return errs


def get(harness_id, custom=None):
    if harness_id in BY_ID:
        return BY_ID[harness_id]
    for m in custom or []:
        if m["id"] == harness_id:
            return Custom(m)
    raise KeyError(harness_id)


def choose_api(harness, provider_styles, preferred=None):
    """Pick the API style both sides support: the provider's preferred style first."""
    order = [preferred] if preferred else []
    order += ["anthropic", "openai-responses", "openai-chat"]
    for s in order:
        if s and s in harness.apis and s in provider_styles:
            return s
    return None
