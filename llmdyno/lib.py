"""LLMDyno as a Python library.

    import llmdyno

    gpt = llmdyno.cloud_model("openai", "gpt-6-luna", reasoning_effort="low", budget_usd=2)
    qwen = llmdyno.local_model("unsloth/Qwen3.8-27B-GGUF", quant="UD-Q3_K_XL", ctx=49152)
    results = llmdyno.bench([gpt, qwen], benchmarks="suite_quick", harnesses="pi")
    print(results)

Everything goes through the same engine, data folder and database as the web app, so a plan started from Python shows
up in the dashboard (`llmdyno.serve()` or `results.open()`), and profiles made in the UI can be used from Python.
Long operations (downloads, image builds, plans) block and print progress by default; Ctrl+C cancels them cleanly.
"""
from __future__ import annotations

import atexit
import csv
import io
import json
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Sequence, Union

__all__ = [
    "LLMDynoError", "NotFoundError", "ConflictError", "PreflightError", "Profile", "Plan", "Results", "Doctor",
    "init", "data_dir", "doctor", "setup", "cloud_model", "local_model", "list_profiles", "profile", "list_benchmarks",
    "list_suites", "import_swebench", "import_polyglot", "preflight", "bench", "list_plans", "plan", "results", "review",
    "serve",
]

ENV_KEYS = {
    "openai": ["OPENAI_API_KEY"], "anthropic": ["ANTHROPIC_API_KEY"], "google": ["GEMINI_API_KEY", "GOOGLE_API_KEY"],
    "deepseek": ["DEEPSEEK_API_KEY"], "moonshot": ["MOONSHOT_API_KEY"], "zai": ["ZAI_API_KEY"],
    "qwen": ["DASHSCOPE_API_KEY"], "minimax": ["MINIMAX_API_KEY"], "xai": ["XAI_API_KEY"],
    "mistral": ["MISTRAL_API_KEY"], "openrouter": ["OPENROUTER_API_KEY"], "groq": ["GROQ_API_KEY"],
    "together": ["TOGETHER_API_KEY"], "fireworks": ["FIREWORKS_API_KEY"], "cerebras": ["CEREBRAS_API_KEY"],
}
LOCAL_PARAM_NAMES = {"ctx", "gpu_layers", "auto_fit", "fit_margin_mib", "n_cpu_moe", "flash_attn", "cache_k", "cache_v",
                     "threads", "batch", "ubatch", "parallel", "mlock", "no_mmap", "swa_full", "thinking",
                     "template_kwargs", "reasoning_budget", "max_output_tokens", "extra_args"}
SAMPLING_NAMES = {"temperature", "top_p", "top_k", "min_p", "repeat_penalty", "presence_penalty"}
CLOUD_PARAM_NAMES = {"ctx", "max_output_tokens", "reasoning_effort", "temperature", "top_p", "api_style", "extra_body"}
TERMINAL = ("done", "failed", "cancelled", "paused")


# ================================================================== errors
class LLMDynoError(Exception):
    """Anything LLMDyno refuses or fails to do; the message says why and usually what to change."""


class NotFoundError(LLMDynoError, LookupError):
    pass


class ConflictError(LLMDynoError):
    pass


class PreflightError(LLMDynoError):
    """A plan cannot start. `problems` are the blocking items, `warnings` the rest of the preflight report."""

    def __init__(self, problems, warnings=None, report=None):
        self.problems, self.warnings, self.report = list(problems), list(warnings or []), report or {}
        super().__init__("the plan cannot start:\n  - " + "\n  - ".join(self.problems))


def _call(fn, *args, **kwargs):
    """Run an API function and turn its HTTP errors into library errors."""
    from fastapi import HTTPException
    try:
        return fn(*args, **kwargs)
    except HTTPException as e:
        cls = {404: NotFoundError, 409: ConflictError}.get(e.status_code, LLMDynoError)
        raise cls(str(e.detail)) from None


# ================================================================== data folder and start-up
_state = {"ready": False}
_init_lock = threading.Lock()


def init(data_dir: Union[str, Path, None] = None) -> Path:
    """Open (and create if needed) a data folder. Optional: without it LLMDyno uses LLMDYNO_DATA or the default
    folder (./data in a git checkout, otherwise %LOCALAPPDATA%\\LLMDyno, ~/Library/Application Support/LLMDyno or
    ~/.local/share/llmdyno). Call it again with another folder to switch."""
    from . import config, db
    with _init_lock:
        if data_dir is not None:
            config.set_data_dir(data_dir)
        db.init()
        _state["ready"] = True
        _register_exit_hook()
    return config.DATA


def _ready():
    if not _state["ready"]:
        init()


def data_dir() -> Path:
    """The data folder in use (models, runs, database, keys)."""
    from . import config
    return config.DATA


_exit_hook = {"done": False}


def _register_exit_hook():
    if _exit_hook["done"]:
        return
    _exit_hook["done"] = True

    def stop():
        try:
            from .inference import llamacpp
            llamacpp.server.stop(force=True)
        except Exception:  # noqa: BLE001 - best effort at interpreter exit
            pass
    atexit.register(stop)


# ================================================================== waiting for jobs
def _say(quiet, msg):
    if not quiet:
        try:
            print(msg, flush=True)
        except UnicodeEncodeError:            # a console code page without · or …
            enc = getattr(sys.stdout, "encoding", None) or "ascii"
            print(msg.encode(enc, "replace").decode(enc), flush=True)


