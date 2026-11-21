"""Artificial Analysis reference numbers: key, refresh and per-profile overrides."""
from __future__ import annotations

__all__: list[str] = []

# Web API routes this module does not cover yet (see sdk/parity.py); remove each one as it gets a library call.
PENDING_ROUTES = (
    "GET /api/references/aa",
    "PUT /api/references/aa/override",
    "POST /api/references/aa/refresh",
    "DELETE /api/settings/aa-key",
    "PUT /api/settings/aa-key",
)
