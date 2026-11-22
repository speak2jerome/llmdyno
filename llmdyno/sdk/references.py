# pyright: strict, reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false
"""Artificial Analysis reference numbers: key, refresh and per-profile overrides.

LLMDyno can show each profile's Artificial Analysis coding index next to its own results, so you can see how a model
ranks publicly and how it did on your machine and harness. It needs a free Artificial Analysis API key."""
from __future__ import annotations

from typing import Any

from ._core import id_of, call, covers

__all__ = ["aa_reference", "refresh_aa", "set_aa_key", "remove_aa_key", "set_aa_match"]


@covers("GET /api/references/aa")
def aa_reference() -> dict[str, Any]:
    """Whether a key is set and when the data was fetched, each profile's matched model and score ("matches",
    by profile id, with "manual" for hand-picked ones), and the model list to pick matches from."""
    return call("references.aa_reference")


@covers("POST /api/references/aa/refresh")
def refresh_aa(force: bool = False) -> dict[str, Any]:
    """Download the latest Artificial Analysis numbers (refreshed at most every 12 hours unless force=True; the free
    tier allows 100 requests a day).
    Returns {"models", "fetched_at"}."""
    return call("references.aa_refresh", body={"force": force})


@covers("PUT /api/settings/aa-key")
def set_aa_key(key: str) -> dict[str, Any]:
    """Save an Artificial Analysis API key in the data folder's secret store (free at artificialanalysis.ai)."""
    return call("references.set_aa_key", body={"key": key})


@covers("DELETE /api/settings/aa-key")
def remove_aa_key() -> dict[str, Any]:
    """Delete the saved Artificial Analysis API key."""
    return call("references.delete_aa_key")


@covers("PUT /api/references/aa/override")
def set_aa_match(profile: Any, slug: str | None) -> dict[str, Any]:
    """Pick which Artificial Analysis model a profile is compared with (its slug from aa_reference()["model_list"]),
    or None to go back to the automatic match. Returns every override."""
    return call("references.aa_override", body={"profile_id": id_of(profile), "slug": slug})["overrides"]