def _wait_job(job_id: str, quiet: bool = False, verbose: bool = False, every_s: float = 2.0) -> dict:
    """Block until a background job ends, printing its progress. Ctrl+C cancels the job and re-raises."""
    from . import db, jobs
    seen, last_detail, last_print = 0, None, 0.0
    try:
        while True:
            with db.Session() as s:
                j = db.row(s.get(db.Job, job_id))
            log = j.get("log") or ""
            if verbose and not quiet:
                if len(log) < seen:
                    seen = 0                                   # the stored log keeps a tail only
                for line in log[seen:].splitlines():
                    _say(False, "    " + line)
                seen = len(log)
            detail = j.get("detail") or ""
            if not quiet and detail and detail != last_detail and time.time() - last_print >= every_s:
                pct = f"{int((j.get('progress') or 0) * 100):>3}% " if j.get("progress") else ""
                _say(False, f"  {pct}{j['title']}: {detail}")
                last_detail, last_print = detail, time.time()
            if j["status"] in TERMINAL:
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        _say(quiet, f"  cancelling {j['title']} …")
        jobs.cancel(job_id)
        _drain(job_id)
        raise
    if j["status"] == "failed":
        tail = "\n".join(ln for ln in (j.get("log") or "").splitlines()[-12:] if ln.strip())
        raise LLMDynoError(f"{j['title']} failed: {j.get('detail')}\n{tail}".rstrip())
    if j["status"] in ("cancelled", "paused"):
        raise LLMDynoError(f"{j['title']} was {j['status']}")
    return j.get("result") or {}


def _drain(job_id, timeout_s=120):
    from . import db
    end = time.time() + timeout_s
    while time.time() < end:
        with db.Session() as s:
            if s.get(db.Job, job_id).status in TERMINAL:
                return
        time.sleep(0.5)


# ================================================================== setup
class Doctor(list):
    """The Setup page's checks as a list of dicts; prints as a table. `ok` is True when nothing required is missing."""

    @property
    def ok(self) -> bool:
        return all(d["ok"] for d in self if d["level"] == "required")

    @property
    def missing(self) -> list:
        return [d for d in self if not d["ok"]]

    def __str__(self):
        lines = []
        for d in self:
            mark = "ok " if d["ok"] else ("!! " if d["level"] == "required" else "-- ")
            lines.append(f"{mark}{d['name']:<24} {d['level']:<26} {d['detail']}")
        return "\n".join(lines)

    def __repr__(self):
        return f"<llmdyno.Doctor ok={self.ok} missing={[d['id'] for d in self.missing]}>"


def doctor() -> Doctor:
    """System and dependency checks (Docker, images, llama.cpp, harnesses, SWE-bench harness, …)."""
    _ready()
    from .system import deps
    return Doctor(deps.check(force=True))


def setup(harnesses: Union[str, Sequence[str]] = ("pi",), *, quality: bool = True,
          llama_cpp: Union[bool, str] = True, swebench: bool = False, polyglot: bool = False,
          quiet: bool = False, verbose: bool = False) -> Doctor:
    """Install what benchmarks need, skipping what is already there: the sandbox image, the code-quality image,
    harness images, a llama.cpp build for this machine (True picks the best one; or pass a variant such as "cuda-13",
    "metal", "vulkan", "cpu"), and optionally the SWE-bench harness and the polyglot toolchain image.
    These download several GB the first time. Docker must be running."""
    _ready()
    from .api import external_api, routes
    from .harnesses import catalog, images
    from .inference import llamacpp
    from .system import specs
    if not specs.detect(force=True)["docker"].get("running"):
        raise LLMDynoError("Docker is not running: start Docker Desktop (or the docker service) and try again")
    todo = []
    if not images.image_exists(images.SANDBOX):
        todo.append(("Sandbox image", lambda: routes.dep_action("sandbox_image", {"action": "build_sandbox"})))
    if quality and not images.image_exists(images.QUALITY):
        todo.append(("Code-quality image", lambda: routes.dep_action("quality_image", {"action": "build_quality"})))
    for hid in ([harnesses] if isinstance(harnesses, str) else list(harnesses or [])):
        h = catalog.get(hid, images.custom_manifests())
        if not images.image_exists(h.image()):
            todo.append((f"{h.name} harness", lambda h=h: routes.build_harness(h.id)))
    if llama_cpp and not llamacpp.installed()["installed"]:
        variant = llama_cpp if isinstance(llama_cpp, str) else next(
            (v["id"] for v in llamacpp.variants() if v.get("ok")), "cpu")
        todo.append((f"llama.cpp ({variant})", lambda v=variant: routes.dep_action(
            "llama_cpp", {"action": "install_llama", "variant": v})))
    if swebench:
        from .benchmarks import swebench as swe
        if not swe.harness_python().exists():
            todo.append(("SWE-bench harness", external_api.install_swebench_harness))
    if polyglot:
        from .benchmarks import polyglot as pg
        if not images.image_exists(pg.IMAGE):
            if not pg.context_ready():
                todo.append(("Aider polyglot exercises", lambda: external_api.import_polyglot({})))
            todo.append(("Polyglot toolchain image", external_api.build_polyglot_image))
    for label, start in todo:
        _say(quiet, f"Setting up: {label}")
        r = _call(start)
        _wait_job(r["job_id"], quiet=quiet, verbose=verbose)
    if not todo:
        _say(quiet, "Everything requested is already set up.")
    return doctor()


