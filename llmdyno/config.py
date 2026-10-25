"""Paths and persistent settings."""
import json
import os
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = Path(__file__).resolve().parent


def _default_data():
    """./data in a git checkout; otherwise the per-user data folder (pip installs must not write into site-packages)."""
    if (ROOT / "pyproject.toml").exists():
        return ROOT / "data"
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "LLMDyno"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "llmdyno"


DATA = Path(os.environ.get("LLMDYNO_DATA") or _default_data()).resolve()

DEFAULTS = {
    "models_dir": str(DATA / "models"),
    "runs_dir": str(DATA / "runs"),
    "bin_dir": str(DATA / "bin"),
    "port": 8777,
    "llama_port": 18180,
    "electricity_usd_per_kwh": 0.15,
    "theme": "system",
    "onboarded": False,
    "default_vram_margin_mib": 1024,
    "cloud_concurrency": 3,
    "proxy_idle_timeout_s": 900,
    "weights": {"correctness": 50, "instruction_following": 15, "quality": 25, "efficiency": 10},
    "quality_weights": {"static": 35, "probes": 30, "review": 35},
    "llama_cpp": {"path": "", "version": "", "backend": ""},
    "hf_token_set": False,
}

_lock = threading.Lock()


def settings_path():
    return DATA / "settings.json"


def load_settings():
    with _lock:
        try:
            saved = json.loads(settings_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = {}
    merged = json.loads(json.dumps(DEFAULTS))
    for k, v in saved.items():
        if isinstance(v, dict) and isinstance(merged.get(k), dict):
            merged[k].update(v)
        else:
            merged[k] = v
    return merged


def save_settings(patch):
    current = load_settings()
    for k, v in patch.items():
        if k not in DEFAULTS:
            raise KeyError(f"unknown setting {k}")
        if isinstance(v, dict) and isinstance(current.get(k), dict):
            current[k].update(v)
        else:
            current[k] = v
    with _lock:
        DATA.mkdir(parents=True, exist_ok=True)
        tmp = settings_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(current, indent=2), encoding="utf-8")
        os.replace(tmp, settings_path())
    return current


def get(key):
    return load_settings()[key]


def path(key):
    p = Path(get(key))
    p.mkdir(parents=True, exist_ok=True)
    return p
