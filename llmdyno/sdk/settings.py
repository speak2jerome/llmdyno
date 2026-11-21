"""Settings and tokens (Hugging Face)."""
from __future__ import annotations

import copy
from typing import Any

from ._core import call, covers

__all__ = ["Settings", "settings", "set_hf_token", "remove_hf_token"]

EDITABLE = ("models_dir", "runs_dir", "electricity_usd_per_kwh", "theme", "onboarded", "default_vram_margin_mib",
            "cloud_concurrency", "weights", "quality_weights", "llama_port")


class Settings:
    """The app's settings (the Settings page). Read them as attributes or keys:

        s = llmdyno.settings()
        s.cloud_concurrency, s["weights"], s.data_dir, s.hf_token_set
        s.update(cloud_concurrency=4, electricity_usd_per_kwh=0.30)

    Editable: models_dir, runs_dir, electricity_usd_per_kwh, theme, onboarded, default_vram_margin_mib,
    cloud_concurrency, weights, quality_weights, llama_port. The rest (data_dir, port, llama_cpp, hf_token_set, …)
    are read-only here."""

    def __init__(self, data: dict):
        self._d = dict(data)

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self._d[name]
        except KeyError:
            raise AttributeError(f"no setting {name!r}") from None

    def __getitem__(self, key: str) -> Any:
        return self._d[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self._d.get(key, default)

    def __dir__(self):
        return sorted(set(super().__dir__()) | set(self._d))

    def to_dict(self) -> dict:
        return copy.deepcopy(self._d)

    def refresh(self) -> "Settings":
        self._d = call("settings.get_settings")
        return self

    @covers("PATCH /api/settings")
    def update(self, **changes) -> "Settings":
        """Change and save settings, e.g. update(cloud_concurrency=4). Weights merge into the current ones."""
        unknown = set(changes) - set(EDITABLE)
        if unknown:
            raise TypeError(f"cannot change {', '.join(sorted(unknown))}; editable: {', '.join(EDITABLE)}")
        call("settings.patch_settings", body=changes)
        return self.refresh()

    def __repr__(self):
        keys = ("data_dir", "cloud_concurrency", "weights")
        return "<llmdyno.Settings " + " ".join(f"{k}={self._d.get(k)!r}" for k in keys) + ">"


@covers("GET /api/settings")
def settings() -> Settings:
    """The current settings."""
    return Settings(call("settings.get_settings"))


@covers("PUT /api/settings/hf-token")
def set_hf_token(token: str) -> None:
    """Save a Hugging Face token (encrypted in the data folder) for gated models and higher rate limits."""
    call("settings.set_hf_token", body={"token": token})


@covers("DELETE /api/settings/hf-token")
def remove_hf_token() -> None:
    call("settings.del_hf_token")