# ================================================================== profiles
class Profile:
    """A model plus the settings it is benchmarked with (the app's "LLM profile"). Get one from cloud_model(),
    local_model() or profile(name); list_profiles() lists them all."""

    def __init__(self, data: dict):
        self._d = data

    # -- basics
    @property
    def id(self) -> str:
        return self._d["id"]

    @property
    def name(self) -> str:
        return self._d["name"]

    @property
    def kind(self) -> str:
        """"local" (llama.cpp on this machine) or "cloud"."""
        return self._d["kind"]

    @property
    def params(self) -> dict:
        return dict(self._d.get("params") or {})

    @property
    def info(self) -> dict:
        """Everything the app knows about the profile (model, provider, last test, …)."""
        return dict(self._d)

    def refresh(self) -> "Profile":
        from .api import routes
        self._d = _call(routes.get_profile, self.id)
        return self

    def __repr__(self):
        what = self._d.get("remote_model") or ((self._d.get("model") or {}).get("name")) or ""
        return f"<llmdyno.Profile {self.name!r} {self.kind} {what}>"

    def __eq__(self, other):
        return isinstance(other, Profile) and other.id == self.id

    def __hash__(self):
        return hash(self.id)

    # -- actions
    def update(self, **params) -> "Profile":
        """Change settings, e.g. update(ctx=32768, cache_k="q4_0") or update(reasoning_effort="high")."""
        from .api import routes
        body = {"params": _params(self.kind, params)}
        self._d = _call(routes.patch_profile, self.id, body)
        return self

    def check(self, exact: bool = False) -> dict:
        """Memory fit for a local profile: verdict ("fits", "tight", "spill", "oom", …), projected GPU memory and
        warnings. exact=True asks llama-fit-params instead of estimating (needs llama.cpp and the downloaded file)."""
        if self.kind != "local":
            raise LLMDynoError("memory checks are for local profiles")
        _ready()
        from .api import routes
        return _call(routes.check_profile, {"model_id": self._d["model_id"], "params": self.params, "exact": exact,
                                            "profile_id": self.id})

    def test(self, quiet: bool = False) -> dict:
        """Quick test (about 20 s locally): loads the model, measures speed and VRAM, and checks tool calling."""
        from .api import routes
        r = _call(routes.smoke_profile, self.id)
        res = _wait_job(r["job_id"], quiet=quiet)
        self.refresh()
        return res

    def delete(self) -> None:
        from .api import routes
        _call(routes.delete_profile, self.id)


def _params(kind, given):
    """Library keyword arguments -> the profile params dict (unknown names are rejected, not ignored)."""
    out, sampling = {}, {}
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


def _profile_rows():
    _ready()
    from .api import routes
    return routes.list_profiles()


def list_profiles(kind: str | None = None) -> list:
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


def _upsert_profile(body: dict) -> Profile:
    """Create the profile, or update the one with the same name: calling cloud_model() or local_model() twice
    with the same arguments gives the same profile instead of piling up copies."""
    from .api import routes
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
        return Profile(_call(routes.patch_profile, p["id"], patch))
    return Profile(_call(routes.create_profile, body))


# ------------------------------------------------------------------ cloud
def cloud_model(vendor: str, model: str, *, api_key: str | None = None, name: str | None = None,
                base_url: str | None = None, api_style: str | None = None, budget_usd: float | None = None,
                pricing: Union[str, dict, None] = "auto", **params) -> Profile:
    """A cloud model to benchmark, e.g. cloud_model("anthropic", "claude-sonnet-5-5", reasoning_effort="low").

    vendor: openai, anthropic, google, deepseek, moonshot, zai, qwen, minimax, xai, mistral, openrouter, groq, together,
    fireworks, cerebras, or custom (any OpenAI-compatible base_url, such as Ollama or vLLM).
    api_key: stored encrypted in the data folder; when omitted, the saved key or the usual environment variable
    (OPENAI_API_KEY, ANTHROPIC_API_KEY, GEMINI_API_KEY, …) is used. The key only ever reaches LLMDyno's proxy.
    budget_usd: hard spend cap for this provider (new providers default to $5).
    pricing: "auto" looks the model up in OpenRouter's catalog; or {"input": $, "output": $, "cached": $} per 1M tokens.
    Other keywords are profile settings: ctx, max_output_tokens, reasoning_effort, temperature, top_p, api_style,
    extra_body."""
    _ready()
    from . import secrets
    from .api import routes
    from .providers import registry as providers
    v = providers.BY_ID.get(vendor)
    if not v:
        raise LLMDynoError(f"unknown vendor {vendor!r}; one of: {', '.join(providers.BY_ID)}")
    if vendor == "custom" and not base_url:
        raise LLMDynoError("a custom provider needs base_url=, e.g. http://host.docker.internal:11434/v1 for Ollama")
    key = api_key or next((os.environ[e] for e in ENV_KEYS.get(vendor, []) if os.environ.get(e)), None)
    provs = [p for p in routes.list_providers() if p["vendor"] == vendor and (not base_url or p["base_url"] == base_url)]
    if provs:
        prov = provs[0]
        patch = {}
        if budget_usd is not None and float(budget_usd) != prov["budget_usd"]:
            patch["budget_usd"] = float(budget_usd)
        if api_style and api_style != prov["api_style"]:
            patch["api_style"] = api_style
        if patch:
            prov = _call(routes.patch_provider, prov["id"], patch)
        if key and secrets.get(providers.secret_name(prov["id"])) != key:
            prov = _call(routes.set_provider_key, prov["id"], {"api_key": key})
    else:
        body = {"vendor": vendor, "base_url": base_url, "api_style": api_style, "api_key": key,
                "budget_usd": 5 if budget_usd is None else budget_usd}
        prov = _call(routes.create_provider, {k: v_ for k, v_ in body.items() if v_ is not None})
    if vendor != "custom" and not prov.get("has_key"):
        envs = " or ".join(ENV_KEYS.get(vendor, [])) or "an environment variable"
        raise LLMDynoError(f"no API key for {v['name']}: pass api_key= or set {envs}")
    if pricing == "auto":
        hit = providers.lookup_price(vendor, model) if vendor != "custom" else None
        pricing = {k: hit.get(k) for k in ("input", "output", "cached") if hit and hit.get(k) is not None} if hit else {}
    effort = params.get("reasoning_effort")
    default_name = f"{model} · {v['name'].split(' (')[0]}" + (f" · {effort}" if effort else "")
    return _upsert_profile({"kind": "cloud", "name": name or default_name, "provider_id": prov["id"],
                            "remote_model": model, "params": _params("cloud", params), "pricing": pricing or {}})


