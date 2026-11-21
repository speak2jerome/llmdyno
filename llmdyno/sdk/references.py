"""Artificial Analysis reference numbers: key, refresh and per-profile overrides.

LLMDyno can show each profile's Artificial Analysis coding index next to its own results, so you can see how a model
ranks publicly and how it did on your machine and harness. It needs a free Artificial Analysis API key."""
from __future__ import annotations

from ._core import _id, call, covers

__all__ = ["aa_reference", "refresh_aa", "set_aa_key", "remove_aa_key", "set_aa_match"]


@covers("GET /api/references/aa")
def aa_reference() -> dict:
    """Whether a key is set and when the data was fetched, each profile's matched model and score ("matches",
    by profile id, with "manual" for hand-picked ones), and the model list to pick matches from."""
    return call("references.aa_reference")


@covers("POST /api/references/aa/refresh")
def refresh_aa(force: bool = False) -> dict:
    """Download the latest Artificial Analysis numbers (cached for a day; the free tier allows 100 requests a day).
    Returns {"models", "fetched_at"}."""
    return call("references.aa_refresh", body={"force": force})


@covers("PUT /api/settings/aa-key")
def set_aa_key(key: str) -> dict:
    """Save an Artificial Analysis API key (encrypted in the data folder)."""
    return call("references.set_aa_key", body={"key": key})


@covers("DELETE /api/settings/aa-key")
def remove_aa_key() -> dict:
    return call("references.delete_aa_key")


@covers("PUT /api/references/aa/override")
def set_aa_match(profile, slug: str | None) -> dict:
    """Pick which Artificial Analysis model a profile is compared with (its slug from aa_reference()["model_list"]),
    or None to go back to the automatic match. Returns every override."""
    return call("references.aa_override", body={"profile_id": _id(profile), "slug": slug})["overrides"]
