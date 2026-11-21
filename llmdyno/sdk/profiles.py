# pyright: strict, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false
"""LLM profiles: a model plus the exact settings it is benchmarked with. cloud_model() and local_model() make them."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Union

from ..errors import ConflictError, LLMDynoError, NotFoundError
from ._core import Handle, Job, say, call, covers

__all__ = ["Profile", "list_profiles", "profile", "cloud_model", "local_model", "import_profile",
           "profile_defaults"]


ENV_KEYS = {
    "openai": ["OPENAI_API_KEY"], "anthropic": ["ANTHROPIC_API_KEY"], "google": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"], "moonshot": ["MOONSHOT_API_KEY"], "zai": ["ZAI_API_KEY"],
    "qwen": ["DASHSCOPE_API_KEY"], "minimax": ["MINIMAX_API_KEY"], "xai": ["XAI_API_KEY"],
    "mistral": ["MISTRAL_API_KEY"], "openrouter": ["OPENROUTER_API_KEY"], "groq": ["GROQ_API_KEY"],
    "together": ["TOGETHER_API_KEY"], "fireworks": ["FIREWORKS_API_KEY"], "cerebras": ["CEREBRAS_API_KEY"],
    "litellm": ["LITELLM_API_KEY", "LITELLM_MASTER_KEY"],
}
LOCAL_PARAM_NAMES = {"ctx", "gpu_layers", "auto_fit", "fit_margin_mib", "n_cpu_moe", "flash_attn", "cache_k", "cache_v",
                     "threads", "batch", "ubatch", "parallel", "mlock", "no_mmap", "swa_full", "thinking",
                     "template_kwargs", "reasoning_budget", "max_output_tokens", "extra_args"}
SAMPLING_NAMES = {"temperature", "top_p", "top_k", "min_p", "repeat_penalty", "presence_penalty"}
CLOUD_PARAM_NAMES = {"ctx", "max_output_tokens", "reasoning_effort", "temperature", "top_p", "api_style", "extra_body"}


class Profile(Handle):
    """A model plus the settings it is benchmarked with (the app's "LLM profile"). Get one from cloud_model(),
    local_model() or profile(name); list_profiles() lists them all."""

    _get_op, _id_arg = "profiles.get_profile", "pid"

    @property
    def name(self) -> str:
        return self._data["name"]

    @property
    def kind(self) -> str:
        """"local" (llama.cpp on this machine) or "cloud"."""
        return self._data["kind"]

    @property
    def params(self) -> dict[str, Any]:
        return dict(self._data.get("params") or {})

    @property
    def info(self) -> dict[str, Any]:
        """Everything the app knows about the profile (model, provider, last test, …)."""
        return self.to_dict()

    @covers("GET /api/profiles/{pid}")
    def refresh(self) -> "Profile":
        return super().refresh()

    def __repr__(self):
        d = self._data
        what = d.get("remote_model") or ((d.get("model") or {}).get("name")) or ""
        return f"<llmdyno.Profile {self.name!r} {self.kind} {what}>"

    # -- actions
    @covers("PATCH /api/profiles/{pid}")
    def update(self, *, name: str | None = None, notes: str | None = None, tags: list[Any] | None = None,
               pricing: dict[str, Any] | None = None, remote_model: str | None = None, **params: Any) -> "Profile":
        """Change settings, e.g. update(ctx=32768, cache_k="q4_0") or update(reasoning_effort="high"), and the
        name, notes, tags, pricing ({"input", "output", "cached"} USD per 1M tokens) or a cloud profile's model."""
        body = {k: v for k, v in (("name", name), ("notes", notes), ("tags", tags), ("pricing", pricing),
                                  ("remote_model", remote_model)) if v is not None}
        if params:
            body["params"] = profile_params(self.kind, params)
        self._d = call("profiles.patch_profile", pid=self.id, body=body)
        return self

    @covers("POST /api/profiles/check")
    def check(self, exact: bool = False) -> dict[str, Any]:
        """Memory fit for a local profile: verdict ("fits", "tight", "spill", "oom", …), projected GPU memory and
        warnings. exact=True asks llama-fit-params instead of estimating (needs llama.cpp and the downloaded file)."""
        if self.kind != "local":
            raise LLMDynoError("memory checks are for local profiles")
        return call("profiles.check_profile", body={"model_id": self._data["model_id"], "params": self.params,
                                                    "exact": exact, "profile_id": self.id})

    @covers("POST /api/profiles/{pid}/smoke")
    def test(self, quiet: bool = False) -> dict[str, Any]:
        """Quick test (about 20 s locally): loads the model, measures speed and VRAM, and checks tool calling."""
        res = Job(call("profiles.smoke_profile", pid=self.id)["job_id"]).wait(quiet=quiet)
        self.refresh()
        return res

    @covers("DELETE /api/profiles/{pid}")
    def delete(self) -> None:
        call("profiles.delete_profile", pid=self.id)

    @covers("POST /api/profiles/{pid}/duplicate")
    def duplicate(self, name: str | None = None, **params: Any) -> "Profile":
        """A copy ("<name> (copy)" unless you name it), optionally with changed settings."""
        copy = Profile(call("profiles.duplicate_profile", pid=self.id))
        patch = {}
        if name:
            patch["name"] = name
        if params:
            patch["params"] = profile_params(self.kind, params)
        return Profile(call("profiles.patch_profile", pid=copy.id, body=patch)) if patch else copy

    @covers("GET /api/profiles/{pid}/export")
    def export(self, path: Union[str, Path, None] = None) -> dict[str, Any]:
        """The profile as a shareable file (settings, pricing and which model or vendor, never keys); written to
        path if given. import_profile() reads it back, here or on another machine."""
        d = call("profiles.export_profile", pid=self.id)
        if path:
            Path(path).write_text(d["content"], encoding="utf-8")
        return json.loads(d["content"])


def profile_params(kind: str, given: dict[str, Any]) -> dict[str, Any]:
    """Library keyword arguments -> the profile params dict (unknown names are rejected, not ignored)."""
    out: dict[str, Any] = {}
    sampling: dict[str, Any] = {}
    allowed = LOCAL_PARAM_NAMES if kind == "local" else CLOUD_PARAM_NAMES
    for k, v in given.items():
        if v is None:
            continue
        if kind == "local" and k in SAMPLING_NAMES:
            sampling[k] = v
        elif k == "kv_cache" and kind == "local":
            out["cache_k"] = out["cache_v"] = v
        elif k in allowed:
            out[k] = v
        else:
            raise TypeError(f"unknown {kind} setting {k!r}; known: {', '.join(sorted(allowed | (SAMPLING_NAMES if kind == 'local' else set())))}")
    if sampling:
        out["sampling"] = sampling
    return out


_params = profile_params        # the 0.3 name, kept for code that used it


def _profile_rows():
    return call("profiles.list_profiles")


@covers("GET /api/profiles")
def list_profiles(kind: str | None = None) -> list[Any]:
    """Every profile in the data folder (optionally only "local" or "cloud")."""
    return [Profile(p) for p in _profile_rows() if kind in (None, p["kind"])]


def profile(name_or_id: Union[str, Profile]) -> Profile:
    """A profile by id or by exact name (case-insensitive)."""
    if isinstance(name_or_id, Profile):
        return name_or_id
    rows = _profile_rows()
    hit = [p for p in rows if p["id"] == name_or_id] or [p for p in rows if p["name"].lower() == str(name_or_id).lower()]
    if not hit:
        names = ", ".join(repr(p["name"]) for p in rows[:12])
        raise NotFoundError(f"no profile {name_or_id!r}" + (f"; there are: {names}" if names else ""))
    if len(hit) > 1:
        raise ConflictError(f"{len(hit)} profiles are called {name_or_id!r}; use the id")
    return Profile(hit[0])


def _upsert_profile(body: dict[str, Any]) -> Profile:
    """Create the profile, or update the one with the same name: calling cloud_model() or local_model() twice
    with the same arguments gives the same profile instead of piling up copies."""
    same = [p for p in _profile_rows() if p["name"].lower() == body["name"].lower()]
    if same:
        p = same[0]
        if p["kind"] != body["kind"]:
            raise ConflictError(f"a {p['kind']} profile is already called {body['name']!r}; pass another name=")
        patch = {"params": body.get("params") or {}}
        for k in ("pricing", "remote_model"):
            if body.get(k) is not None:
                patch[k] = body[k]
        if body["kind"] == "local" and body.get("model_id") != p.get("model_id"):
            raise ConflictError(f"profile {body['name']!r} uses another model file; pass another name=")
        if body["kind"] == "cloud" and body.get("provider_id") != p.get("provider_id"):
            raise ConflictError(f"profile {body['name']!r} uses another provider; pass another name=")
        return Profile(call("profiles.patch_profile", pid=p["id"], body=patch))
    return Profile(call("profiles.create_profile", body=body))


# ------------------------------------------------------------------ cloud
@covers("POST /api/profiles")
def cloud_model(vendor: str, model: str, *, api_key: str | None = None, name: str | None = None,
                base_url: str | None = None, api_style: str | None = None, budget_usd: float | None = None,
                pricing: Union[str, dict[str, Any], None] = "auto", **params: Any) -> Profile:
    """A cloud model to benchmark, e.g. cloud_model("anthropic", "claude-sonnet-5-5", reasoning_effort="low").

    vendor: openai, anthropic, google, deepseek, moonshot, zai, qwen, minimax, xai, mistral, openrouter, groq, together,
    fireworks, cerebras, litellm (a LiteLLM proxy: see litellm_model()), or custom (any OpenAI-compatible base_url,
    such as Ollama or vLLM: see ollama_model() and openai_compatible()).
    api_key: stored encrypted in the data folder; when omitted, the saved key or the usual environment variable
    (OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, …) is used. The key only ever reaches LLMDyno's proxy.
    budget_usd: hard spend cap for this provider (new providers default to $5).
    pricing: "auto" looks the model up in OpenRouter's catalog; or {"input": $, "output": $, "cached": $} per 1M tokens.
    Other keywords are profile settings: ctx, max_output_tokens, reasoning_effort, temperature, top_p, api_style,
    extra_body."""
    vendors = {v["id"]: v for v in call("providers.list_vendors")}
    v = vendors.get(vendor)
    if not v:
        raise LLMDynoError(f"unknown vendor {vendor!r}; one of: {', '.join(vendors)}")
    if vendor == "custom" and not base_url:  # litellm has a default (a proxy on this machine's port 4000)
        raise LLMDynoError("a custom provider needs base_url=, e.g. http://host.docker.internal:11434/v1 for Ollama")
    key = api_key or next((os.environ[e] for e in ENV_KEYS.get(vendor, []) if os.environ.get(e)), None)
    provs = [p for p in call("providers.list_providers")
             if p["vendor"] == vendor and (not base_url or p["base_url"] == base_url)]
    if provs:
        prov = provs[0]
        patch = {}
        if budget_usd is not None and float(budget_usd) != prov["budget_usd"]:
            patch["budget_usd"] = float(budget_usd)
        if api_style and api_style != prov["api_style"]:
            patch["api_style"] = api_style
        if patch:
            prov = call("providers.patch_provider", pid=prov["id"], body=patch)
        if key:                                   # the given or environment key wins over a saved one
            prov = call("providers.set_provider_key", pid=prov["id"], body={"api_key": key})
    else:
        body = {"vendor": vendor, "base_url": base_url, "api_style": api_style, "api_key": key,
                "budget_usd": 5 if budget_usd is None else budget_usd}
        prov = call("providers.create_provider", body={k: v_ for k, v_ in body.items() if v_ is not None})
    if not v.get("key_optional") and not prov.get("has_key"):
        envs = " or ".join(ENV_KEYS.get(vendor, [])) or "an environment variable"
        raise LLMDynoError(f"no API key for {v['name']}: pass api_key= or set {envs}")
    if pricing == "auto":
        hit = (call("providers.pricing_lookup", vendor=vendor, model=model).get("match")
               if vendor != "custom" else None)
        pricing = {k: hit.get(k) for k in ("input", "output", "cached") if hit.get(k) is not None} if hit else {}
    effort = params.get("reasoning_effort")
    default_name = f"{model} · {v['name'].split(' (')[0]}" + (f" · {effort}" if effort else "")
    return _upsert_profile({"kind": "cloud", "name": name or default_name, "provider_id": prov["id"],
                            "remote_model": model, "params": profile_params("cloud", params), "pricing": pricing or {}})


# ------------------------------------------------------------------ local
@covers("POST /api/profiles")
def local_model(repo: str | None = None, *, quant: str | None = None, path: Union[str, Path, None] = None,
                name: str | None = None, download: bool = True, quiet: bool = False, **params: Any) -> Profile:
    """A GGUF model run by llama.cpp on this machine.

    From Hugging Face: local_model("unsloth/Qwen3.8-27B-GGUF", quant="UD-Q3_K_XL", ctx=49152) downloads the file
    (resumable, checksum-verified) unless it is already in the data folder; download=False only uses what is there.
    From disk: local_model(path="D:/models/qwen.gguf") registers the file where it is (no copy).
    Other keywords are profile settings: ctx, cache_k / cache_v (or kv_cache for both), gpu_layers, n_cpu_moe,
    flash_attn, thinking, max_output_tokens, temperature, top_p, top_k, min_p, …"""
    if bool(repo) == bool(path):
        raise LLMDynoError("pass either a Hugging Face repo or path=")
    if path is not None:
        m = _model_from_path(Path(path).expanduser(), quant)
    else:
        m = _model_from_repo(repo, quant, download, quiet)
    return local_profile(call("models.model_detail", mid=m["id"]), name, params, quiet)


def local_profile(m: dict[str, Any], name: Any, params: Any, quiet: Any) -> Profile:
    given = profile_params("local", params)
    ctx = given.get("ctx")
    default_name = m["name"] + (f" · {ctx // 1024}k" if ctx else "")
    prof = _upsert_profile({"kind": "local", "name": name or default_name, "model_id": m["id"], "params": given})
    try:
        verdict = prof.check()
        if verdict.get("verdict") in ("oom", "spill"):
            say(quiet, f"warning: {prof.name} is projected not to fit ({verdict['verdict']}); "
                        "check() shows the details and fixes")
    except LLMDynoError:
        pass
    return prof


def _model_from_path(p: Path, quant: Any):
    if not p.exists():
        raise NotFoundError(f"{p} does not exist")
    folder = p.parent if p.is_file() else p
    call("models.model_import", body={"folder": str(folder)})
    here = [m for m in call("models.list_models") if Path(m["local_dir"]).resolve() == folder.resolve()]
    if p.is_file():
        here = [m for m in here if p.name in m["files"] or Path(m["files"][0]).name == p.name]
    elif quant:
        here = [m for m in here if (m["quant"] or "").lower() == quant.lower()]
    if not here:
        raise NotFoundError(f"no readable GGUF model in {p}")
    if len(here) > 1:
        raise ConflictError(f"{len(here)} models in {p}: pass the file path or quant= ({', '.join(m['quant'] for m in here)})")
    return here[0]


def _model_from_repo(repo: Any, quant: Any, download: Any, quiet: Any):
    from .models import Model, download_model

    def match(m: Any):
        return not quant or (m["quant"] or "").lower() == quant.lower() or quant.lower() in (m["name"] or "").lower()
    mine = [m for m in call("models.list_models") if m["repo"] == repo and match(m)]
    ready = [m for m in mine if m["status"] == "ready"]
    if ready:
        return ready[0]
    if not download:
        raise NotFoundError(f"{repo} {quant or ''} is not downloaded (pass download=True)".replace("  ", " "))
    if mine:                                              # an interrupted download: carry on
        say(quiet, f"Resuming download of {repo} {mine[0]['quant']}")
        return Model(mine[0]).resume(quiet=quiet).to_dict()
    return download_model(repo, quant, quiet=quiet).to_dict()


# ------------------------------------------------------------------ sharing and defaults
@covers("POST /api/profiles/import")
def import_profile(source: Union[str, Path, dict[str, Any]]) -> Profile:
    """Create a profile from an exported profile file (a path or the dict Profile.export() returned). Its model
    must already be downloaded here, or a provider of its vendor added, first."""
    body = source if isinstance(source, dict) else json.loads(Path(source).expanduser().read_text(encoding="utf-8"))
    return Profile(call("profiles.import_profile", body=body))


@covers("GET /api/profiles/defaults")
def profile_defaults(kind: str = "local", model: Any=None) -> dict[str, Any]:
    """The settings a new profile starts from: for "local", tuned to a model (Model, id or name) and this machine;
    for "cloud", the cloud defaults."""
    mid = None
    if model is not None:
        from .models import model as find_model
        mid = find_model(model).id
    return call("profiles.profile_defaults", kind=kind, model_id=mid)