# ------------------------------------------------------------------ local
def local_model(repo: str | None = None, *, quant: str | None = None, path: Union[str, Path, None] = None,
                name: str | None = None, download: bool = True, quiet: bool = False, **params) -> Profile:
    """A GGUF model run by llama.cpp on this machine.

    From Hugging Face: local_model("unsloth/Qwen3.8-27B-GGUF", quant="UD-Q3_K_XL", ctx=49152) downloads the file
    (resumable, checksum-verified) unless it is already in the data folder; download=False only uses what is there.
    From disk: local_model(path="D:/models/qwen.gguf") registers the file where it is (no copy).
    Other keywords are profile settings: ctx, cache_k / cache_v (or kv_cache for both), gpu_layers, n_cpu_moe,
    flash_attn, thinking, max_output_tokens, temperature, top_p, top_k, min_p, …"""
    _ready()
    from . import db
    from .hub import hf
    if bool(repo) == bool(path):
        raise LLMDynoError("pass either a Hugging Face repo or path=")
    if path is not None:
        m = _model_from_path(Path(path).expanduser(), quant)
    else:
        m = _model_from_repo(repo, quant, download, quiet)
    with db.Session() as s:
        m = hf.model_dict(s.get(db.Model, m["id"]))
    given = _params("local", params)
    ctx = given.get("ctx")
    default_name = m["name"] + (f" · {ctx // 1024}k" if ctx else "")
    prof = _upsert_profile({"kind": "local", "name": name or default_name, "model_id": m["id"], "params": given})
    try:
        verdict = prof.check()
        if verdict.get("verdict") in ("oom", "spill"):
            _say(quiet, f"warning: {prof.name} is projected not to fit ({verdict['verdict']}); "
                        "check() shows the details and fixes")
    except LLMDynoError:
        pass
    return prof


def _model_from_path(p: Path, quant):
    from . import db
    from .hub import hf
    if not p.exists():
        raise NotFoundError(f"{p} does not exist")
    folder = p.parent if p.is_file() else p
    hf.import_folder(str(folder))
    with db.Session() as s:
        here = [hf.model_dict(m) for m in s.query(db.Model).all() if Path(m.local_dir).resolve() == folder.resolve()]
    if p.is_file():
        here = [m for m in here if p.name in m["files"] or Path(m["files"][0]).name == p.name]
    elif quant:
        here = [m for m in here if (m["quant"] or "").lower() == quant.lower()]
    if not here:
        raise NotFoundError(f"no readable GGUF model in {p}")
    if len(here) > 1:
        raise ConflictError(f"{len(here)} models in {p}: pass the file path or quant= ({', '.join(m['quant'] for m in here)})")
    return here[0]


def _model_from_repo(repo, quant, download, quiet):
    from . import db
    from .api import routes
    from .hub import hf

    def match(m):
        return not quant or (m.quant or "").lower() == quant.lower() or quant.lower() in (m.name or "").lower()
    with db.Session() as s:
        mine = [hf.model_dict(m) for m in s.query(db.Model).filter(db.Model.repo == repo).all() if match(m)]
    ready = [m for m in mine if m["status"] == "ready"]
    if ready:
        return ready[0]
    if not download:
        raise NotFoundError(f"{repo} {quant or ''} is not downloaded (pass download=True)".replace("  ", " "))
    if mine:                                              # an interrupted download: carry on
        r = _call(routes.model_resume, mine[0]["id"])
        _say(quiet, f"Resuming download of {repo} {mine[0]['quant']}")
        _wait_job(r["job_id"], quiet=quiet)
        return mine[0]
    info = hf.repo_files(repo)
    variants = [v for v in info["variants"] if not v["mmproj"]]
    if not quant:
        raise LLMDynoError(f"pick a quant for {repo}: {', '.join(v['quant'] for v in variants)}")
    hit = [v for v in variants if v["quant"].lower() == quant.lower()] or \
          [v for v in variants if quant.lower() in v["id"].lower()]
    if not hit:
        raise NotFoundError(f"{repo} has no {quant}; available: {', '.join(v['quant'] for v in variants)}")
    v = hit[0]
    _say(quiet, f"Downloading {repo} {v['quant']} ({v['size_bytes'] / 2**30:.1f} GB)")
    r = _call(routes.model_download, {"repo": repo, "variant_id": v["id"]})
    _wait_job(r["job_id"], quiet=quiet)
    return {"id": r["model_id"]}


# ================================================================== benchmarks
def list_benchmarks(category: str | None = None, search: str | None = None) -> list:
    """Benchmarks in the data folder (built-in, your own and imported), as dicts with id, title, category, …"""
    _ready()
    from .benchmarks import registry
    out = []
    for b in registry.all_benchmarks():
        if category and b.get("category", "").lower() != category.lower():
            continue
        text = f"{b['id']} {b.get('title', '')} {b.get('summary', '')} {' '.join(b.get('tags') or [])}".lower()
        if search and search.lower() not in text:
            continue
        out.append({k: b.get(k) for k in ("id", "title", "category", "difficulty", "languages", "summary", "n_stages",
                                          "expected_minutes", "builtin")})
    return out


def list_suites() -> list:
    """Suites (named groups of benchmarks): built-in ones plus yours and those created by imports."""
    _ready()
    from .benchmarks import registry
    return registry.suites()


def import_swebench(dataset: str = "verified_mini", *, limit: int | None = None,
                    instance_ids: Sequence[str] | None = None, quiet: bool = False) -> dict:
    """Import SWE-bench tasks as benchmarks: dataset "verified" (500), "lite" (300) or "verified_mini" (50).
    Grading needs the official harness: setup(swebench=True). Returns the new benchmark ids and suite id."""
    _ready()
    from .api import external_api
    r = _call(external_api.import_swebench, {"dataset": dataset, "limit": limit or 0,
                                             "instance_ids": list(instance_ids or [])})
    return _wait_job(r["job_id"], quiet=quiet)


def import_polyglot(languages: Sequence[str] | None = None, *, quiet: bool = False) -> dict:
    """Import Aider's polyglot benchmark (cpp, go, java, javascript, python, rust). Needs the toolchain image:
    setup(polyglot=True)."""
    _ready()
    from .api import external_api
    r = _call(external_api.import_polyglot, {"languages": list(languages) if languages else None})
    return _wait_job(r["job_id"], quiet=quiet)


# ================================================================== plans and results
def _as_list(x) -> list:
    if x is None:
        return []
    if isinstance(x, (str, Profile, Plan)):
        return [x]
    return list(x)


def _plan_body(models, benchmarks, harnesses, iterations, name, options):
    ids = [profile(m).id for m in _as_list(models)]
    if not ids:
        raise LLMDynoError("pass at least one model (a Profile, or a profile name or id)")
    return {"name": name or "", "profile_ids": ids, "harness_ids": _as_list(harnesses),
            "benchmark_ids": _as_list(benchmarks), "iterations": iterations,
            "options": {k: v for k, v in options.items() if v is not None}}


def preflight(models, benchmarks: Union[str, Sequence[str]] = "suite_quick",
              harnesses: Union[str, Sequence[str]] = "pi", *, iterations: int = 1, **options) -> dict:
    """What bench() would check before starting: blocking problems, warnings, and time and cost estimates."""
    _ready()
    from .api import routes
    return _call(routes.plan_preflight, _plan_body(models, benchmarks, harnesses, iterations, None, options))


def bench(models: Union[Profile, str, Sequence[Union[Profile, str]]],
          benchmarks: Union[str, Sequence[str]] = "suite_quick", harnesses: Union[str, Sequence[str]] = "pi", *,
          iterations: int = 1, name: str | None = None, budget_usd: float | None = None, quality: bool = True,
          timeout_multiplier: float | None = None, cloud_concurrency: int | None = None, allow_spill: bool = False,
          acknowledge_risks: bool = False, wait: bool = True, quiet: bool = False) -> Union["Results", "Plan"]:
    """Run models × harnesses × benchmarks × iterations and return the scored Results.

    models: Profiles (from cloud_model / local_model) or profile names. benchmarks: benchmark or suite ids
    (see list_benchmarks() and list_suites()); harnesses: pi, opencode, codex, qwen-code, crush, aider, mini-swe-agent.
    budget_usd caps this plan's cloud spend on top of each provider's own cap. Local models share the GPU one at a time;
    cloud runs go in parallel. The plan is checked first and PreflightError lists anything that blocks it; danger
    warnings (spill, out of memory, …) need acknowledge_risks=True. wait=False returns the running Plan instead."""
    _ready()
    from .api import routes
    options = {"budget_usd": budget_usd, "quality": quality, "timeout_multiplier": timeout_multiplier,
               "cloud_concurrency": cloud_concurrency, "allow_spill": allow_spill or None}
    body = _plan_body(models, benchmarks, harnesses, iterations, name, options)
    pf = _call(routes.plan_preflight, body)
    if not pf["ok"]:
        raise PreflightError([b["text"] for b in pf["blocking"]], [w["text"] for w in pf["warnings"]], pf)
    risky = [w["text"] for w in pf["warnings"] if w.get("ack")]
    if risky and not acknowledge_risks:
        raise PreflightError(risky + ["pass acknowledge_risks=True to run anyway (results will be flagged)"],
                             [w["text"] for w in pf["warnings"]], pf)
    for w in pf["warnings"]:
        _say(quiet, f"  {w['level']}: {w['text']}")
    est = pf["estimate"]
    _say(quiet, f"Plan: {pf['n_runs']} run(s), about {est['minutes']:.0f} min"
                + (f", about ${est['cost_usd']:.2f} in API costs" if est.get("cost_usd") else ""))
    created = _call(routes.create_plan, {**body, "start": True, "acknowledge_risks": acknowledge_risks})
    p = Plan(created["plan_id"], created.get("job_id"))
    return p.wait(quiet=quiet) if wait else p


class Plan:
    """A benchmark plan: its runs, live status, and results once it finishes."""

    def __init__(self, plan_id: str, job_id: str | None = None):
        self.id, self._job = plan_id, job_id

    def _get(self) -> dict:
        from .api import routes
        return _call(routes.get_plan, self.id)

    @property
    def name(self) -> str:
        return self._get()["name"]

    @property
    def status(self) -> str:
        """queued, running, paused, done, cancelled or failed."""
        return self._get()["status"]

    def runs(self) -> list:
        """Every run with its status, scores and timing."""
        return self._get().get("runs") or []

    def __repr__(self):
        d = self._get()
        return f"<llmdyno.Plan {d['name']!r} {d['status']} {d.get('counts')}>"

    def wait(self, quiet: bool = False) -> "Results":
        """Block until the plan stops, printing each run as it finishes. Ctrl+C cancels the plan."""
        from .api import routes
        seen = {}
        labels = _labels()
        try:
            while True:
                d = self._get()
                for r in d.get("runs") or []:
                    if r["status"] != seen.get(r["id"]) and r["status"] in ("done", "failed", "cancelled", "skipped"):
                        _say(quiet, "  " + _run_line(r, labels))
                    seen[r["id"]] = r["status"]
                job = d.get("job") or {}
                if d["status"] in ("done", "cancelled", "failed", "paused") and job.get("status") in (*TERMINAL, None):
                    break
                time.sleep(2)
        except KeyboardInterrupt:
            _say(quiet, "  cancelling the plan (finished runs are kept) …")
            _call(routes.cancel_plan, self.id)
            job = (self._get().get("job") or {}).get("id")
            if job:
                _drain(job)
            raise
        d = self._get()
        _say(quiet, f"Plan {d['status']}: {d.get('counts')}")
        return self.results()

    def results(self, **weights) -> "Results":
        return results(self, **weights)

    def cancel(self) -> None:
        from .api import routes
        _call(routes.cancel_plan, self.id)

    def pause(self) -> None:
        from .api import routes
        _call(routes.pause_plan, self.id)

    def resume(self, wait: bool = True, quiet: bool = False):
        from .api import routes
        _call(routes.resume_plan, self.id)
        return self.wait(quiet=quiet) if wait else self

    def swebench_predictions(self, path: Union[str, Path, None] = None) -> str:
        """The plan's SWE-bench patches in the official predictions JSONL format (written to path if given)."""
        from .api import external_api
        body = _call(external_api.swebench_predictions, self.id).body.decode("utf-8")
        if path:
            Path(path).write_text(body, encoding="utf-8")
        return body

    def open(self) -> str:
        """Open this plan in the dashboard (starts the web app in the background if it is not running)."""
        return _open_ui(f"/plans/{self.id}")


def list_plans() -> list:
    """Every plan in the data folder, newest first."""
    _ready()
    from .api import routes
    return [Plan(p["id"]) for p in routes.list_plans()]


def plan(plan_id: str) -> Plan:
    _ready()
    p = Plan(plan_id)
    p._get()
    return p


def _labels():
    from .api import results_api
    profs, harn, bl = results_api._labels()
    return {"profiles": profs, "harnesses": harn, "benchmarks": bl}


def _run_line(r, labels):
    prof = (labels["profiles"].get(r["profile_id"]) or {}).get("name", r["profile_id"])
    bench_title = (labels["benchmarks"].get(r["benchmark_id"]) or {}).get("title", r["benchmark_id"])
    h = labels["harnesses"].get(r["harness_id"], r["harness_id"])
    if r["status"] != "done":
        why = f": {r['error'][:140]}" if r.get("error") else ""
        return f"{r['status']:<9} {bench_title} · {prof} · {h}{why}"
    corr = r.get("correctness")
    mins = (r.get("wall_s") or 0) / 60
    cost = f" · ${r['cost_usd']:.4f}" if r.get("cost_usd") else ""
    return f"done      {bench_title} · {prof} · {h}: correctness {corr:.2f} in {mins:.1f} min{cost}"


def results(plans: Union[Plan, str, Sequence[Union[Plan, str]], None] = None, *, include_sample: bool = False,
            correctness: float | None = None, instruction_following: float | None = None,
            quality: float | None = None, efficiency: float | None = None) -> "Results":
    """Scored results for some plans (default: every plan except the bundled sample). The four weights reshape
    the final score the way the Results page does (defaults 50/15/25/10)."""
    _ready()
    from . import config
    from .api import results_api
    ids = [p.id if isinstance(p, Plan) else p for p in _as_list(plans)]
    w = dict(config.get("weights"))
    for k, v in (("correctness", correctness), ("instruction_following", instruction_following),
                 ("quality", quality), ("efficiency", efficiency)):
        if v is not None:
            w[k] = v
    data = results_api.results(plan_ids=",".join(ids), weights=json.dumps(w), quality_weights="",
                               include_sample=include_sample or bool(ids), benchmark_ids="")
    return Results(data, ids)


class Results:
    """Scored results. print(results) shows the leaderboard; leaderboard() and runs() return rows; to_pandas(),
    to_csv() and to_json() export them; open() shows the dashboard."""

    def __init__(self, data: dict, plan_ids: Sequence[str] = ()):
        self.data, self.plan_ids = data, list(plan_ids)
        self._labels = data.get("labels") or {}

    def _name(self, r):
        p = (self._labels.get("profiles") or {}).get(r["profile_id"]) or {}
        return p.get("name") or r["profile_id"]

    def _harness(self, r):
        return (self._labels.get("harnesses") or {}).get(r["harness_id"], r["harness_id"])

    def leaderboard(self) -> list:
        """One row per profile × harness, best first. Scores are 0-100."""
        rows = []
        for i, c in enumerate(self.data.get("configs") or [], 1):
            pct = lambda v: None if v is None else round(v * 100, 1)   # noqa: E731
            rows.append({"rank": i, "profile": self._name(c), "harness": self._harness(c), "final": pct(c.get("final")),
                         "correctness": pct(c.get("correctness")),
                         "instruction_following": pct(c.get("instruction_following")),
                         "quality": pct(c.get("quality")), "efficiency": pct(c.get("efficiency")),
                         "pass_at_k": pct(c.get("pass_at_k")), "runs": c.get("runs"),
                         "wall_s_total": c.get("wall_s_total"), "cost_usd_total": c.get("cost_usd_total"),
                         "decode_tps": c.get("decode_tps"), "peak_vram_mib": c.get("peak_vram_mib"),
                         "profile_id": c["profile_id"], "harness_id": c["harness_id"]})
        return rows

    def runs(self) -> list:
        """One row per run (benchmark × iteration)."""
        bl = self._labels.get("benchmarks") or {}
        out = []
        for r in self.data.get("runs") or []:
            out.append({"run_id": r["id"], "plan_id": r["plan_id"], "profile": self._name(r), "harness": self._harness(r),
                        "benchmark": (bl.get(r["benchmark_id"]) or {}).get("title", r["benchmark_id"]),
                        "benchmark_id": r["benchmark_id"], "iteration": r["iteration"],
                        "final": r.get("final"), "correctness": r.get("correctness"),
                        "instruction_following": r.get("instruction_following"), "quality": r.get("quality"),
                        "tests_passed": r.get("tests_passed"), "tests_total": r.get("tests_total"),
                        "wall_s": r.get("wall_s"), "cost_usd": r.get("cost_usd"),
                        "generated_tokens": r.get("generated_tokens"), "decode_tps": r.get("decode_tps"),
                        "ttft_s": r.get("ttft_median_s"), "peak_context_tokens": r.get("peak_context_tokens"),
                        "spill": r.get("spill_detected")})
        return out

    def public(self) -> list:
        """SWE-bench resolved rate and Aider polyglot solved rate per profile × harness (only when such runs exist)."""
        groups = {}
        for r in self.data.get("runs") or []:
            kind = "swebench" if r["benchmark_id"].startswith("swe_") else "polyglot" if r["benchmark_id"].startswith("pg_") else None
            if kind:
                g = groups.setdefault((r["profile_id"], r["harness_id"]), {"swebench": [], "polyglot": []})
                g[kind].append((r.get("correctness") or 0) >= 1)
        out = []
        for (pid, hid), g in groups.items():
            rate = lambda v: round(100 * sum(v) / len(v), 1) if v else None   # noqa: E731
            out.append({"profile": self._name({"profile_id": pid}), "harness": self._harness({"harness_id": hid}),
                        "swebench_resolved_pct": rate(g["swebench"]), "swebench_runs": len(g["swebench"]),
                        "polyglot_solved_pct": rate(g["polyglot"]), "polyglot_runs": len(g["polyglot"])})
        return out

    def best(self) -> dict | None:
        lb = self.leaderboard()
        return lb[0] if lb else None

    # -- export
    def to_pandas(self, level: str = "configs"):
        """A pandas DataFrame of the leaderboard (level="configs") or every run (level="runs")."""
        try:
            import pandas as pd
        except ImportError as e:
            raise LLMDynoError("to_pandas() needs pandas: pip install pandas") from e
        return pd.DataFrame(self.leaderboard() if level == "configs" else self.runs())

    def to_csv(self, path: Union[str, Path, None] = None, level: str = "configs") -> str:
        rows = self.leaderboard() if level == "configs" else self.runs()
        buf = io.StringIO()
        if rows:
            w = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        if path:
            Path(path).write_text(buf.getvalue(), encoding="utf-8")
        return buf.getvalue()

    def to_json(self, path: Union[str, Path, None] = None) -> dict:
        from . import __version__ as v
        out = {"llmdyno_version": v, "plans": self.plan_ids, "leaderboard": self.leaderboard(), "runs": self.runs(),
               "public": self.public(), "weights": self.data.get("weights")}
        if path:
            Path(path).write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
        return out

    def open(self) -> str:
        """Open these results in the dashboard (starts the web app in the background if it is not running)."""
        q = f"?plans={','.join(self.plan_ids)}" if self.plan_ids else ""
        return _open_ui(f"/results{q}")

    # -- display
    def __str__(self):
        lb = self.leaderboard()
        if not lb:
            return "No finished runs yet."
        cols = [("rank", "#"), ("profile", "Profile"), ("harness", "Harness"), ("final", "Final"),
                ("correctness", "Correct"), ("quality", "Quality"), ("runs", "Runs"), ("wall_s_total", "Time"),
                ("cost_usd_total", "Cost")]
        fmt = {"wall_s_total": lambda v: "–" if v is None else f"{v / 60:.1f} min",
               "cost_usd_total": lambda v: "–" if v is None else f"${v:.4f}"}
        table = [[fmt.get(k, lambda v: "–" if v is None else str(v))(r.get(k)) for k, _ in cols] for r in lb]
        widths = [max(len(h), *(len(row[i]) for row in table)) for i, (_, h) in enumerate(cols)]
        line = lambda cells: "  ".join(c.ljust(w) for c, w in zip(cells, widths)).rstrip()   # noqa: E731
        out = [line([h for _, h in cols]), line(["-" * w for w in widths])] + [line(r) for r in table]
        pub = [p for p in self.public() if p["swebench_runs"] or p["polyglot_runs"]]
        if pub:
            out.append("")
            for p in pub:
                bits = []
                if p["swebench_runs"]:
                    bits.append(f"SWE-bench resolved {p['swebench_resolved_pct']}% of {p['swebench_runs']}")
                if p["polyglot_runs"]:
                    bits.append(f"polyglot solved {p['polyglot_solved_pct']}% of {p['polyglot_runs']}")
                out.append(f"{p['profile']} · {p['harness']}: " + ", ".join(bits))
        return "\n".join(out)

    def __repr__(self):
        b = self.best()
        return (f"<llmdyno.Results {len(self.leaderboard())} configs, {len(self.runs())} runs"
                + (f", best {b['profile']} · {b['harness']} {b['final']}" if b else "") + ">")

    def _repr_html_(self):
        lb = self.leaderboard()
        if not lb:
            return "<p>No finished runs yet.</p>"
        import html
        keys = ["rank", "profile", "harness", "final", "correctness", "instruction_following", "quality", "efficiency",
                "runs", "cost_usd_total"]
        head = "".join(f"<th>{html.escape(k.replace('_', ' '))}</th>" for k in keys)
        body = "".join("<tr>" + "".join(f"<td>{html.escape('' if r.get(k) is None else str(r.get(k)))}</td>" for k in keys)
                       + "</tr>" for r in lb)
        return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


# ================================================================== judging
def review(plans: Union[Plan, str, Sequence[Union[Plan, str]]], judges: Union[Profile, str, Sequence], *,
          budget_usd: float | None = 1.0, concurrency: int = 4, quiet: bool = False) -> "Results":
    """Blind LLM code review of finished runs by one or more judge profiles (cloud or local), then fresh Results
    whose code-quality score includes the reviews. budget_usd caps the judges' spend."""
    _ready()
    from .api import routes
    ids = [p.id if isinstance(p, Plan) else p for p in _as_list(plans)]
    body = {"judge_profile_ids": [profile(j).id for j in _as_list(judges)], "plan_ids": ids,
            "budget_usd": budget_usd, "concurrency": concurrency, "skip_reviewed": True}
    r = _call(routes.start_judge, body)
    _wait_job(r["job_id"], quiet=quiet)
    return results(ids)


# ================================================================== web app
_server = {"thread": None, "url": None}


def _ui_url(port=None):
    from . import config
    return f"http://127.0.0.1:{port or int(config.get('port'))}"


def _ui_up(url) -> bool:
    import httpx
    try:
        return httpx.get(url + "/api/health", timeout=1.5).status_code < 500
    except httpx.HTTPError:
        return False


def serve(port: int | None = None, *, open_browser: bool = True, block: bool = True) -> str:
    """Start the dashboard on this data folder. block=False runs it in a background thread (handy in notebooks)."""
    _ready()
    import uvicorn
    url = _ui_url(port)
    if _ui_up(url):
        if open_browser:
            webbrowser.open(url)
        return url
    from . import config
    cfg = uvicorn.Config("llmdyno.server:app", host="127.0.0.1", port=port or int(config.get("port")), log_level="warning")
    server = uvicorn.Server(cfg)
    if block:
        if open_browser:
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        print(f"LLMDyno on {url}  (data: {config.DATA}); Ctrl+C stops it", flush=True)
        server.run()
        return url
    t = threading.Thread(target=server.run, daemon=True, name="llmdyno-ui")
    t.start()
    for _ in range(60):
        if _ui_up(url):
            break
        time.sleep(0.25)
    _server.update(thread=t, url=url)
    if open_browser:
        webbrowser.open(url)
    return url


def _open_ui(path: str) -> str:
    url = _ui_url()
    if not _ui_up(url):
        serve(open_browser=False, block=False)
    webbrowser.open(url + path)
    return url + path
